"""Check that a claimed quotation really occurs in the supplied manual text.

Generated answers need traceable support, not plausible-looking quotations. These
helpers match text to its original passage while tolerating harmless spacing
differences. A matching quote does not prove that an AI's interpretation is right."""

import json


def normalized(text: str) -> str:
    """Normalize whitespace only for checking a quote against extracted evidence.

    Args:
        text: Source or proposed quote text.
    Returns:
        Whitespace-collapsed string, preserving words, numbers and punctuation.
    """
    return " ".join(text.split())


def anchored(evidence_id: str, quote: str, sources: dict) -> bool:
    """Check that a nontrivial quote occurs in the cited source item.

    Args:
        evidence_id: Proposed source ID.
        quote: Proposed exact quotation.
        sources: Available evidence records keyed by ID.
    Returns:
        True for a complete nonempty source, including short directives, or a
        quotation of at least eight characters contained in one segment; never joins
        separate windows to manufacture an anchor. Does not prove interpretation.
    """
    if evidence_id not in sources or not normalized(quote):
        return False
    source = sources[evidence_id]
    segments = source.get("segments", [source["text"]])
    return any(
        normalized(quote) == normalized(segment)
        or (len(normalized(quote)) >= 8 and normalized(quote) in normalized(segment))
        for segment in segments
    )


def evidence_payload(items: list[dict]) -> str:
    """Serialize source text and minimal metadata without hiding provenance.

    Args:
        items: Source items chosen by a tool or extraction batch.
    Returns:
        JSON string containing IDs, physical page numbers, labels and full text.
    """
    return json.dumps(
        [{k: i[k] for k in ("id", "page", "label", "text")} for i in items],
        ensure_ascii=False,
    )


def source_map(items):
    """Index repeated source IDs without inventing text between overlapping windows.

    Args:
        items: Original records or source windows that may share the same item ID.
    Returns:
        ID-keyed records with separate text segments for quote matching. Page metadata
        stays original; callers must not concatenate segments into synthetic evidence.
    """
    sources = {}
    for item in items:
        source = sources.setdefault(item["id"], {**item, "segments": []})
        source["segments"].append(item["text"])
    return sources
