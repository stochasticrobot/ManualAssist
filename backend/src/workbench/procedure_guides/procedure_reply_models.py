"""Define what an AI must return while discovering, investigating and writing a
guide.

The application needs to distinguish a request to read more text from a proposed
step, unresolved question or review correction. These definitions make required
information and allowed choices explicit. A reply with all the right fields still
needs its evidence and meaning checked before it can be accepted."""

from typing import Literal

from pydantic import Field

from workbench.data_models.analysis_and_question_models import (
    Citation,
    Strict,
    TroubleshootingCheck,
    TroubleshootingTree,
)


class ProcedureCandidate(Strict):
    """A procedure mentioned in supplied passages, not a claim of complete coverage."""

    kind: Literal["installation", "maintenance", "troubleshooting"]
    title: str = Field(min_length=1, max_length=160)
    citations: list[Citation] = Field(min_length=1)
    role: Literal["procedure", "requirement", "warning", "stop_condition"] = "procedure"


class ProcedureCandidates(Strict):
    """Procedures worth investigating; an empty list is appropriate when none occur."""

    procedures: list[ProcedureCandidate]


class CitedInstruction(Strict):
    """An instruction or warning supported by one or more exact source quotations."""

    text: str = Field(min_length=1)
    citations: list[Citation] = Field(min_length=1)


class ProcedureStep(Strict):
    """One ordered step, with explicit conditions, cautions and completion checks."""

    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    instruction: str = Field(min_length=1)
    applies_when: str
    after_step_ids: list[str]
    citations: list[Citation] = Field(min_length=1)
    warnings: list[CitedInstruction]
    checks: list[CitedInstruction]


class ProcedureDraft(Strict):
    """A proposed guide; absent details remain unanswered rather than invented."""

    outcome: Literal["guide", "partial", "stop", "insufficient_evidence"] = "guide"
    title: str
    applies_to: str
    prerequisites: list[CitedInstruction]
    steps: list[ProcedureStep] = Field(max_length=60)
    schedule: CitedInstruction | None
    independent_checks: list[TroubleshootingCheck] = Field(default_factory=list)
    troubleshooting: TroubleshootingTree | None
    unanswered_questions: list[str]


class ProcedureQuestion(Strict):
    """The planner's current answer or gap for one task-specific question."""

    question: str
    status: Literal["supported", "partial", "unresolved", "not_applicable"]
    answer: str
    evidence_ids: list[str]


class ProcedureReviewCorrection(Strict):
    """A source-backed defect to fix without restarting general exploration."""

    issue: str
    step_id: str
    evidence_ids: list[str] = Field(min_length=1)


class ProcedureInspectionDecision(Strict):
    """A source-inspection choice or a proposed finished guide, with a short reason."""

    action: Literal["read_source", "read_page", "search_parsed_document", "finish"]
    reason: str
    question: str = ""
    questions: list[ProcedureQuestion] = Field(default_factory=list)
    evidence_id: str = ""
    page: int = 1
    query: str = ""
    draft: ProcedureDraft | None = None


class ProcedureFinalization(Strict):
    """Assemble inspected evidence without permitting another source inspection."""

    reason: str
    questions: list[ProcedureQuestion] = Field(default_factory=list)
    draft: ProcedureDraft


class ProcedureEvidenceReview(Strict):
    """A second model check of meaning and ordering, not a human safety approval."""

    acceptable: bool
    issues: list[str] = Field(default_factory=list)
    corrections: list[ProcedureReviewCorrection] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)


class OrganizedProcedure(Strict):
    """One practical task with its original leads and supporting requirements."""

    kind: Literal["installation", "maintenance", "troubleshooting"]
    title: str
    lead_ids: list[str] = Field(min_length=1)
    supporting_lead_ids: list[str]
    applicability: str


class UnassignedProcedureLead(Strict):
    """A retained lead that does not justify an independent procedure."""

    lead_id: str
    reason: str


class OrganizedProcedurePlan(Strict):
    """A complete accounting of discovered leads without inventing source references."""

    procedures: list[OrganizedProcedure]
    unassigned: list[UnassignedProcedureLead]
