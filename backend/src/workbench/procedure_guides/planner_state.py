"""Describe saved guide investigations and the changes allowed after each decision.

An investigation can move from finding evidence to drafting, but cannot reopen
search after that transition. Review results retain corrections and source links
for the next draft. These operations make no model calls and write no files, so
pause, revision and completion rules can be checked independently.
"""

from typing import Literal, NotRequired, TypedDict
from workbench.data_models.application_types import (
    Evidence,
    ProcedureGuide,
    ProcedureTask,
)
from workbench.procedure_guides.procedure_reply_models import ProcedureEvidenceReview
from workbench.agentic_workflow.run_source_group_tasks import digest

PlannerPhase = Literal["exploration", "finalization"]


class PlannerState(TypedDict):
    """Persist investigation progress using the existing JSON field names.

    Optional keys appear only after the relevant review or recovery event. Keeping
    this a typed dictionary preserves older checkpoints and additional audit fields.
    """

    input_hash: str
    evidence: dict[str, Evidence]
    omitted: list[str]
    observations: list[dict]
    decisions: int
    inspections: int
    reviews: int
    problems: list[str]
    result: ProcedureGuide | None
    questions: list[dict]
    request_keys: list[str]
    no_new_evidence: int
    preferred_ids: list[str]
    last_draft: ProcedureGuide | None
    last_draft_reviewed: bool
    phase: PlannerPhase
    pending_review_draft: NotRequired[ProcedureGuide]
    review_required_source_ids: NotRequired[list[str]]
    review_reference_map: NotRequired[list[dict]]
    review_corrections: NotRequired[list[dict]]
    behavior_reviews: NotRequired[list[list[dict]]]
    rejected_draft_hash: NotRequired[str | None]
    terminal_format_error: NotRequired[str]


def initial_state(
    fingerprint: str, evidence: dict[str, Evidence], omitted: list[str]
) -> PlannerState:
    """Start an investigation without discarding the original source references.

    Args:
        fingerprint: Identity used to reject incompatible saved work.
        evidence: Collected original passages; retained as the investigation's mapping.
        omitted: Source IDs outside the initial reading allowance.
    Returns:
        New unsaved progress with no draft, reviews or decisions and exploration open.
    """
    return {
        "input_hash": fingerprint,
        "evidence": evidence,
        "omitted": omitted,
        "observations": [],
        "decisions": 0,
        "inspections": 0,
        "reviews": 0,
        "problems": [],
        "result": None,
        "questions": [],
        "request_keys": [],
        "no_new_evidence": 0,
        "preferred_ids": list(evidence),
        "last_draft": None,
        "last_draft_reviewed": False,
        "phase": "exploration",
    }


def advance_phase(state: PlannerState, allowance: int) -> bool:
    """Close investigation when drafting starts or exploration stops making progress.

    Args:
        state: Mutable saved progress, including consecutive unproductive inspections.
        allowance: Maximum exploration decisions before drafting is required.
    Returns:
        True when only drafting is allowed. Mutates phase in one direction only;
        callers must save the change before dispatch so Resume cannot reopen search.
    """
    if (
        state["no_new_evidence"] >= 2
        or state["decisions"] >= allowance
        or state["last_draft"] is not None
    ):
        state["phase"] = "finalization"
    return state["phase"] == "finalization"


def record_review(
    state: PlannerState,
    guide: ProcedureGuide,
    review: ProcedureEvidenceReview,
    comparison_audit: list[dict],
    review_sources: list[Evidence],
) -> None:
    """Apply a completed review while retaining corrections for a later revision.

    Args:
        state: Mutable investigation receiving the review count and next-draft feedback.
        guide: Mutable validated draft; unanswered source questions are appended to it.
        review: Validated acceptance decision, corrections, issues and evidence gaps.
        comparison_audit: Completed comparison records; empty means no model review.
        review_sources: Original passages used for that review and its citation numbers.
    Returns:
        None. Updates state and guide without saving or dispatching work. Unknown
        correction sources and unsupported rejection prevent a clean completion.
    """
    state["review_reference_map"] = [
        {
            "review_passage": number,
            "evidence_id": source["id"],
            "quote": source["text"],
        }
        for number, source in enumerate(review_sources, 1)
    ]
    state["review_corrections"] = [c.model_dump() for c in review.corrections]
    state.pop("pending_review_draft", None)
    state["reviews"] += 1
    state["last_draft_reviewed"] = bool(comparison_audit)
    invalid_corrections = [
        c
        for c in review.corrections
        if set(c.evidence_ids) - {i["id"] for i in review_sources}
    ]
    state["preferred_ids"] = list(
        dict.fromkeys(
            [
                sid
                for correction in review.corrections
                for sid in correction.evidence_ids
                if sid in state["evidence"]
            ]
            + state["preferred_ids"]
        )
    )
    state["problems"] = review.issues + [
        f"{c.step_id}: {c.issue}" for c in review.corrections
    ]
    if invalid_corrections:
        state["problems"].append(
            "Reviewer referenced evidence outside its supplied passages."
        )
    if not review.acceptable and not state["problems"]:
        state["problems"] = [
            "Reviewer rejected the draft without a supported correction."
        ]
    guide["unanswered_questions"] = list(
        dict.fromkeys(guide["unanswered_questions"] + review.gaps)
    )
    state["last_draft"] = guide
    state["rejected_draft_hash"] = digest(guide) if state["problems"] else None


