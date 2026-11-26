"""Keep a useful saved draft when an AI repeatedly returns an unusable guide reply.

One malformed answer should not erase valid earlier work or cancel unrelated
guides. This file preserves any already checked draft and labels the unfinished
review. It does not turn malformed text into instructions or hide provider, budget
or unexpected application failures."""

import json

from workbench.job_storage import job_files_and_audit_log as storage
from workbench.procedure_guides.validate_procedure_steps import validate_saved_procedure


def retain_failed_procedure_result(job_id, candidate, error):
    """Save an explicit local failure, retaining an earlier validated draft if available.

    Args:
        job_id: Job whose other independent guide investigations may continue.
        candidate: Assigned procedure with stable ID, kind, title and optional scope.
        error: Exhausted invalid-response correction; not a provider or budget error.
    Returns:
        Needs-review draft or an unfinished empty guide with the failure recorded.
        Writes a failure artifact and a terminal result in the matching planner
        checkpoint, preventing Resume from spending on the same failed response.
        Original replies and saved draft evidence remain intact. Citation/structure failures in the saved draft propagate.
    """
    path = storage.job_dir(job_id)
    checkpoint = path / "procedure-plans-v3" / (candidate["id"] + ".json")
    state = json.loads(checkpoint.read_text()) if checkpoint.exists() else {}
    draft = state.get("last_draft")
    issue = "This guide could not be completed: the model reply remained invalid after one correction."
    result = {
        "id": candidate["id"],
        "kind": candidate["kind"],
        "scope": candidate.get("scope", "procedure"),
        "title": candidate["title"],
        "applies_to": "Not established",
        "prerequisites": [],
        "steps": [],
        "schedule": None,
        "troubleshooting": None,
        "unanswered_questions": [],
        **(draft or {}),
        "status": "needs_review" if draft else "unfinished",
        "generation_failed": True,
        "model_reviewed": bool(draft and state.get("last_draft_reviewed")),
        "inspected_source_ids": list(state.get("evidence", {})),
        "question_ledger": state.get("questions", []),
        "review_issues": [*state.get("problems", []), issue],
    }
    validate_saved_procedure(result, state.get("evidence", {}))
    storage.save(
        path / f"procedure-failure-{candidate['id']}.json",
        {"result": result, "error": str(error)},
    )
    if checkpoint.exists():
        state["terminal_format_error"] = str(error)
        state["result"] = result
        storage.save(checkpoint, state)
    storage.event(
        job_id,
        "procedure_failed",
        procedure_id=candidate["id"],
        message=issue,
        error=str(error),
        other_procedures_continue=True,
    )
    return result
