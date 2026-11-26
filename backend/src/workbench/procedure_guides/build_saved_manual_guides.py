"""Build procedure guides for a manual whose earlier analysis is already saved.

Readers should not have to repeat fact extraction just to add installation,
maintenance or troubleshooting guides. This explicitly requested operation saves
guides as they finish and retains previous results if work stops. The exports are
refreshed after successful completion."""

import json

from workbench.agentic_workflow.model_call_allowances import BudgetPause
from workbench.agentic_workflow.execution import Run
from workbench.job_storage import job_files_and_audit_log as storage
from workbench.model_access.model_requests_and_responses import ModelError
from workbench.procedure_guides.generate_manual_procedure_guides import (
    generate_manual_procedure_guides,
)
from workbench.result_exports.write_reports_and_data_exports import publish


def build_saved_manual_guides(job_id, resume=False, service=None):
    """Generate only procedure guides for a saved ready profile.

    Args:
        job_id: Saved job selected by an explicit guide-generation action.
        resume: Reuse exact saved requests and incomplete planner checkpoints.
        service: Optional isolated fixture provider; production reads configured models.
    Returns:
        None; updates ready, paused or failed status. The generator saves completed
        guides incrementally to profile.json; exports refresh only on completion.
        Facts and search artifacts survive failure, but the profile may contain
        newer partial guides than the existing exported reports. No automatic retries occur.
    """
    path = storage.job_dir(job_id)
    storage.update(
        job_id,
        status="analyzing",
        stage="Discover source-linked procedures",
        active_model_calls=[],
        operation="procedure_guides",
    )
    try:
        run = Run(job_id, service=service, replay=resume)
        profile = json.loads((path / "profile.json").read_text())
        document = json.loads((path / "document.json").read_text())
        profile = generate_manual_procedure_guides(job_id, profile, document, run)
        publish(job_id, profile)
        storage.update(
            job_id,
            status="ready",
            stage="Analysis complete",
            operation=None,
            message="Source-linked procedure guides saved.",
        )
        storage.event(
            job_id,
            "procedure_guides_completed",
            guides=len(profile["procedure_guides"]),
        )
    except BudgetPause as error:
        storage.update(
            job_id,
            status="paused",
            stage="Procedure planning paused",
            message=str(error),
        )
        storage.event(job_id, "workflow_paused", reason=str(error))
    except Exception as error:  # noqa: BLE001 - persist a safe stopped state at the worker boundary
        message = (
            str(error)
            if isinstance(error, ModelError)
            else f"{type(error).__name__}: procedure planning could not be completed."
        )
        storage.update(
            job_id, status="failed", stage="Procedure planning stopped", message=message
        )
        storage.event(
            job_id, "workflow_error", error=type(error).__name__, message=message
        )
