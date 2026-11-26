"""Break source text into reviewable statements and retain an earlier grouped guide
checker.

Small comparisons help expose omissions that a whole-guide approval can miss. The
application keeps original text and references while the AI judges each
comparison. The current reviewer uses the text-splitting helpers here; the earlier
combined checker remains available for comparisons with historical experiments."""

import re
from typing import Literal

from pydantic import Field, model_validator

from workbench.data_models.analysis_and_question_models import Strict
from workbench.model_access.code_owned_source_evidence import (
    evidence_task,
    source_response_schema,
)
from workbench.procedure_guides.procedure_reply_models import (
    ProcedureEvidenceReview,
    ProcedureReviewCorrection,
)

VERSION = "context-and-task-scoped-review-v14"
COVERAGE = (
    "You are checking the READER GUIDE against the MANUAL, never the other way around. "
    "The statement_to_check is original manual text. Its section_context applies to it. "
    "Read those together before deciding what the manual requires. "
    "When scope_check_required is true, first explain whether the row applies to the assigned task, including its prerequisites and warnings. "
    "Use out_of_scope only for a clearly unrelated task, never because the guide omitted the action. "
    "Use unclear for uncertain relevance; relevant rows still require every documented action. "
    "Missing means missing from the reader_guide, not missing from the focused manual statement. "
    "First decide whether the focused manual text tells the reader to do, avoid or check something. "
    "If it only explains what the machine does or describes a state, return not_instruction; do not invent a reader obligation. "
    "Otherwise compare that required reader behavior with the complete reader instructions. "
    "Account for every reader action in the focused text, including actions joined by and, with conditions and required order from its context. "
    "Does following the guide preserve those behaviors? Equivalent wording and separate steps are fine. "
    "Present means equivalent reader behavior; absent means a required action is missing; different means behavior, condition or order changes. "
    "Use not_instruction if the focused text only describes automatic machine behavior or labels a topic. "
    "A required wait or indicator check is a reader instruction. Use unclear when evidence cannot settle the comparison. "
    "A required action must actually be stated in the reader guide. Never count an unstated prerequisite as present merely because it seems obvious, safe, necessary or implicit in another action. "
    "If even one explicit required action is unstated, report absent or different. "
    "Explain how each required action is expressed, or identify the missing action; do not judge wording preferences."
)
SUPPORT = (
    "Does the manual establish the actions, objects, named controls, materials, quantities and factual details in the proposed reader text? "
    "Section_context is the original heading governing that passage, not an unrelated source. "
    "Only the manual passages are evidence. The proposed text is the claim being tested, never evidence for itself. "
    "Read the complete proposed text with reader_context: its symptom, applicability, prerequisites and surrounding instructions define what the reader is told. "
    "Check those conditions against the manual; do not require them to be repeated inside every sentence. "
    "When evidence_gap is true, evaluate it as a limit of examined evidence, not a manufacturer claim: established means it states a bounded unanswered question without prescribing an unsupported action or claiming whole-manual absence. "
    "Do not infer missing symbols or use product knowledge: unspecified identities do not establish specific names. "
    "Check that specific control names are actually readable in the supplied manual text; treating missing symbols as named buttons is unsupported. "
    "Ordinary component words already used in the manual need no separate glossary definition. "
    "Equivalent wording is fine. Check support for the factual details, not whether prerequisites appear elsewhere in the guide; a separate coverage check evaluates conditions and order. "
    "Use established, not_established or unclear. Use not_instruction only for navigation labels. "
    "Explain concrete support or missing support, not punctuation or stylistic preferences."
)


