"""Define the separate questions used to review a guide and the allowed replies.

Relevance, missing instructions and unsupported claims need different decisions.
Keeping their prompts and response checks together makes those distinctions visible;
this file does not send requests or approve guides.
"""

from typing import Literal
from pydantic import Field, model_validator
from workbench.data_models.analysis_and_question_models import Strict

VERSION = "verified-objections-review-v17"
MAX_COMPARISONS = 6
OUTPUT_CAP = 3000
RELEVANCE = (
    "Decide only whether each manual statement contains an instruction relevant to the assigned procedure. "
    "Include its explicitly named subtasks and applicable prerequisites and warnings. "
    "Use all manual passages to understand conditions; do not judge whether a reader guide covers the instruction. "
    "Return required for a relevant instruction, out_of_scope for a clearly unrelated task, "
    "not_instruction for a topic label or automatic machine behavior, and unclear for uncertain relevance. "
    "Explain the task relationship briefly before the result."
)
COVERAGE = (
    "Check only whether the reader guide preserves the instruction in statement_to_check. "
    "Its relevance has already been checked; do not reconsider task scope. "
    "Use all supplied manual passages to establish its action, condition and required order, "
    "then compare with the actual reader instructions. Separate steps and equivalent wording are fine. "
    "Return present for equivalent behavior, absent for an unstated required action, different for changed behavior or conditions, "
    "not_instruction for a topic or automatic machine behavior, and unclear when evidence cannot settle it. "
    "Do not invent implicit reader actions. Explain the concrete match or difference before choosing the result."
)
SUPPORT = (
    "Identify any concrete action or factual detail in the proposed reader text that the manual does not support. "
    "Use all supplied manual passages together. Reader context explains the proposal, but is not evidence. "
    "Compare meaning, not matching words: equivalent behavior and summaries are supported. "
    "Do not report omitted manual content; a separate coverage job checks omissions. "
    "A changed condition or order, invented action or object, or altered literal value is an unsupported detail. "
    "Harmless formatting may differ; do not repair corrupted values or infer unreadable symbols. "
    "Explain the comparison, identify the unsupported detail if any, then decide. "
    "Return established when supported, not_established for a concrete unsupported detail, unclear when evidence cannot settle it, "
    "or not_instruction for a navigation label."
)
EVIDENCE_GAP = (
    "Check only whether the proposed text accurately describes an unanswered question within the examined evidence. "
    "It must not prescribe an unsupported action or claim that the whole manual lacks information. "
    "Reader context is a proposal, not evidence. Explain your comparison with the original passages. "
    "Return established for a bounded unanswered question, not_established with the unsupported detail for an added claim or action, "
    "or unclear if the passages cannot settle it."
)
ACCOUNTING = " Return exactly one judgment per supplied comparison number, with a brief explanation followed by its result."


class RelevanceJudgment(Strict):
    """A task-applicability decision with no reader-guide approval choices."""

    comparison: int
    explanation: str = Field(min_length=1)
    result: Literal["required", "out_of_scope", "not_instruction", "unclear"]


class CoverageJudgment(Strict):
    """A required-behavior comparison that cannot discard task scope."""

    comparison: int
    explanation: str = Field(min_length=1)
    result: Literal["present", "absent", "different", "not_instruction", "unclear"]


class SupportJudgment(Strict):
    """A source-support decision naming any added or changed unsupported detail."""

    comparison: int
    explanation: str = Field(min_length=1)
    unsupported_detail: str = Field(
        description="The concrete unsupported action or factual detail; empty unless result is not_established."
    )
    result: Literal["established", "not_established", "not_instruction", "unclear"]

    @model_validator(mode="after")
    def require_concrete_objection(self):
        """Reject contradictory response fields without rewriting the verdict.

        Args:
            self: Parsed support decision and proposed unsupported detail.
        Returns:
            Unchanged reply when a negative verdict has a concrete detail and other
            verdicts do not; raises ValueError for the ordinary bounded correction.
            This validates structure, not whether the alleged detail is truly wrong.
        """
        if bool(self.unsupported_detail.strip()) != (self.result == "not_established"):
            raise ValueError(
                "Provide an unsupported detail only for not_established; leave it empty for other results."
            )
        return self


ANSWER_TYPES = {
    "relevance": RelevanceJudgment,
    "coverage": CoverageJudgment,
    "support": SupportJudgment,
    "evidence_gap": SupportJudgment,
}
INSTRUCTIONS = {
    "relevance": RELEVANCE,
    "coverage": COVERAGE,
    "support": SUPPORT,
    "evidence_gap": EVIDENCE_GAP,
}


def job_schema(stage, comparisons):
    """Give each review job its own verdict choices and complete item accounting.

    Args:
        stage: Relevance, coverage, support or evidence-gap job name.
        comparisons: Original numbered comparisons included in this request.
    Returns:
        Strict response class that rejects missing, repeated or invented numbers.
        Its advertised verdicts match those accepted locally for every item; no
        union of scope and coverage choices is exposed to the model.
    """
    answer_type = ANSWER_TYPES[stage]
    expected = sorted(c["comparison"] for c in comparisons)

    class JobReply(Strict):
        """All requested judgments for one narrow review responsibility."""

        judgments: list[answer_type]

        @model_validator(mode="after")
        def check_inventory(self):
            """Prevent partial replies from silently removing review obligations.

            Args:
                self: Parsed reply for the current job's numbered comparisons.
            Returns:
                Unchanged complete reply; raises ValueError for ordinary correction
                when a number is omitted, duplicated or invented.
            """
            if sorted(j.comparison for j in self.judgments) != expected:
                raise ValueError(
                    f"Return each supplied comparison exactly once: {expected}"
                )
            return self

    return JobReply
