"""Create reader questions and troubleshooting guidance from the manual's text.

These requests use original passages and the extracted facts they support, rather
than asking an AI to answer from memory. FAQs and troubleshooting material are
created separately so each answer has room to be detailed. Citations are checked
before accepted material is added to the saved results."""

import json
from workbench.job_storage import job_files_and_audit_log as storage
from workbench.data_models.analysis_and_question_models import (
    FAQGeneration,
    TroubleshootingChecksGeneration,
    TroubleshootingGeneration,
)
from workbench.model_prompts.analysis_task_prompts import (
    FAQ,
    CHECKS,
    TREES,
    LEGACY_TREES,
    aids_prompt,
)
from workbench.procedure_guides.legacy_cited_gap_schemas import (
    LegacyTroubleshootingGeneration,
)
from workbench.agentic_workflow.run_source_group_tasks import run_stage
from workbench.manual_analysis.group_sources_for_fact_extraction import (
    build_fact_batches,
    saved_grouping_version,
)
from workbench.manual_analysis.check_source_quotations import source_map
from workbench.manual_analysis.validate_faq_and_troubleshooting import cite, check_tree


def generate_aid(job_id, profile, document, run, kind):
    """Generate and validate one kind of decision aid without changing the source facts.

    Args:
        job_id: Job receiving independent FAQ or troubleshooting progress.
        profile: Completed Task A/B results; facts supply context, not new evidence.
        document: Original parsed manual used for every citation check.
        run: Authorized model-call owner, shared with the other stages in this slice.
        kind: faq or troubleshooting_checks; troubleshooting is retained for legacy audits.
    Returns:
        Accepted aid dictionaries. Saves rejected proposals and completed-stage output.
        Invalid trees and unmatched quotations are rejected, never silently repaired.
    """
    is_faq = kind == "faq"
    schema = FAQGeneration if is_faq else TroubleshootingGeneration
    instructions = FAQ if is_faq else TREES
    if kind == "troubleshooting_checks":
        schema, instructions = TroubleshootingChecksGeneration, CHECKS
    stage_path = storage.job_dir(job_id) / "troubleshooting-stage.json"
    legacy_requests = (
        kind == "troubleshooting"
        and stage_path.exists()
        and any(
            (record.get("schema") or {}).get("title") == "TroubleshootingGeneration"
            and record["schema"]
            .get("$defs", {})
            .get("DiagnosticNode", {})
            .get("properties", {})
            .get("citations", {})
            .get("minItems")
            == 1
            for record in (
                json.loads(file.read_text())
                for file in storage.job_dir(job_id).glob("call-*-request.json")
            )
        )
    )
    if legacy_requests:
        # Completed old trees are revalidated with their original prompt and schema.
        # This avoids repaying for finished generation merely to clarify gap semantics.
        schema = LegacyTroubleshootingGeneration
        instructions = LEGACY_TREES
    fraction = 0.625 if is_faq else 0.75
    title = "Generate FAQ" if is_faq else "Generate troubleshooting checks"
    planning_version = saved_grouping_version(
        storage.job_dir(job_id) / f"{kind}-stage.json"
    )
    batches = build_fact_batches(
        document["items"],
        run.service.output_allowance("text", fraction),
        planning_version,
    )

    def prompt(batch):
        """Build only this aid's request with the facts matching its source passages.

        Args:
            batch: Bounded original source records for one request.
        Returns:
            FAQ-only or troubleshooting-only instructions, facts and source text.
        """
        return aids_prompt(instructions, batch, profile["facts"])

    results = run_stage(
        job_id,
        kind,
        title,
        batches,
        prompt,
        schema,
        run,
        fraction,
        planning_version=planning_version,
        isolate_invalid_replies=True,
    )
    accepted, rejected = [], []
    for batch, response in results:
        sources = source_map(batch)
        for proposal in getattr(response, kind):
            value = proposal.model_dump()
            try:
                if kind == "troubleshooting":
                    check_tree(value)
                checked = cite(value, sources)
                if checked not in accepted:
                    accepted.append(checked)
            except ValueError as exc:
                rejected.append({"kind": kind, "proposal": value, "reason": str(exc)})
    path = storage.job_dir(job_id)
    stage_file = path / f"{kind}-stage.json"
    if stage_file.exists():
        rejected.extend(
            {
                "kind": kind,
                "source_ids": [i["id"] for i in task["batch"]],
                "reason": task["failure"],
            }
            for task in json.loads(stage_file.read_text())["tasks"]
            if task.get("failure")
        )
    storage.save(
        path / f"{kind}-complete.json",
        {"complete": True, "accepted": accepted, "rejected": rejected},
    )
    return accepted


def generate_decision_aids(job_id, profile, document, run):
    """Extract FAQ and independent checks; only later investigations construct paths.

    Args:
        job_id: Job receiving the two generated outputs.
        profile: Accepted facts and reviewed uncertainties from Tasks A and B.
        document: Original manual text; unreviewed visual interpretations stay separate.
        run: Current model-call allowance; pauses propagate without publishing completion.
    Returns:
        Profile with FAQ and independent checks. Trees are left to later investigations.
        Invalid groups remain in rejection records and processing notices, not accepted output.
        Does not change the facts or claim that source matches certify safe repairs.
    """
    faq = generate_aid(job_id, profile, document, run, "faq")
    checks = generate_aid(job_id, profile, document, run, "troubleshooting_checks")
    path = storage.job_dir(job_id)
    rejected = []
    for kind in ("faq", "troubleshooting_checks"):
        rejected.extend(
            json.loads((path / f"{kind}-complete.json").read_text())["rejected"]
        )
    storage.save(path / "guidance-rejected.json", rejected)
    return {
        **profile,
        "faq": faq,
        "troubleshooting": [],
        "troubleshooting_checks": checks,
        "guidance_rejected_count": len(rejected),
        "processing_notices": profile.get("processing_notices", [])
        + (
            [
                {
                    "issue": f"{len(rejected)} generated guidance groups or proposals were rejected; retained guidance is incomplete.",
                    "severity": "review",
                    "evidence_ids": [],
                }
            ]
            if rejected
            else []
        ),
    }
