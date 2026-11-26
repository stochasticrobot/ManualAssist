"""Keep each review decision attached to the exact instruction it checked.

Negative or uncertain answers become proposed corrections, while all answers remain
available for inspection. Recording an answer never changes the model's verdict or
turns an unfinished check into approval.
"""

from workbench.procedure_guides.procedure_reply_models import ProcedureReviewCorrection


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