SUPPORT += (
    " Check each proposed action against the original passages before deciding whether the "
    "combined instruction is supported. In your explanation, identify the source condition for "
    "each action and whether the proposed condition agrees. An action restricted to one situation "
    "cannot be moved into another situation merely because the action itself appears somewhere in "
    "the manual. Do not invent an unstated prerequisite to connect actions. If any action has an "
    "incompatible condition, reject the combined claim even when all its verbs and objects occur "
    "in the passages. A condition or sequence explicitly asserted in the proposed text is itself "
    "a factual claim that this support check must verify. Then check the readable objects, tools "
    "and quantities. An unexplained trailing marker does not erase an independently readable "
    "action or quantity; do not assign that marker an invented meaning. Conversely, an unreadable "
    "or missing quantity does not establish a specific number. Finally, consecutive documented "
    "actions may be expressed in a single reader step when every action and its condition, "
    "object, tool, quantity and required order are supported across the supplied passages. No "
    "single source passage needs to contain the entire proposed sentence. Reject concrete "
    "unsupported details or changed behavior, not sentence merging alone."
)


class RequiredBehaviorAnswer(Strict):
    """Judge the focused source text without writing references or quotations."""

    explanation: str = Field(min_length=1)
    result: Literal["present", "absent", "different", "not_instruction", "unclear"]


class ClaimSupportAnswer(Strict):
    """Judge source support for a code-selected reader statement."""

    explanation: str = Field(min_length=1)
    result: Literal["established", "not_established", "not_instruction", "unclear"]


def text_units(text):
    """Enumerate contiguous sentence-like spans without losing original characters.

    Args:
        text: Complete original source or reader string.
    Returns:
        Start/end/text records partitioning the original nonempty string exactly.
        Trailing colon labels remain attached to the preceding sentence. Conservative
        punctuation boundaries may not be linguistic sentences. Source comparisons
        retain original source context; reader instructions are reviewed whole.
    """
    boundaries = (
        [0] + [m.end() for m in re.finditer(r"[.!?]\s+(?=[A-Z])", text)] + [len(text)]
    )
    units = [
        {"start": a, "end": b, "text": text[a:b]}
        for a, b in zip(boundaries, boundaries[1:])
        if b > a
    ]
    # A trailing label introducing a continuation is not a separate sentence.
    # Retain it with the preceding text, rather than inventing a standalone duty.
    if len(units) > 1 and units[-1]["text"].rstrip().endswith(":"):
        tail = units.pop()
        units[-1]["end"] = tail["end"]
        units[-1]["text"] = text[units[-1]["start"] : tail["end"]]
    return units


MAX_COMPARISONS = 6
BATCH_OUTPUT_TOKENS = 3000
BATCH_INSTRUCTIONS = (
    " Review each numbered comparison independently and return exactly one judgment for every supplied number, including positive judgments. "
    "Do not omit or invent comparison numbers. Keep each explanation concise and make its result agree with it. "
    "Coverage statements with scope_check_required need a task-relevance decision; other coverage statements are required obligations. Other passages are supporting context, not additional tasks to reproduce. "
    "For support, only original manual passages are evidence, never another part of a proposed guide."
)


class ReviewJudgment(Strict):
    """One result for a code-owned comparison, with no model-written references."""

    comparison: int
    explanation: str = Field(min_length=1)
    result: Literal[
        "present",
        "absent",
        "different",
        "not_instruction",
        "unclear",
        "established",
        "not_established",
        "out_of_scope",
    ]


class BatchedProcedureReview(Strict):
    """Explicit per-comparison results instead of a broad approval flag."""

    judgments: list[ReviewJudgment]


