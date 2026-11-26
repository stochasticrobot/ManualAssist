"""Estimate how much manual text is left to send for fact extraction.

The progress display needs an approximate remaining-work figure before every
request has finished. This calculation uses the saved plan and completed work; it
does not ask a model, predict a price, or replace measured usage."""

import json
import math
from workbench.manual_analysis.estimate_fact_extraction_work import extraction_prompt
from workbench.data_models.analysis_and_question_models import FactExtraction
from workbench.model_access.model_requests_and_responses import Request
from workbench.model_prompts.shared_model_instructions import SYSTEM
from workbench.agentic_workflow.model_call_allowances import estimate_input


def remaining_estimate(path, batches, completed, events):
    """Estimate only unprocessed extraction, not variable inspection or finding review.

    Args:
        path: Job directory containing private request receipts.
        batches: Actual extraction boundaries, including current saved subdivisions.
        completed: Number of durably completed extraction batches.
        events: Recorded model results used for observed output-size samples.
    Returns:
        Rough input/output ranges and explicit scope. Output is unknown until an
        extraction sample exists. Does not contact a provider or modify job state.
    """
    remaining = batches[completed:]
    high = sum(
        estimate_input(
            Request(
                extraction_prompt(b),
                SYSTEM,
                schema=FactExtraction.model_json_schema(),
            )
        )
        for b in remaining
    )
    samples = []
    for event in events:
        if event["kind"] != "model_result" or event.get("stop_reason") not in (
            "end_turn",
            "complete",
            "stop_sequence",
        ):
            continue
        request_path = path / f"call-{event['call']:03}-request.json"
        if not request_path.exists():
            continue
        request = json.loads(request_path.read_text())
        if (request.get("schema") or {}).get("title") in (
            "FactExtraction",
        ) and event.get("output_tokens") is not None:
            samples.append(event["output_tokens"])
    output = None
    if not remaining:
        output = [0, 0]
    elif samples:
        mean = sum(samples) / len(samples) * len(remaining)
        output = [math.floor(mean * 0.7), math.ceil(mean * 1.5)]
    return {
        "input_range": [math.ceil(high / 3), high],
        "output_range": output,
        "remaining_batches": len(remaining),
        "note": "Remaining extraction only. Input uses a rough 2–6 UTF-8 bytes/token range including repeated instructions. Output uses observed extraction responses. Excludes inspection, uncertainty review, FAQ generation, troubleshooting generation, subdivisions and Q&A; not a guaranteed bound.",
    }
