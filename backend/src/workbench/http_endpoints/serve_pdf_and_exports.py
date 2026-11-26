"""Let readers open the original PDF and download the results produced from it.

The server allows only known result files, not arbitrary files or credentials. It
can render an original PDF page for viewing and rebuild exports from saved
results. Opening a page does not ask an AI to interpret it."""

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, Response
import json
from workbench.job_storage import job_files_and_audit_log as storage
from workbench.pdf_processing.validate_and_render_pdf import page_image
from workbench.http_endpoints.validate_job_identifier import directory

router = APIRouter()


@router.get("/api/jobs/{job_id}/source")
def source(job_id: str):
    """Serve the immutable uploaded PDF for citation navigation.

    Args:
        job_id: Existing job identifier.
    Returns:
        Original PDF, served inline with the correct media type.
    """
    return FileResponse(directory(job_id) / "source.pdf", media_type="application/pdf")


@router.get("/api/jobs/{job_id}/pages/{page}")
def page(job_id: str, page: int):
    """Render a physical PDF page on demand for the evidence viewer.

    Args:
        job_id: Existing job identifier.
        page: One-based PDF page number.
    Returns:
        PNG page image or HTTP 400 for out-of-range pages.
    """
    try:
        return Response(
            page_image(directory(job_id) / "source.pdf", page),
            media_type="image/png",
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None


@router.get("/api/jobs/{job_id}/assets/{name}")
def asset(job_id: str, name: str):
    """Download only explicitly published artifacts, never arbitrary private files.

    Args:
        job_id: Existing job identifier.
        name: Whitelisted report, extraction, chunk, audit or CSV filename.
    Returns:
        File response; unknown or absent artifacts return HTTP 404.
    """
    allowed = {
        "report.html",
        "quick-start.html",
        "profile.json",
        "tables.json",
        "chunks.json",
        "document.json",
        "docling.json",
        "extracted.md",
        "audit.jsonl",
        "parts.csv",
        "maintenance.csv",
        "rejected.json",
        "decisions.json",
        "troubleshooting.json",
        "troubleshooting_checks.json",
        "faq.json",
        "procedure_guides.json",
        "guidance-rejected.json",
    }
    path = directory(job_id) / name
    if name not in allowed or not path.is_file():
        raise HTTPException(404, "Artifact not available")
    return FileResponse(path, filename=name)


@router.post("/api/jobs/{job_id}/refresh-exports")
def refresh_exports(job_id: str):
    """Regenerate deterministic exports from saved facts without model calls.

    Args:
        job_id: Completed job with a saved extraction profile.
    Returns:
        Export receipt; rewrites only derived HTML/CSV/JSON projections and audits it.
        Rejects active jobs so exports cannot race an ongoing extraction worker.
    """
    path = directory(job_id)
    if (
        storage.state(job_id)["status"] not in ("ready", "partial")
        or not (path / "profile.json").exists()
    ):
        raise HTTPException(409, "A completed extraction is required")
    from workbench.result_exports.write_reports_and_data_exports import publish

    profile = json.loads((path / "profile.json").read_text())
    publish(job_id, profile)
    storage.event(job_id, "tool_result", tool="refresh_exports", model_calls=0)
    return {"refreshed": True, "model_calls": 0}