def batch_schema(comparisons):
    """Require complete, correctly typed accounting within the normal correction path.

    Args:
        comparisons: Numbered comparisons actually supplied in one request.
    Returns:
        Response class whose validator rejects omitted, duplicate, unknown or
        wrong-kind results. Run saves the raw reply and allows its usual single
        format correction; no local repair or extra retry allowance is introduced.
    """
    expected = {c["comparison"]: c["kind"] for c in comparisons}
    scope_checks = {
        c["comparison"] for c in comparisons if c.get("scope_check_required")
    }

    class ValidatedReview(BatchedProcedureReview):
        """Bind the ordinary response schema to this request's complete inventory."""

        model_config = {
            "extra": "forbid",
            "strict": True,
            "title": "BatchedProcedureReview",
        }

        @classmethod
        def model_json_schema(cls, *args, **kwargs):
            """Advertise only result labels accepted for this request's kind.

            Args:
                cls: Response class for the current comparison inventory.
                *args: Standard Pydantic schema arguments.
                **kwargs: Standard Pydantic schema options.
            Returns:
                Independent schema with kind-specific choices; mixed batches keep
                their union. Inventory and result validators remain unchanged.
            """
            result = super().model_json_schema(*args, **kwargs)
            kinds = set(expected.values())
            if len(kinds) == 1:
                allowed = (
                    {"present", "absent", "different", "not_instruction", "unclear"}
                    if kinds == {"coverage"}
                    else {
                        "established",
                        "not_established",
                        "not_instruction",
                        "unclear",
                    }
                )
                if kinds == {"coverage"} and scope_checks:
                    allowed.add("out_of_scope")
                for definition in result.get("$defs", {}).values():
                    field = definition.get("properties", {}).get("result", {})
                    if "enum" in field:
                        field["enum"] = [v for v in field["enum"] if v in allowed]
            return result

        @model_validator(mode="after")
        def check_inventory(self):
            """Validate coverage accounting after normal response parsing.

            Args:
                self: Parsed model reply containing numbered judgments.
            Returns:
                Unchanged reply if every supplied comparison has exactly one valid
                decision; otherwise raises ValueError for the bounded correction.
            """
            numbers = [j.comparison for j in self.judgments]
            if sorted(numbers) != sorted(expected):
                raise ValueError(
                    "Return each supplied comparison exactly once: "
                    + str(sorted(expected))
                )
            for judgment in self.judgments:
                allowed = (
                    {"present", "absent", "different", "not_instruction", "unclear"}
                    if expected[judgment.comparison] == "coverage"
                    else {
                        "established",
                        "not_established",
                        "not_instruction",
                        "unclear",
                    }
                )
                if judgment.comparison in scope_checks:
                    allowed.add("out_of_scope")
                if judgment.result not in allowed:
                    raise ValueError(
                        f"Comparison {judgment.comparison} needs a {expected[judgment.comparison]} decision"
                    )
            return self

    return ValidatedReview


