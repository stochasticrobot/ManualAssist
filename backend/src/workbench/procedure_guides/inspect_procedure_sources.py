"""Let a guide-writing AI look up missing instructions in the original manual.

A prerequisite, warning or next step may be on another page. The AI can request a
text search, a passage with its neighbours, or a page read. This file returns a
limited amount of relevant text and records what was left out, rather than
pretending the AI has read everything. It does not modify the PDF."""

import json

from workbench.manual_analysis.select_uncertainty_review_sources import (
    search_parsed_document,
)

MAX_EVIDENCE_BYTES = 22000


def add_source_passages(evidence, items):
    """Add whole source items that fit, keeping previously inspected passages intact.

    Args:
        evidence: Mutable dictionary of already supplied original source records.
        items: Original records selected by a tool or initial procedure references.
    Returns:
        IDs that could not fit. No record is shortened, and no quoted text is joined
        across IDs. The caller must disclose excluded IDs as a coverage limitation.
    """
    omitted = []
    for item in items:
        if item["id"] in evidence:
            continue
        compact = {
            key: item[key]
            for key in (
                "id",
                "text",
                "page",
                "label",
                "section",
                "section_source_ids",
                "source_offset",
                "document_position",
            )
            if key in item
        }
        if (
            len(json.dumps([*evidence.values(), compact], ensure_ascii=False).encode())
            > MAX_EVIDENCE_BYTES
        ):
            omitted.append(item["id"])
        else:
            evidence[item["id"]] = compact
    return omitted


def inspect_procedure_sources(document, decision):
    """Execute the planner's selected source read without making another model call.

    Args:
        document: Original parsed manual with ordered text and table items.
        decision: Validated read_source, read_page or search_parsed_document choice.
    Returns:
        Selected original items and a plain description of the search/read limits.
        Unknown IDs, invalid pages and empty searches return no items, not evidence
        that the manual lacks the information. Source reads include two neighbours.
    """
    items = document["items"]
    if decision.action == "read_source":
        position = next(
            (n for n, item in enumerate(items) if item["id"] == decision.evidence_id),
            None,
        )
        return (
            items[max(0, position - 2) : position + 3] if position is not None else []
        ), "Requested source and up to two neighbours on each side."
    if decision.action == "read_page":
        return [
            item for item in items if item["page"] == decision.page
        ], "Original text and table records on the requested physical PDF page."
    return search_parsed_document(
        document, [decision.query]
    ), "Bounded lexical search; a missing match does not prove absence."


def select_planning_evidence(evidence, preferred_ids=()):
    """Choose a bounded reading window while keeping the full inspected archive.

    Args:
        evidence: All original passages previously returned to this procedure.
        preferred_ids: Newly requested IDs or draft citations to show first.
    Returns:
        Selected records and omitted IDs. New passages can displace older context
        instead of being permanently refused once the first window fills. No saved
        source is modified; an individually oversized passage remains disclosed.
    """
    order = list(dict.fromkeys([*preferred_ids, *reversed(evidence)]))
    selected = {}
    omitted = add_source_passages(
        selected, [evidence[i] for i in order if i in evidence]
    )
    return list(selected.values()), omitted
