"""Check that a request to correct an invalid guide reply stays within its size limit
without losing the original reply or cited evidence. These tests inspect prepared
text rather than calling an AI."""

import json
import pytest
from workbench.agentic_workflow.validate_and_correct_model_json import (
    bounded_correction_prompt,
    correction_prompt,
    parse_response,
)
from workbench.agentic_workflow.model_call_allowances import (
    estimate_input,
    MAX_REQUEST_INPUT,
)
from workbench.model_access.model_requests_and_responses import Request
from workbench.model_prompts.shared_model_instructions import SYSTEM
from workbench.procedure_guides.procedure_reply_models import (
    ProcedureInspectionDecision,
)


def test_large_correction_keeps_reply_and_cited_sources_without_search_history():
    """Check the complete request budget and lossless source/reply preservation.

    Args:
        None; synthetic history imitates an investigation approaching its input limit.
    Returns:
        None; confirms only unrelated history disappears, the invalid reply remains
        byte-for-byte intact, and referenced passages still occur unchanged.
    """
    schema = ProcedureInspectionDecision.model_json_schema()
    source = dict(
        id="kept", text="Exact original passage. " * 200, page=2, label="text"
    )
    context = dict(
        task=dict(kind="installation", title="Setup", scope="procedure"),
        sources=[source],
        observations=["history " * 3500],
    )
    prompt = "Investigate the task.\n" + json.dumps(context)
    text = json.dumps(
        dict(
            action="finish",
            reason="explanation " * 1500,
            draft=dict(
                citations=[dict(evidence_id="kept", quote="Exact original passage.")]
            ),
        )
    )
    assert estimate_input(Request(prompt, SYSTEM, schema=schema)) < MAX_REQUEST_INPUT
    with pytest.raises(Exception) as failure:
        parse_response(ProcedureInspectionDecision, text)
    original = correction_prompt(prompt, text, failure.value)
    assert estimate_input(Request(original, SYSTEM, schema=schema)) > MAX_REQUEST_INPUT
    result = bounded_correction_prompt(prompt, text, failure.value, schema, SYSTEM)
    assert estimate_input(Request(result, SYSTEM, schema=schema)) <= MAX_REQUEST_INPUT
    assert result.endswith(text)
    assert source["text"] in result
    assert "history " * 100 not in result


def test_small_correction_preserves_original_replay_identity():
    """Keep previously valid correction requests identical for saved-response reuse.

    Args:
        None; a small malformed response fits without reducing any context.
    Returns:
        None; confirms unchanged requests can still reuse existing correction receipts.
    """
    schema = ProcedureInspectionDecision.model_json_schema()
    with pytest.raises(Exception) as failure:
        parse_response(ProcedureInspectionDecision, "{}")
    assert bounded_correction_prompt(
        "Original source", "{}", failure.value, schema, SYSTEM
    ) == correction_prompt("Original source", "{}", failure.value)
