"""Define the information required in AI answers and requests sent by the browser.

Facts, questions, citations and troubleshooting branches need predictable fields
before the application can store or display them. These definitions reject missing
or unexpected data. Passing those checks does not prove that an answer follows the
manual or that a suggested action is safe."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Strict(BaseModel):
    """Reject unexpected fields rather than silently dropping model output."""

    model_config = ConfigDict(extra="forbid", strict=True)


class Decision(Strict):
    """One inspectable agent action, not a private reasoning trace."""

    document_type: str
    purpose: str
    action: Literal[
        "read_page", "search_manual", "inspect_table", "inspect_image", "finish"
    ]
    reason: str
    page: int = 1
    query: str = ""
    evidence_id: str = ""


class Fact(Strict):
    """A proposed fact with exact source evidence and explicit model applicability."""

    category: str = Field(
        min_length=1,
        pattern=r"\S",
        description=(
            "A descriptive category chosen to fit the source. Examples include product, "
            "model, specification, power, environment, safety, quick_start, installation, "
            "operation, troubleshooting, maintenance, validation, inspection, disassembly, "
            "reassembly, quality_assurance, compliance, integrity_verification, part and "
            "error_code. These are examples, not an allowed-values list. Preserve any "
            "other meaningful category; do not force a procedure into an unrelated label."
        ),
    )
    name: str
    value: str
    applies_to: str
    evidence_id: str
    quote: str


class Finding(Strict):
    """Unresolved uncertainty; proposals are not manufacturer-confirmed defects."""

    issue: str
    evidence_ids: list[str]
    severity: Literal["info", "review", "critical"]


class AnswerClaim(Strict):
    """One answer statement linked to a verbatim retrieved passage."""

    statement: str
    evidence_id: str
    quote: str


class Answer(Strict):
    """Cited answer or explicit insufficiency, with no unsupported free narrative."""

    claims: list[AnswerClaim]
    insufficient: bool


class Question(Strict):
    """Bounded Q&A request from the UI."""

    question: str = Field(min_length=2, max_length=1500)


class Review(Strict):
    """Human review annotation; does not rewrite the source manual."""

    index: int = Field(ge=0)
    status: Literal["open", "resolved", "deferred"]
    note: str = Field(max_length=1500)


class Citation(Strict):
    """A verbatim supporting passage; a matched anchor is not semantic approval."""

    evidence_id: str
    quote: str


class FAQEntry(Strict):
    """One manual-specific question and answer with applicability and sources."""

    question: str
    answer: str
    applies_to: str
    citations: list[Citation] = Field(min_length=1)


class Branch(Strict):
    """A source-supported condition leading to another diagnostic node."""

    condition: str
    next_node: str
    citations: list[Citation] = Field(min_length=1)


class DiagnosticNode(Strict):
    """A check, remedy, service stop or explicit gap in the manual's instructions."""

    id: str
    kind: Literal["check", "action", "stop", "unresolved"]
    text: str
    citations: list[Citation]
    branches: list[Branch]

    @model_validator(mode="after")
    def require_instruction_sources(self):
        """Distinguish an evidence gap from a source-backed diagnostic instruction.

        Args:
            self: Parsed node with its kind, citations and outgoing branches.
        Returns:
            The unchanged node. Raises ValueError when an instruction lacks sources
            or an unresolved endpoint tries to prescribe an outgoing diagnostic path.
        """
        if self.kind != "unresolved" and not self.citations:
            raise ValueError(
                "Checks, actions and stop instructions require source citations"
            )
        if self.kind == "unresolved" and self.branches:
            raise ValueError("An unresolved evidence gap must terminate the path")
        return self


class TroubleshootingTree(Strict):
    """One symptom's diagnostic path, preserving stated warnings and scope."""

    symptom: str
    applies_to: str
    prerequisites: list[FAQEntry]
    root: str
    nodes: list[DiagnosticNode] = Field(min_length=1)


class FactExtraction(Strict):
    """Task A: extract facts only, with original units, applicability and quotations."""

    facts: list[Fact]


class UncertaintyCandidates(Strict):
    """Task B: propose specific ambiguities to check against the rest of the manual."""

    findings: list[Finding]


class FAQGeneration(Strict):
    """Task C1: answer useful manual-specific questions with cited evidence."""

    faq: list[FAQEntry]


class TroubleshootingCheck(Strict):
    """One documented check or remedy, without implied links to other checks."""

    symptom: str
    applies_to: str
    instruction: str
    citations: list[Citation] = Field(min_length=1)


class TroubleshootingChecksGeneration(Strict):
    """Extract independent instructions before an investigator considers connections."""

    troubleshooting_checks: list[TroubleshootingCheck]


class TroubleshootingGeneration(Strict):
    """Task C2: produce only source-supported troubleshooting paths."""

    troubleshooting: list[TroubleshootingTree]


class TargetedFindingAssessment(Strict):
    """A review decision with separate quotations and explicit evidence meaning."""

    index: int
    disposition: Literal[
        "resolved", "false_positive", "supported_issue", "needs_more_evidence"
    ]
    evidence_effect: Literal[
        "answers_question", "refutes_proposal", "shows_conflict", "inconclusive"
    ]
    reason: str
    citations: list[Citation]
    search_queries: list[str] = Field(max_length=3)


class TargetedFindingsReview(Strict):
    """One assessment per assigned uncertainty; source and decision checks are local."""

    assessments: list[TargetedFindingAssessment]


class InspectionDecision(Decision):
    """Inspection choice with explicit unanswered questions for an honest stop status."""

    remaining_questions: list[str] = Field(
        description="Specific inspection questions still unanswered; empty only when none remain. A finish decision must have an empty list."
    )
