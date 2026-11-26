"""Retain an earlier check of whether a claimed guide defect is supported by the
text.

The check compares the complaint with the supplied manual and the actual reader
instructions, including later steps and prerequisites. It requires quoted support
before dismissing a complaint and leaves uncertainty unresolved. This older method
is retained for tests and experiments, not the current production review path."""

from typing import Literal

from pydantic import Field

from workbench.data_models.analysis_and_question_models import Strict
from workbench.procedure_guides.procedure_reply_models import ProcedureReviewCorrection

VERIFICATION_INSTRUCTIONS = """Check the specific alleged defects below, not the quality of the entire guide.
For each claim, inspect ALL evidence and ALL supplied reader instructions, including later sentences and relevant prerequisites. Evidence has equal authority throughout sources.
Decide whether the alleged change, omission or unsupported addition is actually present. Equivalent wording counts; an action need not be repeated in the same sentence as its condition. Do not infer actions that were never stated or guess missing button labels.
Copy an exact contiguous source quotation. If the draft contains the action or wording relevant to your decision, copy its exact contiguous words and their reader_path. Do not join separated fragments with ellipses.
Explain the specific behavioral difference or equivalence before returning confirmed, refuted or uncertain. Refuted requires actual reader text and source evidence demonstrating that the allegation is wrong. If the evidence cannot settle it, use uncertain. Do not approve a claim merely because the first checker reported it.
Headings that only name a section need not be reproduced. Concrete instructions or conditions within headings still matter.
"""


class BehaviorClaimDecision(Strict):
    """An evidence-backed decision about one specific proposed correction."""

    claim_index: int
    source_id: str
    source_quote: str = Field(min_length=1)
    reader_path: str
    draft_quote: str
    explanation: str = Field(min_length=1)
    verdict: Literal["confirmed", "refuted", "uncertain"]


class BehaviorDefectVerification(Strict):
    """Require a decision for each alleged defect, not a whole-guide approval flag."""

    decisions: list[BehaviorClaimDecision]


def validate_claim_decisions(reply, corrections, sources, reader_fields):
    """Apply only complete, quote-anchored confirmations or refutations of claims.

    Args:
        reply: Structured confirmation response for the listed corrections.
        corrections: Original proposed defects, in the order sent to the checker.
        sources: All evidence records, with no focus/context authority distinction.
        reader_fields: Mapping from exact reader paths to complete instruction text.
    Returns:
        Remaining corrections. Invalid, missing, duplicate or uncertain decisions
        remain visibly incomplete; they never silently approve a guide. Raw replies
        remain in the normal call receipts and are not repaired locally.
    """
    by_id = {s["id"]: s["text"] for s in sources}
    indices = [d.claim_index for d in reply.decisions]
    if sorted(indices) != list(range(len(corrections))):
        return [
            ProcedureReviewCorrection(
                issue="Defect confirmation did not account for every claim exactly once; review remains incomplete.",
                step_id=c.step_id,
                evidence_ids=c.evidence_ids,
            )
            for c in corrections
        ]
    remaining = []
    for decision in reply.decisions:
        original = corrections[decision.claim_index]
        valid = (
            decision.source_quote in by_id.get(decision.source_id, "")
            and (
                not decision.draft_quote
                or decision.draft_quote in reader_fields.get(decision.reader_path, "")
            )
            and (decision.verdict != "refuted" or bool(decision.draft_quote))
        )
        if not valid or decision.verdict == "uncertain":
            remaining.append(
                ProcedureReviewCorrection(
                    issue="Defect confirmation lacks conclusive matched evidence; review remains incomplete.",
                    step_id=original.step_id,
                    evidence_ids=original.evidence_ids,
                )
            )
        elif decision.verdict == "confirmed":
            remaining.append(
                ProcedureReviewCorrection(
                    issue=decision.explanation,
                    step_id=original.step_id,
                    evidence_ids=[decision.source_id],
                )
            )
    return remaining


def verify_reported_behavior_defects(corrections, packet, reader_fields, run):
    """Reject calls to the retired second-review cascade without spending tokens.

    Args:
        corrections: Non-integrity defects proposed by the initial comparison.
        packet: Original source pool and complete relevant reader instructions.
        reader_fields: Actual reader path/text pairs, never citation quotations.
        run: Production metered call owner with normal receipt persistence.
    Returns:
        Never returns; always raises RuntimeError, even for empty corrections.
        The current review uses review_actions_with_code_owned_evidence instead.
        No model request, result mutation or receipt write occurs here.
    """
    raise RuntimeError(
        "The confirmation cascade is retired; use focused code-owned evidence review."
    )
