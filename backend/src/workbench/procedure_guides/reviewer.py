"""Review whether a generated guide follows the manual without adding or losing
instructions.

Separate AI questions check which passages apply, whether required actions and
warnings appear in the guide, and whether the guide's claims have source support.
Specific negative findings can receive a further check for a concrete needed
change. All decisions remain inspectable; unfinished checks are not approval, and
model review is not a human safety assessment."""

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
from workbench.procedure_guides.review_jobs import (
    VERSION,
    MAX_COMPARISONS,
    OUTPUT_CAP,
    INSTRUCTIONS,
    ACCOUNTING,
    job_schema,
)
from workbench.procedure_guides.review_batches import judge_batches
from workbench.procedure_guides.review_audit import record_judgment


from collections.abc import Sequence
from workbench.data_models.application_types import (
    Evidence,
    ProcedureGuide,
    ProcedureTask,
    ParsedDocument,
)
from workbench.agentic_workflow.execution import Run


def compare_source_and_guide_behavior(
    guide: ProcedureGuide,
    sources: list[Evidence],
    run: Run,
    task: ProcedureTask | None = None,
    document: ParsedDocument | None = None,
    required_source_ids: Sequence[str] = (),
) -> tuple[ProcedureEvidenceReview, list[dict]]:
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
