"""Estimate the work needed to extract facts before starting the analysis.

The Import screen needs to show how many small text requests are planned and an
approximate amount of input. This calculation uses the same manual portions as
actual extraction, but sends no AI requests and extracts no facts. The estimate is
not a measured bill or a promise that no retries will be needed."""

from workbench.data_models.analysis_and_question_models import FactExtraction
from workbench.model_access.model_requests_and_responses import Request
from workbench.model_prompts.shared_model_instructions import SYSTEM
from workbench.model_prompts.analysis_task_prompts import (
    facts_prompt as extraction_prompt,
)
from workbench.agentic_workflow.model_call_allowances import (
    estimate_input,
    MAX_REQUEST_INPUT,
)
from workbench.manual_analysis.group_sources_for_fact_extraction import (
    build_fact_batches as build_batches,
)
from workbench.manual_analysis.check_source_quotations import evidence_payload


def analysis_preflight(document):
    """Preview fact-extraction work without constructing clients or spending tokens.

    Args:
        document: Parsed manual with original source items.
    Returns:
        Batch count and rough input estimate using the current default text allowance.
        Actual execution uses the configured model's allowance and may subdivide more.
        A blocker describes a single oversized request, never total document length.
    """
    batches = build_batches(document["items"])
    estimates = [
        estimate_input(
            Request(
                extraction_prompt(batch),
                SYSTEM,
                schema=FactExtraction.model_json_schema(),
            )
        )
        for batch in batches
    ]
    return {
        "batches": len(batches),
        "source_characters": sum(len(evidence_payload(b)) for b in batches),
        "estimated_extraction_input": sum(estimates),
        "blocker": "A single fact request exceeds the input allowance."
        if any(n > MAX_REQUEST_INPUT for n in estimates)
        else None,
    }
