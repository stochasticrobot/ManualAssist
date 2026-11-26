"""Keep proposed facts only when their quoted evidence matches the supplied manual.

The application attaches page references from the original passages rather than
trusting an AI to invent them. Rejected facts are recorded separately so
unsupported content is not silently displayed as accepted. These checks verify
quotations, not the truth of the manual or every interpretation of it."""

from workbench.manual_analysis.check_source_quotations import anchored, source_map

EMPTY = {
    "facts": [],
    "findings": [],
    "rejected": [],
    "troubleshooting": [],
    "faq": [],
    "guidance_rejected": [],
    "batches_processed": 0,
}


def accept(response, batch):
    """Check proposed facts against precisely the supplied source group.

    Args:
        response: Current FactExtraction response with proposed facts.
        batch: Original evidence or bounded fragments from the request.
    Returns:
        New lists of accepted/rejected proposals; original model reply stays in receipts.
        Quote matching does not prove the proposed interpretation is correct.
    """
    sources = source_map(batch)
    result = {key: [] for key in EMPTY if key != "batches_processed"}
    for fact in response.facts:
        record = fact.model_dump()
        if anchored(fact.evidence_id, fact.quote, sources):
            result["facts"].append(
                {
                    **record,
                    "page": sources[fact.evidence_id]["page"],
                    "validation": "exact source anchor matched; interpretation not independently verified",
                }
            )
        else:
            result["rejected"].append(record)
    return result
