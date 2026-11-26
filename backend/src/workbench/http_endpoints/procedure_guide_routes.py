"""Let a reader build missing guides or repair unresolved reviews for a saved manual.

A button press starts the requested work without repeating PDF extraction. The
server reserves the manual before queuing it so repeated clicks cannot start
duplicate work. Simply opening Results does not trigger model requests."""

from fastapi import APIRouter, HTTPException

from workbench.http_endpoints import background_worker_and_question_lock as runtime
from workbench.http_endpoints.validate_job_identifier import directory
from workbench.job_storage import job_files_and_audit_log as storage
from workbench.procedure_guides.build_saved_manual_guides import (
    build_saved_manual_guides,
)

router = APIRouter()


@router.post("/api/jobs/{job_id}/procedure-guides")
def start_procedure_guides(job_id: str):
    """Authorize a bounded guide build without repeating analysis or vector indexing.

    Args:
        job_id: Existing completed manual whose profile has no completed guide build.
    Returns:
        Reserved job state. Rejects active jobs or duplicate completed builds with
        HTTP 409; queues only the guide workflow after releasing the storage lock.
    """
    path = directory(job_id)
    with storage.LOCK:
        if (
            storage.state(job_id)["status"] != "ready"
            or not (path / "profile.json").exists()
        ):
            raise HTTPException(409, "Guide generation requires a completed analysis.")
        if (path / "procedure-guides-complete.json").exists():
            raise HTTPException(409, "Procedure guides have already been generated.")
        storage.update(
            job_id,
            status="analyzing",
            operation="procedure_guides",
            stage="Discover source-linked procedures",
        )
    runtime.WORKER.submit(build_saved_manual_guides, job_id)
    return storage.state(job_id)


@router.post("/api/jobs/{job_id}/repair-guide-reviews")
def repair_guide_reviews(job_id: str):
    """Queue recovery of saved unresolved guides without repeating manual extraction.

    Args:
        job_id: Ready manual with at least one saved unresolved guide review.
    Returns:
        Reserved job state; HTTP 409 for active jobs or no blocked guides. The
        worker preserves old evidence and receipts, and publishes only reviewed
        status transitions. Work remains bounded and can pause for explicit Resume.
    """
    import json
    from workbench.procedure_guides.repair_unresolved_manual_guides import (
        repair_unresolved_manual_guides,
    )

    path = directory(job_id)
    with storage.LOCK:
        if storage.state(job_id)["status"] != "ready":
            raise HTTPException(
                409, "Review recovery requires an idle analysed manual."
            )
        profile = json.loads((path / "profile.json").read_text())
        if not any(
            g.get("completion") == "review_unresolved"
            for g in profile.get("procedure_guides", [])
        ):
            raise HTTPException(409, "No unresolved guide reviews to repair.")
        storage.update(
            job_id,
            status="analyzing",
            operation="procedure_review_repair",
            stage="Repair unresolved guide reviews",
        )
    runtime.WORKER.submit(repair_unresolved_manual_guides, job_id)
    return storage.state(job_id)
