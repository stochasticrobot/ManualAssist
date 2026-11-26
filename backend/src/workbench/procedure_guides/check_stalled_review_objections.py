"""Check whether a review complaint really requires changing the reader's guide.

A reviewer may demand an unrelated task or miss equivalent wording already in the
guide. This second check sees the complete guide and supplied manual passages,
asks for a concrete needed change, and records its reasons. Unsupported or
uncertain dismissals remain blockers; a second AI opinion is not independent proof
that the guide is correct."""

from typing import Literal
from pydantic import Field, model_validator
from workbench.data_models.analysis_and_question_models import Citation, Strict
from workbench.model_access.code_owned_source_evidence import evidence_task
from workbench.procedure_guides.procedure_reply_models import ProcedureReviewCorrection
from workbench.procedure_guides.compare_source_and_guide_behavior import (
    reader_guide,
    instruction_fields,
)

INSTRUCTIONS = """For each review concern, decide whether this guide needs a concrete change to follow the manual.
Use the assigned task AND its prerequisites and the subtasks covered by the guide. Do not narrow the task to its title.
A statement that something is absent is not enough: explain why that content is required for this task. Unrelated procedures and section labels need not be added. Actual governing instructions, conditions, order and warnings must remain.
Count equivalent source-supported wording anywhere in the guide, including prerequisites and checks. Do not assume unstated actions or let a precaution substitute for a missing hazard warning.
State the exact required change, then choose needs_change, no_change, or uncertain. For no_change, leave required_change empty and select the reader positions supporting your explanation. Select source passages for every decision.
"""


class ObjectionDecision(Strict):
    """One source-linked judgment about a reported defect, not whole-guide approval."""

    objection: int
    explanation: str = Field(min_length=1)
    verdict: Literal["needs_change", "no_change", "uncertain"]
    required_change: str
    reader_positions: list[int]
    citations: list[Citation] = Field(min_length=1)


def reader_strings(value):
    """Collect actual reader-facing strings so evidence cannot masquerade as the guide.

    Args:
        value: Citation-free reader guide, nested list, dictionary or scalar.
    Returns:
        List of exact strings; no model inference or source quotation is added.
    """
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [text for child in value.values() for text in reader_strings(child)]
    if isinstance(value, list):
        return [text for child in value for text in reader_strings(child)]
    return []


def check_stalled_review_objections(guide, task, sources, corrections, run):
    """Verify a bounded set of disputed objections while retaining every raw decision.

    Args:
        guide: Complete source-validated draft whose review cannot make progress.
        task: Original assigned task with its scope and applicability.
        sources: Unchanged review evidence, including prior required sources.
        corrections: Semantic objections from the last review, in original order.
        run: Production request owner with normal accounting and source bindings.
    Returns:
        Remaining concrete change requests and verification audit. Only source-bound no-change decisions
        with valid code-owned reader selections including actual instructions or conditions remove an objection; required changes, uncertainty or
        unvalid decisions retain it. No guide, source or initial verdict is edited.
        Provider, budget and schema errors propagate without granting approval.
    """
    reader = reader_guide(guide)
    strings = reader_strings(reader)
    meaningful_text = {text for _, text in instruction_fields(reader)}
    remaining, audit = [], []
    for start in range(0, len(corrections), 4):
        group = corrections[start : start + 4]
        expected = list(range(len(group)))

        class ObjectionReply(Strict):
            """Account for every supplied objection exactly once."""

            decisions: list[ObjectionDecision]

            @model_validator(mode="after")
            def complete(self):
                """Reject missing or invented decisions through normal format correction.

                Args:
                    self: Parsed objection decisions for the current group.
                Returns:
                    Unchanged reply, or ValueError for incomplete/duplicate accounting.
                """
                if sorted(d.objection for d in self.decisions) != expected:
                    raise ValueError(f"Return each objection exactly once: {expected}")
                return self

        prompt = evidence_task(
            INSTRUCTIONS,
            {
                "assigned_task": {
                    k: task.get(k, "")
                    for k in ["title", "kind", "scope", "applicability"]
                },
                "reader_guide": reader,
                "reader_positions": [
                    {"position": i, "text": text} for i, text in enumerate(strings)
                ],
                "reported_defects": [
                    {"objection": i, **c.model_dump()} for i, c in enumerate(group)
                ],
            },
            sources,
        )
        reply = run.call("text", prompt, ObjectionReply, cap=2200)
        for decision in reply.decisions:
            original = group[decision.objection]
            matched = bool(decision.reader_positions) and all(
                0 <= i < len(strings) for i in decision.reader_positions
            )
            matched = matched and any(
                strings[i] in meaningful_text
                for i in decision.reader_positions
                if 0 <= i < len(strings)
            )
            dismissed = (
                decision.verdict == "no_change"
                and matched
                and not decision.required_change.strip()
            )
            audit.append(
                {
                    "original": original.model_dump(),
                    "decision": decision.model_dump(),
                    "reader_positions_valid": matched,
                    "selected_reader_text": [
                        strings[i]
                        for i in decision.reader_positions
                        if 0 <= i < len(strings)
                    ],
                    "dismissed": dismissed,
                }
            )
            if not dismissed:
                remaining.append(
                    ProcedureReviewCorrection(
                        issue=decision.required_change,
                        step_id=original.step_id,
                        evidence_ids=list(
                            dict.fromkeys(c.evidence_id for c in decision.citations)
                        ),
                    )
                    if decision.verdict == "needs_change"
                    and decision.required_change.strip()
                    else original
                )
    return remaining, audit
