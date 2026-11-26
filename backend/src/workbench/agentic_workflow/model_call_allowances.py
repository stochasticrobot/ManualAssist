"""Limit how much AI work can start in one authorized analysis or continuation.

These limits keep a difficult manual from causing unlimited requests. Completed
calls use the provider's reported input usage; unfinished calls temporarily use
estimates. Reaching a limit pauses the work while preserving completed results. It
does not declare the manual complete or resume spending automatically."""

import json
from workbench.model_access.model_requests_and_responses import ModelError, Request

# Whole-document headroom: the observed 44-page sample plans about 359 calls
# and 1.92M estimated input tokens before inspections, corrections or subdivisions.
# The latest 44-page run spent 5,997,201 estimated input tokens in 758 calls.
# Retain the approved 6M ceiling now that completed calls use measured usage.
# Completed calls consume measured input; estimates cover outstanding/unknown usage.
MAX_CALLS = 1_000
MAX_VISION_CALLS = 2
MAX_INPUT_TOKENS = 6_000_000
MAX_REQUEST_INPUT = 24_000


class BudgetPause(ModelError):
    """The authorized work slice is spent; saved work can be explicitly continued."""


def estimate_input(request: Request) -> int:
    """Estimate input size consistently for planning and pre-dispatch checks.

    Args:
        request: Neutral request including system instructions and optional schema.
    Returns:
        Rough input tokens at two UTF-8 bytes per token plus 4,000 per image.
        This is not a tokenizer or a guaranteed upper bound for all providers.
    """
    text = request.system + request.prompt
    if request.schema:
        text += "\nReturn only JSON matching this response schema:\n" + json.dumps(
            request.schema
        )
    return (len(text.encode("utf-8")) + 1) // 2 + 4000 * len(request.images)