def compare_source_and_guide_behavior(guide, sources, run, task=None, document=None):
    """Review one complete guide in bounded batches using code-selected obligations.

    Args:
        guide: Complete validated guide with original source citations.
        sources: Original collected passages available as evidence/context.
        run: Shared ordinary request owner, enforcing existing budgets and replay.
        document: Full original parsed document for heading identity recovery.
            Original files are never modified.
        task: Optional original assigned task; scope/title/applicability are passed
            as context, never source evidence or permission to invent instructions.
    Returns:
        Review and source/reader-location audit. No comparison is dropped or marked
        successful without a returned judgment. Oversized batches split before
        dispatch; an indivisible oversized request fails without truncating evidence.
        Incomplete/invalid replies use existing failure handling and retain drafts.
        No revision-delta cache or new per-guide spending allowance is introduced.
    """
    from workbench.agentic_workflow.model_call_allowances import (
        MAX_REQUEST_INPUT,
        estimate_input,
    )
    from workbench.model_access.model_requests_and_responses import ModelError, Request
    from workbench.model_prompts.shared_model_instructions import SYSTEM
    from workbench.procedure_guides.compare_source_and_guide_behavior import (
        reader_guide,
    )
    from workbench.procedure_guides.prepare_batched_guide_review import (
        prepare_comparisons,
    )
    from workbench.procedure_guides.retain_governing_heading_sources import (
        retain_heading_sources,
    )

    sources = retain_heading_sources(sources, document)
    comparisons, scope, problems = prepare_comparisons(guide, sources, text_units)
    source_ids = [s["id"] for s in sources] or ["unavailable"]
    corrections = [
        ProcedureReviewCorrection(
            issue=p["issue"], step_id="guide", evidence_ids=p["evidence_ids"]
        )
        for p in problems
    ]
    receipt = {
        "version": VERSION,
        "source_records": sources,
        "scope": scope,
        "coverage": [],
        "support": [],
        "batches": [],
    }
    if not comparisons:
        if guide.get("outcome") in {"partial", "insufficient_evidence"} and guide.get(
            "unanswered_questions"
        ):
            return ProcedureEvidenceReview(acceptable=True), []
        corrections.append(
            ProcedureReviewCorrection(
                issue="No source-linked instructions were available; review remains incomplete.",
                step_id="guide",
                evidence_ids=source_ids,
            )
        )
    elif not any(c["kind"] == "coverage" for c in comparisons) or not any(
        c["kind"] == "support" for c in comparisons
    ):
        corrections.append(
            ProcedureReviewCorrection(
                issue="No complete source/reader instruction comparison was available; review remains incomplete.",
                step_id="guide",
                evidence_ids=source_ids,
            )
        )
    pending = []
    for kind in ("coverage", "support"):
        same_kind = [c for c in comparisons if c["kind"] == kind]
        pending.extend(
            same_kind[i : i + MAX_COMPARISONS]
            for i in range(0, len(same_kind), MAX_COMPARISONS)
        )
    while pending:
        group = pending.pop(0)
        schema = batch_schema(group)
        payload = {
            "assigned_procedure": {
                key: (task or guide).get(key, "")
                for key in ("title", "kind", "scope", "applies_to", "applicability")
            },
            "comparisons": [
                {k: v for k, v in c.items() if not k.startswith("_")} for c in group
            ],
        }
        if group[0]["kind"] == "coverage":
            payload["reader_guide"] = reader_guide(guide)
        instructions = (
            COVERAGE if group[0]["kind"] == "coverage" else SUPPORT
        ) + BATCH_INSTRUCTIONS
        prompt = evidence_task(instructions, payload, sources)
        estimated = estimate_input(
            Request(
                prompt,
                SYSTEM,
                schema=source_response_schema(schema, prompt).model_json_schema(),
                max_tokens=BATCH_OUTPUT_TOKENS,
            )
        )
        if estimated > MAX_REQUEST_INPUT:
            if len(group) == 1:
                raise ModelError(
                    "Review context exceeds the request allowance; original evidence and draft are retained unchanged."
                )
            middle = len(group) // 2
            pending[0:0] = [group[:middle], group[middle:]]
            continue
        reply = run.call("text", prompt, schema, cap=BATCH_OUTPUT_TOKENS)
        by_number = {j.comparison: j for j in reply.judgments}
        receipt["batches"].append(
            {
                "comparisons": [c["comparison"] for c in group],
                "estimated_input": estimated,
            }
        )
        for comparison in group:
            judgment = by_number[comparison["comparison"]]
            item = {
                "comparison": comparison["comparison"],
                "answer": judgment.model_dump(),
            }
            if comparison["kind"] == "coverage":
                item.update(
                    source_id=comparison["_source_ids"][0],
                    unit=comparison["_unit"],
                    context_source_ids=comparison["_source_ids"],
                )
                accepted = judgment.result in {
                    "present",
                    "not_instruction",
                    "out_of_scope",
                }
            else:
                item.update(
                    reader_path=comparison["_reader_path"], unit=comparison["_unit"]
                )
                accepted = judgment.result in {"established", "not_instruction"}
            receipt[comparison["kind"]].append(item)
            if not accepted:
                corrections.append(
                    ProcedureReviewCorrection(
                        issue=judgment.explanation,
                        step_id=comparison.get("_reader_path", "guide"),
                        evidence_ids=comparison["_source_ids"] or source_ids,
                    )
                )
    return ProcedureEvidenceReview(
        acceptable=not corrections, corrections=corrections
    ), [receipt] if comparisons else []
