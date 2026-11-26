"""Try to finish the reviews that are keeping saved guides from reaching completed
output.

Existing drafts are rechecked before any rewrite, using their saved evidence.
Necessary corrections return through the normal guide-writing and review process.
Accepted guides and original extraction remain intact, and completed repairs
update the reader's results. A failed or exhausted attempt stays visibly
unresolved."""

import json
from uuid import uuid4
from collections import Counter

from workbench.agentic_workflow.model_call_allowances import BudgetPause
from workbench.agentic_workflow.run_source_group_tasks import digest
from workbench.agentic_workflow.schedule_independent_model_tasks import completed_tasks
from workbench.agentic_workflow.send_and_record_model_requests import Run
from workbench.job_storage import job_files_and_audit_log as storage
from workbench.procedure_guides.plan_source_linked_procedures import (
    plan_source_linked_procedure,
    PLANNER_INSTRUCTIONS,
    FINALIZER_INSTRUCTIONS,
)
from workbench.procedure_guides.review_guide_with_separate_jobs import (
    review_configuration,
)
from workbench.result_exports.write_reports_and_data_exports import publish

REPAIR_CALL_LIMIT = 240


def repair_unresolved_manual_guides(job_id, resume=False, service=None):
    """Repair blocked saved guides through the normal planner, reviewer and publisher.

    Args:
        job_id: Existing analysed manual with source-linked planner checkpoints.
        resume: Continue the frozen recovery batch and reuse exact successful requests.
            If review policy changed, archive the old batch and recheck only guides
            still blocked in the published profile; never reuse incompatible approval.
        service: Optional isolated model service for tests; otherwise configured models.
    Returns:
        None; saves a frozen original profile and planner states before work, then
        republishes each completed recovery without dropping other guides. Extraction,
        PDF and original planner checkpoints are untouched. A bounded call allowance
        pauses work; provider failures stop dispatch and remain visible. Unchanged
        failed drafts are never promoted. Repeated starts reuse the frozen batch.
    """
    path = storage.job_dir(job_id)
    storage.update(
        job_id,
        status="analyzing",
        operation="procedure_review_repair",
        stage="Repair unresolved guide reviews",
        active_model_calls=[],
    )
    try:
        manifest_path = path / "procedure-review-recovery.json"
        policy = digest(
            [
                "bounded-review-recovery-v2",
                PLANNER_INSTRUCTIONS,
                FINALIZER_INSTRUCTIONS,
                review_configuration(),
            ]
        )
        prior_checkpoints = None
        if (
            manifest_path.exists()
            and json.loads(manifest_path.read_text()).get("policy") != policy
        ):
            archive = path / "procedure-review-recovery-history" / uuid4().hex
            archive.mkdir(parents=True)
            manifest_path.rename(archive / manifest_path.name)
            old_checkpoints = path / "procedure-repairs-v1"
            if old_checkpoints.exists():
                prior_checkpoints = archive / old_checkpoints.name
                old_checkpoints.rename(prior_checkpoints)
            storage.event(
                job_id,
                "procedure_recovery_policy_changed",
                archive=str(archive.relative_to(path)),
                policy=policy,
            )

        if manifest_path.exists():
            batch = json.loads(manifest_path.read_text())
        else:
            profile = json.loads((path / "profile.json").read_text())
            candidates = {
                c["id"]: c
                for c in json.loads(
                    (path / "procedure-candidates-v2.json").read_text()
                )["candidates"]
            }
            targets = []
            for guide in profile.get("procedure_guides", []):
                if guide.get("completion") != "review_unresolved":
                    continue
                checkpoint_path = path / "procedure-plans-v3" / (guide["id"] + ".json")
                if (
                    prior_checkpoints
                    and (prior_checkpoints / checkpoint_path.name).exists()
                ):
                    checkpoint_path = prior_checkpoints / checkpoint_path.name
                checkpoint = json.loads(checkpoint_path.read_text())
                # Recheck the published draft, not an unpublished partial revision.
                # The archived evidence retains any additional inspected sources.
                checkpoint["result"] = guide
                targets.append(
                    {"candidate": candidates[guide["id"]], "saved": checkpoint}
                )
            batch = {"policy": policy, "profile": profile, "targets": targets}
            storage.save(manifest_path, batch)
        document = json.loads((path / "document.json").read_text())
        profile = json.loads((path / "profile.json").read_text())
        guides = {g["id"]: g for g in profile["procedure_guides"]}
        run = Run(
            job_id,
            limit=REPAIR_CALL_LIMIT,
            service=service,
            replay=resume,
            concurrency=3,
        )

        def execute(target):
            """Run one frozen saved draft through shared production planning.

            Args:
                target: Original candidate and original planner evidence/result.
            Returns:
                Reviewed or explicitly unresolved result in a separate checkpoint.
                Model and budget exceptions propagate to the batch coordinator.
            """
            return plan_source_linked_procedure(
                job_id, target["candidate"], document, run, recovery=target["saved"]
            )

        errors = []
        for target, guide, error in completed_tasks(
            batch["targets"],
            execute,
            run.concurrency,
            can_start=lambda: run.dispatch_error is None,
        ):
            if error:
                errors.append(error)
                run.stop_dispatch(error)
                continue
            guides[guide["id"]] = guide
            profile["procedure_guides"] = list(guides.values())
            profile["procedure_outcomes"] = dict(
                Counter(g["status"] for g in guides.values())
            )
            publish(job_id, profile)
            storage.save(
                path / "procedure-guides-progress.json",
                {"guides": list(guides.values()), "total": len(guides)},
            )
            storage.save(
                path / "procedure-guides-complete.json",
                {"guides": list(guides.values()), "complete": True},
            )
            storage.event(
                job_id,
                "procedure_review_recovered",
                procedure_id=guide["id"],
                completion=guide["completion"],
            )
        if errors:
            raise next((e for e in errors if not isinstance(e, BudgetPause)), errors[0])
        unresolved = sum(
            g.get("completion") == "review_unresolved" for g in guides.values()
        )
        storage.update(
            job_id,
            status="ready",
            operation=None,
            stage="Analysis complete",
            message=f"Guide review recovery finished; {unresolved} reviews remain unresolved.",
        )
    except BudgetPause as error:
        storage.update(
            job_id,
            status="paused",
            stage="Guide review recovery paused",
            message=str(error),
        )
        storage.event(job_id, "workflow_paused", reason=str(error))
    except (
        Exception
    ) as error:  # Persist a stopped worker without losing earlier recoveries.
        storage.update(
            job_id,
            status="failed",
            stage="Guide review recovery stopped",
            message=f"{type(error).__name__}: {error}",
        )
        storage.event(
            job_id, "workflow_error", error=type(error).__name__, message=str(error)
        )