def completed_result(
    state: PlannerState,
    candidate: ProcedureTask,
    guide: ProcedureGuide,
    review: ProcedureEvidenceReview,
    comparison_audit: list[dict],
    omitted: list[str],
) -> ProcedureGuide:
    """Build the saved result after acceptance or exhaustion of review attempts.

    Args:
        state: Investigation progress containing review problems and collected evidence.
        candidate: Original task identity, category and optional symptom coverage.
        guide: Mutable validated draft; missing context is appended as explicit gaps.
        review: Last completed review, including its acceptance and suggestions.
        comparison_audit: Comparison records establishing whether model review occurred.
        omitted: Source IDs that did not fit the planning context allowance.
    Returns:
        Result with completion, review status and source links. Exhausting attempts
        does not turn rejection into approval. Does not save files or change counters.
    """
    gaps = list(guide["unanswered_questions"])
    if candidate.get("related_symptoms_total", 0) > len(
        candidate.get("related_symptoms", [])
    ):
        gaps.append(
            "The top-level planning preview did not include every discovered symptom."
        )
    if omitted:
        gaps.append(
            "Some selected source passages exceeded the planning context allowance; inspect the linked manual before relying on completeness."
        )
    guide["unanswered_questions"] = gaps
    return dict(
        id=candidate["id"],
        kind=candidate["kind"],
        scope=candidate.get("scope", "procedure"),
        **guide,
        review_issues=state["problems"],
        status="source_checked"
        if not gaps and not state["problems"] and guide["outcome"] in {"guide", "stop"}
        else "needs_review",
        inspected_source_ids=list(state["evidence"]),
        completion=("finished_with_gaps" if gaps else "finished")
        if review.acceptable and not state["problems"]
        else "review_unresolved",
        model_reviewed=bool(comparison_audit),
        review_suggestions=review.suggestions,
        question_ledger=state["questions"],
    )


def unfinished_result(state: PlannerState, candidate: ProcedureTask) -> ProcedureGuide:
    """Retain a usable draft or an explicit no-guide result when investigation stops.

    Args:
        state: Investigation progress after a stop or exhausted decision allowance.
        candidate: Original task identity, kind, title and optional scope.
    Returns:
        Unapproved result preserving inspected sources, questions and blocking issues.
        An absent draft is marked unfinished; no model call or file write occurs.
    """
    if state["last_draft"] is not None:
        draft = state["last_draft"]
        result = {
            **draft,
            "id": candidate["id"],
            "kind": candidate["kind"],
            "scope": candidate.get("scope", "procedure"),
            "status": "needs_review",
            "completion": "review_unresolved"
            if state["last_draft_reviewed"]
            else "stopped_before_completion",
            "review_issues": state["problems"],
            "model_reviewed": state["last_draft_reviewed"],
            "question_ledger": state["questions"],
            "inspected_source_ids": list(state["evidence"]),
            "unanswered_questions": list(
                dict.fromkeys(
                    draft["unanswered_questions"]
                    + ["Investigation stopped before an accepted final review."]
                )
            ),
        }
        return result
    result = {
        "id": candidate["id"],
        "kind": candidate["kind"],
        "scope": candidate.get("scope", "procedure"),
        "title": candidate["title"],
        "status": "unfinished",
        "completion": "stopped_before_completion",
        "steps": [],
        "troubleshooting": None,
        "schedule": None,
        "prerequisites": [],
        "applies_to": "Not established",
        "unanswered_questions": state["problems"]
        or ["Planning allowance reached before a supported guide was assembled."],
        "review_issues": [],
        "inspected_source_ids": list(state["evidence"]),
        "model_reviewed": False,
    }
    return result
