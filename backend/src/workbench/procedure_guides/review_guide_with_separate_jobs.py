"""Review whether a generated guide follows the manual without adding or losing
instructions.

Separate AI questions check which passages apply, whether required actions and
warnings appear in the guide, and whether the guide's claims have source support.
Specific negative findings can receive a further check for a concrete needed
change. All decisions remain inspectable; unfinished checks are not approval, and
model review is not a human safety assessment."""

from typing import Literal

from pydantic import Field, model_validator

from workbench.agentic_workflow.model_call_allowances import (
    MAX_REQUEST_INPUT,
    estimate_input,
)
from workbench.data_models.analysis_and_question_models import Strict
from workbench.model_access.code_owned_source_evidence import (
    evidence_task,
    source_response_schema,
)
from workbench.model_access.model_requests_and_responses import ModelError, Request
from workbench.model_prompts.shared_model_instructions import SYSTEM
from workbench.procedure_guides.compare_source_and_guide_behavior import reader_guide
from workbench.procedure_guides.prepare_batched_guide_review import prepare_comparisons
from workbench.procedure_guides.procedure_reply_models import (
    ProcedureEvidenceReview,
    ProcedureReviewCorrection,
)
from workbench.procedure_guides.retain_governing_heading_sources import (
    retain_heading_sources,
)
from workbench.procedure_guides.review_actions_with_code_owned_evidence import (
    text_units,
)

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


def judge_batches(stage, comparisons, guide, assigned, sources, run, audit):
    """Dispatch homogeneous jobs without losing evidence when an input is large.

    Args:
        stage: One review responsibility with its own prompt and response schema.
        comparisons: Prepared comparisons retaining private original locations.
        guide: Complete reader guide, visible only to coverage; support already has
            its local reader context and relevance never sees the draft.
        assigned: Original task title, category and applicability, not source evidence.
        sources: Full selected original passages, unchanged across job types.
        run: Ordinary production request owner with shared budgets and receipts.
        audit: Mutable per-guide audit receiving measured batch estimates and results.
    Returns:
        Comparison/judgment pairs. Oversized batches split before dispatch; an
        indivisible oversized request raises without truncation. Model/format failures
        propagate with raw request receipts preserved; no local verdict repair occurs.
    """
    pending = [
        comparisons[i : i + MAX_COMPARISONS]
        for i in range(0, len(comparisons), MAX_COMPARISONS)
    ]
    results = []
    while pending:
        group = pending.pop(0)
        payload = {
            "assigned_procedure": assigned,
            "comparisons": [
                {
                    k: v
                    for k, v in c.items()
                    if not k.startswith("_") and k != "scope_check_required"
                }
                for c in group
            ],
        }
        if stage == "coverage":
            payload["reader_guide"] = reader_guide(guide)
        schema = job_schema(stage, group)
        prompt = evidence_task(INSTRUCTIONS[stage] + ACCOUNTING, payload, sources)
        estimate = estimate_input(
            Request(
                prompt,
                SYSTEM,
                schema=source_response_schema(schema, prompt).model_json_schema(),
                max_tokens=OUTPUT_CAP,
            )
        )
        if estimate > MAX_REQUEST_INPUT:
            if len(group) == 1:
                raise ModelError(
                    "Review context exceeds the request allowance; original evidence and draft remain unchanged."
                )
            middle = len(group) // 2
            pending[0:0] = [group[:middle], group[middle:]]
            continue
        reply = run.call("text", prompt, schema, cap=OUTPUT_CAP)
        by_number = {j.comparison: j for j in reply.judgments}
        audit["batches"].append(
            {
                "stage": stage,
                "comparisons": [c["comparison"] for c in group],
                "estimated_input": estimate,
                "answers": reply.model_dump()["judgments"],
            }
        )
        results.extend((c, by_number[c["comparison"]]) for c in group)
    return results


def record_judgment(comparison, judgment, stage, audit, corrections):
    """Attach a narrow job's decision to the original source or reader location.

    Args:
        comparison: Original code-owned comparison with private source references.
        judgment: Validated semantic response, never locally rewritten.
        stage: Actual job that made the decision, including relevance exclusions.
        audit: Mutable per-guide record receiving the unchanged answer and original unit.
        corrections: Mutable corrections list for negative or uncertain judgments.
    Returns:
        None; records every judgment. Relevant scope decisions are routed separately;
        uncertainty never becomes approval. Semantic correctness still needs testing.
    """
    kind = comparison["kind"]
    item = {
        "comparison": comparison["comparison"],
        "answer": judgment.model_dump(),
        "stage": stage,
        "unit": comparison["_unit"],
    }
    if kind == "coverage":
        item.update(
            source_id=comparison["_source_ids"][0],
            context_source_ids=comparison["_source_ids"],
        )
    else:
        item["reader_path"] = comparison["_reader_path"]
    audit[kind].append(item)
    accepted = {
        "relevance": {"out_of_scope", "not_instruction"},
        "coverage": {"present", "not_instruction"},
        "support": {"established", "not_instruction"},
        "evidence_gap": {"established", "not_instruction"},
    }[stage]
    if judgment.result not in accepted:
        corrections.append(
            ProcedureReviewCorrection(
                issue=judgment.explanation,
                step_id=comparison.get("_reader_path", "guide"),
                evidence_ids=comparison["_source_ids"],
            )
        )


