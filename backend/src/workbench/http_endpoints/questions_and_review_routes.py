"""Receive a reader's manual question or saved note about an unresolved issue.

Questions are passed to the source-backed answering process. Review notes update
the stored issue status and the reader's explanation. These browser request
handlers check the request but do not themselves interpret the manual."""

from workbench.document_search.answer_from_retrieved_passages import answer

from fastapi import APIRouter, HTTPException
from workbench.job_storage import job_files_and_audit_log as storage
from workbench.data_models.analysis_and_question_models import Question, Review
from workbench.http_endpoints.validate_job_identifier import directory
from workbench.http_endpoints import background_worker_and_question_lock as runtime

router = APIRouter()


@router.post("/api/jobs/{job_id}/ask")
def ask(job_id: str, body: Question):
    """Answer a question through the production retrieval/model boundary.

    Args:
        job_id: Indexed job identifier.
        body: Validated bounded question.
    Returns:
        Source-cited answer or HTTP error; at most one model call per request.
        Serializes Q&A to avoid overlapping paid calls from double submissions.
    """
    directory(job_id)
    state = storage.state(job_id)
    if state["status"] not in ("ready", "partial") and not state.get("results_available"):
        raise HTTPException(409, "Wait for indexing to finish")
    if not runtime.ANSWER_LOCK.acquire(blocking=False):
        raise HTTPException(409, "Another answer is in progress")
    try:
        return answer(job_id, body.question)
    except Exception as exc:
        raise HTTPException(
            502, f"Answer could not be validated ({type(exc).__name__})"
        ) from None
    finally:
        runtime.ANSWER_LOCK.release()


@router.post("/api/jobs/{job_id}/review")
def review(job_id: str, body: Review):
    """Record a human review decision without rewriting manufacturer evidence.

    Args:
        job_id: Existing job identifier.
        body: Finding index, disposition and human note.
    Returns:
        Updated review queue; logs the escalation resolution separately.
    """
    directory(job_id)
    with storage.LOCK:
        entries = storage.state(job_id)["review"]
        if body.index >= len(entries):
            raise HTTPException(404, "Review item not found")
        entries[body.index].update(status=body.status, note=body.note)
        storage.update(job_id, review=entries)
        storage.event(job_id, "human_review", **body.model_dump())
    return entries
