"""Find the manual's installation, maintenance and troubleshooting tasks and build
their guides.

Relevant instructions can be scattered across many pages. This file discovers
possible tasks across the manual, organizes related passages, and starts separate
investigations for the resulting guides. Independent guides can progress together
while each retains its own evidence and completion status."""

import json
from collections import Counter

from workbench.agentic_workflow.model_call_allowances import BudgetPause
from workbench.agentic_workflow.run_source_group_tasks import digest, run_stage
from workbench.agentic_workflow.schedule_independent_model_tasks import completed_tasks
from workbench.job_storage import job_files_and_audit_log as storage
from workbench.manual_analysis.check_source_quotations import (
    source_map,
)
from workbench.manual_analysis.group_sources_for_uncertainty_review import build_batches
from workbench.manual_analysis.validate_faq_and_troubleshooting import cite
from workbench.model_access.code_owned_source_evidence import evidence_task
from workbench.model_access.model_requests_and_responses import (
    InvalidModelResponseError,
)
from workbench.procedure_guides.consolidate_source_linked_tasks import (
    consolidate_source_linked_tasks,
)
from workbench.procedure_guides.plan_source_linked_procedures import (
    plan_source_linked_procedure,
)
from workbench.procedure_guides.procedure_reply_models import ProcedureCandidates
from workbench.procedure_guides.retain_failed_procedure_result import (
    retain_failed_procedure_result,
)


def legacy_procedure_discovery_prompt(batch):
    """Ask which procedures are actually supported by this source group.

    Args:
        batch: Original text/table records assigned to this discovery request.
    Returns:
        Instructions and unchanged source evidence. This only discovers leads;
        later planning must find the sequence, prerequisites, warnings and checks.
    """
    return evidence_task(
        "Identify practical installation/setup, maintenance and troubleshooting tasks supported by these passages. "
        "Use kind for installation, maintenance or troubleshooting; use role separately for procedure, requirement, warning or stop_condition. "
        "Supporting warnings are not separate procedures. Use concise task titles and select supporting passages. "
        "Do not invent a procedure from a topic label or an absent category. Return no procedures when none are supported.",
        {},
        batch,
    )


def procedure_discovery_prompt(batch):
    """Explain the separate guide destination and source-lead role in plain English.

    Args:
        batch: Original source records for one discovery request.
    Returns:
        Product-neutral discovery instructions and unchanged source passages. Kind
        selects a guide destination; role describes the lead, not a fourth guide type.
    """
    return legacy_procedure_discovery_prompt(batch)


def generate_manual_procedure_guides(job_id, profile, document, run):
    """Discover every source group, then plan independent procedures with shared budgets.

    Args:
        job_id: Existing manual job receiving discovery and planner checkpoints.
        profile: Existing facts, FAQ and issue-specific trees, preserved in the result.
        document: Parsed original manual with ordered evidence records.
        run: Shared model-call owner with bounded parallelism and exact Resume.
    Returns:
        Copied profile with procedure_guides and discovery counts. Writes validated
        candidate and guide files, including rejected leads and unfinished procedures.
        Publishes each finished investigation as a partial profile so interactive
        guide views are available while other investigations continue.
        Provider failures pause/stop the caller after all active workers settle.
    """
    old_discovery = storage.job_dir(job_id) / "procedure-discovery-v2-stage.json"
    reuse_old_discovery = old_discovery.exists() and json.loads(
        old_discovery.read_text()
    ).get("complete")
    results = run_stage(
        job_id,
        "procedure-discovery-v2" if reuse_old_discovery else "procedure-discovery-v3",
        "Discover source-linked procedures",
        build_batches(document["items"]),
        legacy_procedure_discovery_prompt
        if reuse_old_discovery
        else procedure_discovery_prompt,
        ProcedureCandidates,
        run,
        0.5,
    )
    leads, rejected = {}, []
    for batch, reply in results:
        for candidate in reply.procedures:
            value = candidate.model_dump()
            try:
                checked = cite(value, source_map(batch))
            except ValueError as error:
                rejected.append({"proposal": value, "reason": str(error)})
                continue
            key = digest(
                [candidate.kind, candidate.title, candidate.role, checked["citations"]]
            )[:20]
            leads[key] = {
                "id": key,
                "kind": candidate.kind,
                "title": candidate.title,
                "role": candidate.role,
                "citations": checked["citations"],
                "evidence_ids": sorted(
                    {c["evidence_id"] for c in checked["citations"]}
                ),
            }
    candidates, unassigned = consolidate_source_linked_tasks(
        job_id, list(leads.values()), run
    )
    diagnostic = [c for c in candidates if c["kind"] == "troubleshooting"]
    if diagnostic:
        candidates.insert(
            0,
            {
                "id": "troubleshooting-from-start",
                "kind": "troubleshooting",
                "title": "Troubleshoot from the beginning",
                "scope": "top_level",
                "evidence_ids": sorted(
                    {source for c in diagnostic for source in c["evidence_ids"]}
                ),
                "related_symptoms": [c["title"] for c in diagnostic],
                "related_symptoms_total": len(diagnostic),
            },
        )
    path = storage.job_dir(job_id)
    storage.save(
        path / "procedure-candidates-v2.json",
        {"candidates": candidates, "rejected": rejected, "unassigned": unassigned},
    )
    workers = getattr(run, "concurrency", 1)
    guides = {}

    def execute(candidate):
        """Assign one independently saved procedure investigation to a worker.

        Args:
            candidate: Source-backed procedure title, kind, ID and initial evidence.
        Returns:
            Validated or explicitly unfinished guide; failures retain saved work.
        """
        try:
            return plan_source_linked_procedure(job_id, candidate, document, run)
        except InvalidModelResponseError as error:
            return retain_failed_procedure_result(job_id, candidate, error)

    errors = []
    for candidate, guide, error in completed_tasks(
        candidates, execute, workers, can_start=lambda: run.dispatch_error is None
    ):
        if error is not None:
            errors.append(error)
            run.stop_dispatch(error)
        else:
            guides[candidate["id"]] = guide
            storage.save(
                path / "profile.json",
                {
                    **profile,
                    "procedure_guides": list(guides.values()),
                    "procedure_generation_pending": True,
                    "review_pending": True,
                },
            )
            storage.save(
                path / "procedure-guides-progress.json",
                {"guides": list(guides.values()), "total": len(candidates)},
            )
    if errors:
        raise next(
            (error for error in errors if not isinstance(error, BudgetPause)),
            errors[0],
        )
    result = [guides[c["id"]] for c in candidates]
    storage.save(
        path / "procedure-guides-complete.json", {"guides": result, "complete": True}
    )
    failures = sum(bool(g.get("generation_failed")) for g in result)
    notices = list(profile.get("processing_notices", []))
    if failures:
        notices.append(
            {
                "issue": f"{failures} procedure guide(s) could not finish because their model replies remained invalid. Other guides were retained.",
                "severity": "review",
                "evidence_ids": [],
            }
        )
    return {
        **profile,
        "processing_notices": notices,
        "procedure_guides": result,
        "procedure_generation_pending": False,
        "procedure_outcomes": dict(Counter(g["status"] for g in result)),
        "procedure_discovery": {
            "source_groups": len(results),
            "candidates": len(candidates),
            "rejected": len(rejected),
            "available_leads": len(leads),
            "unassigned": unassigned,
            "planner_version": 3,
        },
    }