def compare_source_and_guide_behavior(
    guide, sources, run, task=None, document=None, required_source_ids=()
):
    """Review a guide through separate applicability, coverage and support jobs.

    Args:
        guide: Complete validated reader guide and original citations.
        sources: Original collected evidence, including uncited supporting passages.
        run: Production request owner enforcing the caller's finite allowance.
        task: Original assigned task; falls back to guide metadata when absent.
        document: Full parsed document for original headings and continuation context.
        required_source_ids: Earlier draft sources whose coverage must survive edits.
    Returns:
        ProcedureEvidenceReview plus an audit retaining every original comparison,
        scope decision and source/reader binding. Unknown scope or support prevents
        acceptance. Format/provider errors propagate without editing the guide.
        The production planner and compatibility entry point use this same function.
    """
    sources = retain_heading_sources(sources, document)
    comparisons, scope, problems = prepare_comparisons(
        guide, sources, text_units, required_source_ids
    )
    source_ids = [s["id"] for s in sources] or ["unavailable"]
    corrections = [
        ProcedureReviewCorrection(
            issue=p["issue"], step_id="guide", evidence_ids=p["evidence_ids"]
        )
        for p in problems
    ]
    audit = {
        "version": VERSION,
        "source_records": sources,
        "scope": scope,
        "relevance": [],
        "coverage": [],
        "support": [],
        "batches": [],
    }
    if (
        not comparisons
        and guide.get("outcome") in {"partial", "insufficient_evidence"}
        and guide.get("unanswered_questions")
    ):
        return ProcedureEvidenceReview(acceptable=True), []
    if {c["kind"] for c in comparisons} != {"coverage", "support"}:
        corrections.append(
            ProcedureReviewCorrection(
                issue="No complete source/reader instruction comparison was available; review remains incomplete.",
                step_id="guide",
                evidence_ids=source_ids,
            )
        )
    structural_count = len(corrections)
    assigned = {
        key: (task or guide).get(key, "")
        for key in ("title", "kind", "scope", "applies_to", "applicability")
    }
    heading_ids = {
        item["source_id"]
        for item in scope
        if item["mode"] == "explicit_governing_heading"
    }
    relevance = [
        c
        for c in comparisons
        if c.get("scope_check_required")
        or (c["kind"] == "coverage" and c["_source_ids"][0] in heading_ids)
    ]
    excluded = set()
    for comparison, judgment in judge_batches(
        "relevance", relevance, guide, assigned, sources, run, audit
    ):
        audit["relevance"].append(judgment.model_dump())
        if judgment.result != "required":
            excluded.add(comparison["comparison"])
            record_judgment(comparison, judgment, "relevance", audit, corrections)
    for stage in ("coverage", "support", "evidence_gap"):
        selected = [
            c
            for c in comparisons
            if c["comparison"] not in excluded
            and (
                (stage == "coverage" and c["kind"] == "coverage")
                or (
                    stage != "coverage"
                    and c["kind"] == "support"
                    and bool(c.get("evidence_gap")) == (stage == "evidence_gap")
                )
            )
        ]
        for comparison, judgment in judge_batches(
            stage, selected, guide, assigned, sources, run, audit
        ):
            record_judgment(comparison, judgment, stage, audit, corrections)
    expected = sorted(c["comparison"] for c in comparisons)
    recorded = sorted(
        c["comparison"] for kind in ("coverage", "support") for c in audit[kind]
    )
    if expected != recorded:
        raise ValueError(
            "Review did not account for every original comparison exactly once"
        )
    if corrections[structural_count:]:
        from workbench.procedure_guides.check_stalled_review_objections import (
            check_stalled_review_objections,
        )

        remaining, checks = check_stalled_review_objections(
            guide, task or guide, sources, corrections[structural_count:], run
        )
        audit["objection_checks"] = checks
        corrections = corrections[:structural_count] + remaining
    return ProcedureEvidenceReview(
        acceptable=not corrections, corrections=corrections
    ), [audit]


def review_configuration():
    """Fingerprint every deployed review job so incompatible saved work cannot resume.

    Args:
        None; reads loaded prompts, schemas and batch/output limits without I/O.
    Returns:
        JSON-compatible configuration covering all jobs and their allowed decisions.
        Changing a review job invalidates old planner fingerprints rather than
        silently reusing results checked by another reviewer version.
    """
    from workbench.procedure_guides.check_stalled_review_objections import (
        INSTRUCTIONS as OBJECTION_INSTRUCTIONS,
        ObjectionDecision,
    )

    return {
        "objection_check": {
            "instructions": OBJECTION_INSTRUCTIONS,
            "schema": ObjectionDecision.model_json_schema(),
            "policy": "source-and-reader-bound-v2",
        },
        "version": VERSION,
        "instructions": {
            stage: text + ACCOUNTING for stage, text in INSTRUCTIONS.items()
        },
        "schemas": {
            stage: job_schema(stage, [{"comparison": 1}]).model_json_schema()
            for stage in INSTRUCTIONS
        },
        "max_comparisons": MAX_COMPARISONS,
        "output_cap": OUTPUT_CAP,
    }
