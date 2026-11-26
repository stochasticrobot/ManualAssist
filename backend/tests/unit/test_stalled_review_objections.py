"""Check that a second opinion cannot clear a guide-review complaint using
uncertainty or irrelevant reader text. Controlled decisions test the application’s
dismissal rules while preserving the original complaint."""

from types import SimpleNamespace
import pytest
from workbench.procedure_guides.procedure_reply_models import ProcedureReviewCorrection
from workbench.procedure_guides.check_stalled_review_objections import (
    check_stalled_review_objections,
)


@pytest.mark.parametrize(
    "verdict,positions,cleared",
    [
        ("no_change", [1], True),
        ("no_change", [99], False),
        ("no_change", [0], False),
        ("no_change", [], False),
        ("needs_change", [1], False),
        ("uncertain", [1], False),
    ],
)
def test_only_anchored_refutations_clear_reported_objections(
    verdict, positions, cleared
):
    """Retain the original complaint unless a complete, anchored refutation is returned.

    Args:
        verdict: Scripted semantic judgment; this test does not establish its quality.
        positions: Valid or invented code-owned reader selections.
        cleared: Whether code may apply the explicit refutation.
    Returns:
        None; checks code gates, original audit preservation and no input mutation.
    """
    source = {"id": "s", "text": "Unplug before cleaning.", "page": 1}
    guide = {
        "title": "Clean",
        "prerequisites": [
            {
                "text": source["text"],
                "citations": [{"evidence_id": "s", "quote": source["text"]}],
            }
        ],
        "steps": [],
    }
    correction = ProcedureReviewCorrection(
        issue="Unplugging is absent.", step_id="guide", evidence_ids=["s"]
    )

    def call(role, prompt, schema, **kwargs):
        """Supply one controlled decision after inspecting production task preparation.

        Args:
            role: Model role, unused by this offline fixture.
            prompt: Actual source-bound task, with quotations separate from the guide.
            schema: Dynamic complete-accounting reply schema.
            **kwargs: Bounded dispatch settings, unused without a provider.
        Returns:
            Scripted parsed decision with an original source reference.
        """
        assert "reported_defects" in prompt and "reader_guide" in prompt
        return schema.model_validate(
            {
                "decisions": [
                    {
                        "objection": 0,
                        "explanation": "Fixture only.",
                        "verdict": verdict,
                        "reader_positions": positions,
                        "required_change": "Fix the defect"
                        if verdict == "needs_change"
                        else "",
                        "citations": [{"evidence_id": "s", "quote": source["text"]}],
                    }
                ]
            }
        )

    remaining, audit = check_stalled_review_objections(
        guide, {"title": "Clean"}, [source], [correction], SimpleNamespace(call=call)
    )
    assert bool(remaining) != cleared
    assert audit[0]["original"] == correction.model_dump()
    assert audit[0]["dismissed"] == cleared
    assert guide["prerequisites"][0]["text"] == source["text"]
