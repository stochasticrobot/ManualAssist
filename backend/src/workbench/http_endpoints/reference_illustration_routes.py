"""Serve original manual illustrations and accept explicit requests to prepare them.

Saved manuals may need their reference images prepared before the browser can show
them. Preparation is a separate requested operation; viewing an already saved
image only reads the image file and does not ask a model to generate a picture."""

import json
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from workbench.http_endpoints.validate_job_identifier import directory
from workbench.http_endpoints import background_worker_and_question_lock as runtime
from workbench.job_storage import job_files_and_audit_log as storage
from workbench.result_illustrations.prepare_source_illustrations import (
    prepare,
    public_manifest,
    content_hash,
)
from workbench.agentic_workflow.send_and_record_model_requests import Run

router = APIRouter()


def prepare_saved(job_id):
    """Run a bounded optional illustration pass without redoing text analysis.

    Args:
        job_id: Saved, idle job explicitly selected for preparation.
    Returns:
        None; records independent status. Model receipts and usage are accounted by
        Run. Errors leave saved guides unchanged and record incomplete preparation.
    """
    try:
        document = json.loads((storage.job_dir(job_id) / "document.json").read_text())
        result = prepare(job_id, document, Run(job_id, limit=12, replay=True))
        storage.update(job_id, illustration_status=result["status"])
    except Exception as exc:
        storage.update(job_id, illustration_status="incomplete")
        storage.event(job_id, "illustration_error", error=type(exc).__name__)


@router.post("/api/jobs/{job_id}/illustrations/prepare")
def start(job_id: str):
    """Queue optional, bounded image assessment for a saved idle analysis.

    Args:
        job_id: Existing completed/partial job identifier.
    Returns:
        Queued status or HTTP409 when analysis or illustration preparation is active.
        At most twelve candidate assessments; reopening Results never invokes this.
    """
    path = directory(job_id)
    with storage.LOCK:
        state = storage.state(job_id)
        if (
            state["status"] not in ["ready", "partial"]
            or state.get("illustration_status") == "preparing"
            or not (path / "document.json").exists()
        ):
            raise HTTPException(409, "Wait for the current work to finish")
        storage.update(job_id, illustration_status="preparing")
    runtime.WORKER.submit(prepare_saved, job_id)
    return {"status": "preparing", "maximum_candidate_calls": 12}


@router.get("/api/jobs/{job_id}/illustrations/{figure_id}.png")
def image(job_id: str, figure_id: str):
    """Serve only an accepted, unaltered original-source crop from this job.

    Args:
        job_id: Existing job identifier.
        figure_id: Exact accepted figure ID; never interpolated before whitelist lookup.
    Returns:
        PNG bytes or HTTP404 for absent, stale, excluded or modified assets. No calls.
    """
    path = directory(job_id)
    if not (path / "document.json").exists():
        raise HTTPException(404, "Image unavailable")
    document = json.loads((path / "document.json").read_text())
    allowed = public_manifest(job_id, document)
    if not any(r["id"] == figure_id for r in allowed["images"]):
        raise HTTPException(404, "Image unavailable")
    manifest = json.loads((path / "illustrations/manifest.json").read_text())
    if content_hash((path / "source.pdf").read_bytes()) != manifest.get(
        "source_pdf_hash"
    ):
        raise HTTPException(404, "Source changed")
    record = next(r for r in manifest["records"] if r["id"] == figure_id)
    file = path / "illustrations" / f"{figure_id}.png"
    if not file.is_file():
        raise HTTPException(404, "Image unavailable")
    data = file.read_bytes()
    if content_hash(data) != record["image_sha256"]:
        raise HTTPException(404, "Image unavailable")
    return Response(data, media_type="image/png")
