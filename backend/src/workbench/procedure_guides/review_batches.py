"""Send review questions in groups that fit the model's input allowance.

Large groups are split without shortening the guide or original manual passages.
Every reply is recorded with the comparisons it answered. This file handles request
sizes and accounting; the reviewer decides what the answers mean for completion.
"""

from workbench.agentic_workflow.model_call_allowances import (
    MAX_REQUEST_INPUT,
    estimate_input,
)
from workbench.model_access.code_owned_source_evidence import (
    evidence_task,
    source_response_schema,
)
from workbench.model_access.model_requests_and_responses import ModelError, Request
from workbench.model_prompts.shared_model_instructions import SYSTEM
from workbench.procedure_guides.compare_source_and_guide_behavior import reader_guide
from workbench.procedure_guides.review_jobs import (
    MAX_COMPARISONS,
    OUTPUT_CAP,
    INSTRUCTIONS,
    ACCOUNTING,
    job_schema,
)


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
