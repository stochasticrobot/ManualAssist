"""Check investigation transitions without a provider, saved manual or model call.

These tests exercise the same functions called by the production planner, including
one-way finalization, checkpoint round trips and corrections that must block approval.
They do not establish the semantic quality of model-generated reviews.
"""

import json
import pytest
from workbench.procedure_guides.planner_state import (
    initial_state,
    advance_phase,
    record_review,
)
from workbench.procedure_guides.procedure_reply_models import (
    ProcedureEvidenceReview,
    ProcedureReviewCorrection,
)


@pytest.mark.parametrize(
    "decisions,idle,draft,expected",
    [
        (0, 0, None, False),
        (3, 0, None, True),
        (0, 2, None, True),
        (0, 0, {"unanswered_questions": []}, True),
    ],
)
def test_finalization_is_one_way_across_resume(decisions, idle, draft, expected):
    """Exercise each stop condition and preserve it after saving and reopening progress.

    Args:
        decisions: Number of decisions already consumed.
        idle: Consecutive inspections that added no evidence.
        draft: Existing draft, or None before any draft is available.
        expected: Whether these inputs require finalization.
    Returns:
        None; asserts the exact boundary and that a saved finalization cannot reopen.
    """
    state = initial_state("same-input", {}, [])
    state.update(decisions=decisions, no_new_evidence=idle, last_draft=draft)
    assert advance_phase(state, 3) is expected
    resumed = json.loads(json.dumps(state))
    resumed.update(decisions=0, no_new_evidence=0, last_draft=None)
    assert advance_phase(resumed, 3) is expected


def test_invalid_review_references_remain_blocking():
    """Retain an out-of-context correction instead of silently approving the guide.

    Args:
        None; uses a controlled reviewer response and one original passage.
    Returns:
        None; asserts count, citation mapping, rejection identity and blocking issue.
    """
    source = {"id": "s1", "text": "Unplug before cleaning.", "page": 1}
    state = initial_state("same-input", {"s1": source}, [])
    state["pending_review_draft"] = {}
    guide = {"unanswered_questions": []}
    review = ProcedureEvidenceReview(
        acceptable=False,
        corrections=[
            ProcedureReviewCorrection(
                issue="Missing warning", step_id="guide", evidence_ids=["unknown"]
            )
        ],
    )
    record_review(state, guide, review, [{"coverage": []}], [source])
    assert state["reviews"] == 1
    assert state["last_draft_reviewed"] is True
    assert "pending_review_draft" not in state
    assert state["review_reference_map"][0]["evidence_id"] == "s1"
    assert state["rejected_draft_hash"]
    assert (
        "Reviewer referenced evidence outside its supplied passages."
        in state["problems"]
    )


def test_empty_audit_does_not_claim_model_review():
    """Keep a source-gap-only result distinct from a completed model comparison.

    Args:
        None; uses an acceptable result without model comparison records.
    Returns:
        None; asserts review counting, explicit gaps and absence of model-review claim.
    """
    state = initial_state("same-input", {}, [])
    guide = {"unanswered_questions": ["Existing gap"]}
    review = ProcedureEvidenceReview(acceptable=True, gaps=["New gap"])
    record_review(state, guide, review, [], [])
    assert state["last_draft_reviewed"] is False
    assert state["reviews"] == 1
    assert state["problems"] == []
    assert guide["unanswered_questions"] == ["Existing gap", "New gap"]
    assert state["rejected_draft_hash"] is None


def test_exhausted_reviews_do_not_become_approval():
    """Keep rejection visible when the final permitted review has returned.

    Args:
        None; constructs four completed negative reviews and one preserved draft.
    Returns:
        None; asserts the final result remains unresolved even when a draft exists.
    """
    from workbench.procedure_guides.planner_state import completed_result

    state = initial_state("same-input", {}, [])
    state.update(reviews=4, problems=["Missing a supported warning"])
    task = {"id": "task", "kind": "maintenance", "title": "Clean", "evidence_ids": []}
    guide = {"outcome": "guide", "unanswered_questions": []}
    result = completed_result(
        state, task, guide, ProcedureEvidenceReview(acceptable=False), [{}], []
    )
    assert result["completion"] == "review_unresolved"
    assert result["status"] == "needs_review"
    assert result["review_issues"] == state["problems"]


def test_stopped_draft_and_absent_draft_stay_distinct():
    """Preserve a useful draft without presenting it as a finished investigation.

    Args:
        None; compares a fresh investigation with a validated but unreviewed draft.
    Returns:
        None; asserts no-draft status, preserved draft text and explicit unfinished status.
    """
    from workbench.procedure_guides.planner_state import unfinished_result

    state = initial_state("same-input", {}, [])
    task = {"id": "task", "kind": "maintenance", "title": "Clean", "evidence_ids": []}
    assert unfinished_result(state, task)["status"] == "unfinished"
    state["last_draft"] = {"title": "Retained draft", "unanswered_questions": []}
    result = unfinished_result(state, task)
    assert result["title"] == "Retained draft"
    assert result["completion"] == "stopped_before_completion"
    assert result["model_reviewed"] is False
