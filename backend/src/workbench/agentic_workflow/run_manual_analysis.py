"""Run the steps that turn a parsed manual into usable, source-linked results.

The application extracts facts, makes FAQs and troubleshooting aids, investigates
procedure guides, and publishes reports and searchable text. It then checks
uncertainties while the earlier results remain available. This file chooses that
order and records completion, pauses and failures; it does not treat a failed
stage as a successful analysis."""

import json
import logging
from workbench.procedure_guides.generate_manual_procedure_guides import (
    generate_manual_procedure_guides,
)

from pydantic import ValidationError

from workbench.manual_analysis.generate_faq_and_troubleshooting import (
    generate_decision_aids,
)
from workbench.manual_analysis.extract_manual_facts import extract
from workbench.manual_analysis.discover_and_review_uncertainties import (
    review_uncertainties,
)
from workbench.model_access.model_requests_and_responses import ModelError
from workbench.job_storage import job_files_and_audit_log as storage
from workbench.result_exports.write_reports_and_data_exports import publish
from workbench.document_search import index as knowledge

from workbench.agentic_workflow.model_call_allowances import BudgetPause
from workbench.agentic_workflow.run_source_group_tasks import digest
from workbench.agentic_workflow.execution import Run
from workbench.agentic_workflow.validate_and_correct_model_json import (
    validation_message,
)


from workbench.data_models.application_types import (
    ParsedDocument,
    InspectionResult,
    ExtractionResult,
)


def make_profile(
    document: ParsedDocument,
    inspection: InspectionResult,
    extraction: ExtractionResult,
) -> dict:
    """Assemble validated stage outputs without generating new factual statements.

    Args:
        document: Parsed manual with parser outcome.
        inspection: Historical classification and visual observations, or an explicit
            not-run record. No new preliminary inspection is requested.
        extraction: Accepted facts and rejection records, with empty FAQ/tree lists until their stages run.
    Returns:
        Profile ready for Task B. Processing problems are kept separate from manual
        ambiguities, so the model is not asked to resolve parser or quote-check errors.
    """
    facts = extraction["facts"]
    findings = []
    if extraction["rejected"]:
        findings.append(
            {
                "issue": f"{len(extraction['rejected'])} fact proposals failed source-quote checks.",
                "severity": "review",
                "evidence_ids": [],
            }
        )
    if document["parser_status"] != "success":
        findings.append(
            {
                "issue": "Parser reported incomplete extraction. Review the sources.",
                "severity": "critical",
                "evidence_ids": [],
            }
        )
    if inspection.get("inspection_status") in ("allowance_reached", "unfinished"):
        findings.append(
            {
                "issue": "Preliminary inspection is unfinished: "
                + "; ".join(inspection.get("remaining_questions", [])),
                "severity": "review",
                "evidence_ids": [],
            }
        )
    visuals = [
        o["result"]
        for o in inspection["observations"]
        if o["action"] == "inspect_image" and "observation" in o["result"]
    ]
    # Visual observations remain separate; do not ask text-only gap review to certify them.
    decisions = inspection["decisions"]
    return {
        "document_type": decisions[0]["document_type"] if decisions else "unknown",
        "purpose": decisions[0]["purpose"] if decisions else "unknown",
        "facts": facts,
        "findings": [],
        "processing_notices": findings,
        "inspection_status": inspection.get("inspection_status", "not_recorded"),
        "inspection_allowance": inspection.get("allowance"),
        "visual_observations": visuals,
        "vision_calls": len(visuals),
        "troubleshooting": extraction["troubleshooting"],
        "faq": extraction["faq"],
        "guidance_rejected_count": len(extraction["guidance_rejected"]),
        "task_version": 3,
        "batches_processed": extraction["batches_processed"],
        "batches_total": extraction["batches_processed"],
        "coverage_note": f"{extraction['batches_processed']} source batches processed; {len(facts)} source-anchored facts. Machine interpretation and safety coverage require review.",
    }


