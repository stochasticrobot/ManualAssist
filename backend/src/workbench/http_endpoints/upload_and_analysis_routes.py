"""Receive uploaded manuals and requests to start or continue their analysis.

The browser needs a way to list saved manuals, read progress and request work.
These handlers validate those requests and arrange background processing. They do
not extract PDF text or decide what the AI should conclude."""

from workbench.manual_analysis.estimate_fact_extraction_work import analysis_preflight

from fastapi import APIRouter, File, HTTPException, UploadFile
import json
from workbench.job_storage import job_files_and_audit_log as storage
from workbench.agentic_workflow.process_uploaded_manual import process_uploaded_manual
from workbench.pdf_processing.validate_and_render_pdf import inspect_pdf
from workbench.agentic_workflow import run_manual_analysis as agent
from workbench.http_endpoints.validate_job_identifier import directory
from workbench.http_endpoints import background_worker_and_question_lock as runtime

router = APIRouter()


@router.get("/api/jobs")
def jobs():
    """List persisted jobs for the document sidebar.

    Args:
        None.
    Returns:
        Most-recent-first state snapshots without credentials.
    """
    return storage.list_jobs()


@router.post("/api/jobs")
async def upload(file: UploadFile = File(...)):
    """Admit a bounded PDF and queue real local layout extraction.

    Args:
        file: Multipart PDF upload; filename is display-only.
    Returns:
        Queued job state; rejects oversized/invalid PDFs with HTTP 400.
        Saves source bytes and starts local parsing followed automatically by one
        bounded model analysis when the import succeeds. Failed/partial imports do
        not automatically advance, and later Resume remains explicit.
    """
    data = await file.read(25 * 1024 * 1024 + 1)
    try:
        inspect_pdf(data)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    state = storage.create((file.filename or "manual.pdf")[:200], data)
    runtime.WORKER.submit(process_uploaded_manual, state["id"])
    return state


@router.get("/api/jobs/{job_id}")
def detail(job_id: str):
    """Load saved evidence and progress for one document workspace.

    Args:
        job_id: Existing job identifier.
    Returns:
        State, available artifacts, audit events and a read-only workflow/usage
        summary with explicitly labelled estimates. No generation occurs.
    """
    path = directory(job_id)
    result = {"state": storage.state(job_id)}
    for name in ("document", "profile", "chunks", "decisions"):
        if (path / f"{name}.json").exists():
            result[name] = json.loads((path / f"{name}.json").read_text())
    from workbench.result_illustrations.prepare_source_illustrations import public_manifest
    result["illustrations"] = public_manifest(job_id, result["document"]) if "document" in result else {"status":"not_prepared", "images":[]}
    result["audit"] = storage.events(job_id)
    from workbench.agentic_workflow.build_analysis_progress import summarize

    result["workflow"] = summarize(path, result)
    return result


@router.post("/api/jobs/{job_id}/analyze")
def start_analysis(job_id: str):
    """Queue explicitly requested bounded model analysis, preserving parsed evidence.

    Args:
        job_id: Parsed job; duplicate/running/completed submissions are rejected.
    Returns:
        Updated queued state; validates the per-request batch plan before queueing.
        Whole-document size is not capped; work pauses at the per-slice allowance.
    """
    directory(job_id)
    with storage.LOCK:
        state = storage.state(job_id)
        if state["status"] != "parsed":
            raise HTTPException(
                409, "Analysis requires a parsed, not previously analyzed job"
            )
        plan = analysis_preflight(
            json.loads((directory(job_id) / "document.json").read_text())
        )
        if plan["blocker"]:
            raise HTTPException(409, plan["blocker"])
        storage.update(job_id, status="analyzing", stage="Queued for agent analysis")
    runtime.WORKER.submit(agent.analyze, job_id)
    return storage.state(job_id)


@router.post("/api/jobs/{job_id}/resume")
def resume_analysis(job_id: str):
    """Explicitly resume stopped analysis, replaying compatible successful responses.

    Args:
        job_id: Failed/interrupted job with saved analysis requests or an extraction checkpoint.
    Returns:
        Queued state authorizing up to 1,000 new attempted calls and a bounded estimated
        input allowance. Successful compatible responses replay without spending.
        Rejects active jobs or absent parsed sources; never continues automatically.
    """
    path = directory(job_id)
    with storage.LOCK:
        state = storage.state(job_id)
        if (
            state["status"] not in ("failed", "interrupted", "paused")
            or not (path / "document.json").exists()
        ):
            raise HTTPException(409, "No saved analysis requests to resume")
        plan = analysis_preflight(json.loads((path / "document.json").read_text()))
        if plan["blocker"]:
            raise HTTPException(409, plan["blocker"])
        storage.update(job_id, status="analyzing", stage="Resuming unresolved guide reviews" if state.get("operation") == "procedure_review_repair" else "Resuming saved extraction")
    if state.get('operation') == 'procedure_review_repair':
        from workbench.procedure_guides.repair_unresolved_manual_guides import repair_unresolved_manual_guides
        runtime.WORKER.submit(repair_unresolved_manual_guides, job_id, True)
    elif state.get('operation') == 'procedure_guides':
        from workbench.procedure_guides.build_saved_manual_guides import build_saved_manual_guides
        runtime.WORKER.submit(build_saved_manual_guides, job_id, True)
    else:
        runtime.WORKER.submit(agent.analyze, job_id, True)
    return storage.state(job_id)
