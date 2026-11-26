"""Name the information passed between document reading and guide investigation.

These types describe existing Python dictionaries without changing saved JSON or
adding model instructions. They help readers and static tools distinguish original
evidence, discovered tasks and generated guides; model replies still receive their
separate runtime validation before being used.
"""

from typing import NotRequired, TypedDict


class Evidence(TypedDict):
    """An original manual passage with a stable identifier and page reference."""

    id: str
    text: str
    page: int
    label: NotRequired[str]
    section: NotRequired[list[str]]
    source_offset: NotRequired[int]
    document_position: NotRequired[int]


class ParsedDocument(TypedDict):
    """Extracted manual content and the parser's reported completion status."""

    items: list[Evidence]
    pages: int
    parser_status: str
    outline: NotRequired[list[dict]]


class ProcedureTask(TypedDict):
    """One discovered reader task and the source passages that justify investigating it."""

    id: str
    title: str
    kind: str
    evidence_ids: list[str]
    scope: NotRequired[str]
    applies_to: NotRequired[str]
    applicability: NotRequired[str]
    lead_ids: NotRequired[list[str]]
    related_symptoms: NotRequired[list[dict]]
    related_symptoms_total: NotRequired[int]


class ProcedureGuide(TypedDict, total=False):
    """A source-linked draft or saved result, with completion fields added after review."""

    title: str
    outcome: str
    steps: list[dict]
    prerequisites: list[dict]
    independent_checks: list[dict]
    troubleshooting: dict | None
    schedule: dict | None
    unanswered_questions: list[str]
    applies_to: str
    id: str
    kind: str
    scope: str
    status: str
    completion: str
    review_issues: list[str]
    model_reviewed: bool
    inspected_source_ids: list[str]
    question_ledger: list[dict]
    review_suggestions: list[str]


class InspectionResult(TypedDict):
    """Preliminary observations, or an explicit record that no inspection was run."""

    observations: list[dict]
    decisions: list[dict]
    inspection_status: NotRequired[str]
    remaining_questions: NotRequired[list[str]]
    allowance: NotRequired[int]


class ExtractionResult(TypedDict):
    """Accepted facts and rejected proposals, plus subsequent question and guide outputs."""

    facts: list[dict]
    rejected: list[dict]
    troubleshooting: list[dict]
    faq: list[dict]
    guidance_rejected: list[dict]
    batches_processed: int