def complete(job_id, profile, document, index_ready=False):
    """Publish reports and searchable evidence only after required analysis finishes.

    Args:
        job_id: Job whose extraction and review completed successfully.
        profile: Source-anchored results including troubleshooting and FAQ assets.
        document: Original parsed evidence used to build the local knowledge base.
        index_ready: True only when this workflow has already indexed these sources.
    Returns:
        None; writes exports/vectors and final ready state. Failures propagate to
        the workflow handler, leaving existing artifacts inspectable but not ready.
    """
    storage.update(job_id, stage="Publish source-linked assets")
    publish(job_id, profile)
    storage.update(job_id, stage="Write local vector knowledge base")
    chunks = (
        json.loads((storage.job_dir(job_id) / "chunks.json").read_text())
        if index_ready
        else knowledge.build(job_id, document)
    )
    review = [
        {**f, "status": "open", "note": ""}
        for f in profile["findings"] + profile.get("processing_notices", [])
    ]
    for visual in profile["visual_observations"]:
        review.append(
            {
                "issue": f"Image interpretation on PDF page {visual['page']} needs human review.",
                "severity": "review",
                "evidence_ids": [],
                "status": "open",
                "note": "",
            }
        )
    storage.update(
        job_id,
        status="ready",
        stage="Analysis complete",
        chunks=len(chunks),
        facts=len(profile["facts"]),
        review=review,
        message=profile["coverage_note"],
    )
    storage.event(
        job_id,
        "completed",
        facts=len(profile["facts"]),
        chunks=len(chunks),
        vision_calls=profile["vision_calls"],
        troubleshooting=len(profile["troubleshooting"]),
        faq=len(profile["faq"]),
        extraction_batches_processed=profile["batches_processed"],
        extraction_batches_total=profile["batches_total"],
    )


def analyze(job_id: str, resume: bool = False, service=None):
    """Execute or explicitly continue the production manual workflow.

    Args:
        job_id: Parsed job already authorized for model calls through the UI/API.
        resume: Reuse compatible receipts and checkpoints; grants one new bounded slice.
        service: Optional neutral model service for integration tests; production uses config.
    Returns:
        None; starts directly with fact extraction and preserves historical inspection
        receipts on Resume without requesting more inspections. Persists ready,
        paused or failed state. Output-limited task groups may
        be subdivided within the current allowance; other failures stop the run.
        Pauses allow another explicit continuation; failures retain a safe explanation.
    """
    path = storage.job_dir(job_id)
    storage.update(
        job_id,
        status="analyzing",
        stage="Extract source-linked facts",
        message="",
        active_model_calls=[],
    )
    try:
        document = json.loads((path / "document.json").read_text())
        run = Run(job_id, service=service, replay=resume)
        storage.event(
            job_id,
            "analysis_slice",
            resume=resume,
            call_allowance=run.limit,
            parallel_limit=run.concurrency,
        )
        # Retain old inspection evidence for comparison, without invoking the retired
        # model loop. Fresh runs do not claim a classification or visual assessment.
        inspection_path = path / "decisions.json"
        inspection = (
            json.loads(inspection_path.read_text())
            if inspection_path.exists()
            else {"decisions": [], "observations": [], "inspection_status": "not_run"}
        )
        storage.update(job_id, preliminary_inspection_enabled=False)
        extraction = extract(job_id, document, run)
        profile = make_profile(document, inspection, extraction)
        profile = generate_decision_aids(job_id, profile, document, run)
        from workbench.result_illustrations.prepare_source_illustrations import prepare

        storage.update(job_id, stage="Prepare reference illustrations")
        prepare(job_id, document, run)
        # Let readers inspect completed facts, FAQ and issue-specific trees while
        # the longer guide investigations continue. This is not final publication.
        storage.save(
            path / "profile.json",
            {
                **profile,
                "procedure_guides": [],
                "procedure_generation_pending": True,
                "review_pending": True,
            },
        )
        profile = generate_manual_procedure_guides(job_id, profile, document, run)
        profile["review_pending"] = True
        storage.update(job_id, stage="Publish source-linked assets")
        publish(job_id, profile)
        marker = path / "usable-results-source.json"
        source_hash = digest(document)
        if (
            not marker.exists()
            or json.loads(marker.read_text())["source_hash"] != source_hash
        ):
            storage.update(job_id, stage="Write local vector knowledge base")
            chunks = knowledge.build(job_id, document)
            # Fixture indexes may only return chunks; persist the same manifest here
            # so production and injected providers share the completed-index boundary.
            storage.save(path / "chunks.json", chunks)
            storage.save(marker, {"source_hash": source_hash})
        storage.update(job_id, results_available=True)
        storage.event(
            job_id, "usable_results_available", uncertainty_review_pending=True
        )
        profile = review_uncertainties(job_id, profile, document, run)
        profile["review_pending"] = False
        complete(job_id, profile, document, index_ready=True)
    except BudgetPause as exc:
        storage.event(job_id, "workflow_paused", reason=str(exc))
        storage.update(
            job_id, status="paused", stage="Analysis paused", message=str(exc)
        )
    except Exception as exc:
        safe = (
            validation_message(exc)
            if isinstance(exc, ValidationError)
            else str(exc)
            if isinstance(exc, ModelError)
            else f"{type(exc).__name__}: output or processing failed validation"
        )
        storage.event(
            job_id,
            "workflow_error",
            error=type(exc).__name__,
            message=safe,
            blocked=True,
        )
        storage.update(job_id, status="failed", stage="Analysis stopped", message=safe)
        logging.exception("Analysis failed for %s", job_id)
