"""Supply predetermined guide-review answers for tests of application control flow.
The answers let tests exercise acceptance and failure handling without contacting
a model; their correctness is not a measured AI result."""

import json

from workbench.procedure_guides.compare_source_and_guide_behavior import (
    instruction_fields,
)


def behavior_reply(request, defect=None):
    """Return covered source rows for routing tests, optionally reporting a defect.

    Args:
        request: Actual production review packet from an offline test.
        defect: Optional concrete fixture comparison failure for bounded-revision tests.
    Returns:
        Structured response with real quote locations. It intentionally supplies a
        canned semantic judgment; separate saved-case tests exercise live receipts.
    """
    data = json.loads(request.prompt.split("\n")[-1])
    text = next(text for path, text in instruction_fields(data["guide"]) if text)
    return {
        "source_actions": [
            {
                "source_id": s["id"],
                "source_quote": s["text"],
                "draft_quote": text,
                "comparison": defect or "Fixture behavior preserved.",
                "status": "changed" if defect else "preserved",
            }
            for s in data["sources"]
        ],
        "unsupported_draft_actions": [],
    }


def confirmed_claims_reply(request):
    """Confirm fixture defects to exercise the bounded second-check routing offline.

    Args:
        request: Production claim-verification request with original sources and text.
    Returns:
        Deterministic confirmed decisions with real quote locations. This is routing
        evidence only, not a substitute for live positive/negative judgment tests.
    """
    data = json.loads(request.prompt.split("\n")[-1])
    sources = {s["id"]: s["text"] for s in data["sources"]}
    path, text = next(iter(data["reader_instructions"].items()))
    return {
        "decisions": [
            {
                "claim_index": c["claim_index"],
                "source_id": c["evidence_ids"][0],
                "source_quote": sources[c["evidence_ids"][0]],
                "reader_path": path,
                "draft_quote": text,
                "explanation": c["issue"],
                "verdict": "confirmed",
            }
            for c in data["claims"]
        ]
    }
