"""Check that an earlier review-checking method cannot dismiss a complaint using
missing, invented or uncertain evidence. Predetermined replies exercise the
acceptance rules, not the accuracy of a live reviewer."""

import pytest
from workbench.procedure_guides.procedure_reply_models import ProcedureReviewCorrection
from workbench.procedure_guides.verify_reported_behavior_defects import (
    BehaviorDefectVerification,
    validate_claim_decisions,
)


def decision(**changes):
    """Create an anchored refutation for an action appearing in a later sentence.

    Args:
        changes: Decision fields overridden to exercise invalid evidence or verdicts.
    Returns:
        One explicit fixture judgment, not evidence of live model accuracy.
    """
    return (
        dict(
            claim_index=0,
            source_id="s",
            source_quote="Add the device.",
            reader_path="guide.steps[one].instruction",
            draft_quote="Add the device.",
            explanation="The later sentence includes the action.",
            verdict="refuted",
        )
        | changes
    )


def check(decisions):
    """Validate fixture decisions against the same complete source and reader text.

    Args:
        decisions: Response rows, including deliberately incomplete or invalid rows.
    Returns:
        Remaining corrections from the production validator.
    """
    return validate_claim_decisions(
        BehaviorDefectVerification(decisions=decisions),
        [
            ProcedureReviewCorrection(
                issue="Missing add-device action", step_id="one", evidence_ids=["s"]
            )
        ],
        [{"id": "s", "text": "Reset it. Add the device."}],
        {"guide.steps[one].instruction": "Reset it. Add the device."},
    )


def test_anchored_refutation_removes_only_the_supplied_claim():
    """Allow an anchored refutation of a specific proposed defect.

    Args:
        None.
    Returns:
        None; the original allegation is removed by the production validator.
    """
    assert check([decision()]) == []


@pytest.mark.parametrize(
    "changes",
    [
        {"source_id": "unknown"},
        {"source_quote": "Invented source"},
        {"draft_quote": "Invented reader instruction"},
        {"draft_quote": ""},
        {"reader_path": "citation.quote"},
        {"verdict": "uncertain"},
    ],
)
def test_invalid_or_uncertain_refutations_stay_incomplete(changes):
    """Prevent absent evidence and uncertainty from silently approving a draft.

    Args:
        changes: One invalid field or uncertain verdict applied to the base decision.
    Returns:
        None; a visible incomplete-review correction must survive.
    """
    remaining = check([decision(**changes)])
    assert len(remaining) == 1
    assert "review remains incomplete" in remaining[0].issue


@pytest.mark.parametrize(
    "rows", [[], [decision(), decision()], [decision(claim_index=2)]]
)
def test_missing_duplicate_and_unknown_claim_indices_fail_closed(rows):
    """Require a complete one-to-one accounting of the original allegations.

    Args:
        rows: Invalid claim accounting to submit to the production validator.
    Returns:
        None; original defect remains incomplete, never silently refuted.
    """
    assert "review remains incomplete" in check(rows)[0].issue


def test_confirmed_defect_keeps_the_evidence_and_explanation():
    """Retain a confirmed omission even when no corresponding draft quote exists.

    Args:
        None.
    Returns:
        None; the specific confirmed defect remains available to the planner.
    """
    remaining = check(
        [decision(verdict="confirmed", draft_quote="", explanation="Action is absent.")]
    )
    assert remaining[0].issue == "Action is absent."
    assert remaining[0].evidence_ids == ["s"]
