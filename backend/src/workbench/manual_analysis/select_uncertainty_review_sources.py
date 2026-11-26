"""Find manual passages that may answer a reported ambiguity or contradiction.

Nearby instructions and matching text elsewhere can supply a missing condition or
explanation. These helpers choose those passages and keep their original
references; they do not decide whether a question has been resolved."""

import re

from workbench.manual_analysis.group_sources_for_uncertainty_review import build_batches


def nearby_sources(document, evidence_ids):
    """Include cited items and two reading-order neighbours on either side.

    Args:
        document: Complete parsed document in reading order.
        evidence_ids: Original source IDs to inspect first.
    Returns:
        Ordered original text/table items, without rewriting or merging sources.
        Neighbours can cross a page boundary. Conservative PDF-column context
        recovery also retains separate original sentence fragments when layout
        supports them; it does not infer a semantic join or rewrite quotations.
    """
    items = document["items"]
    selected = set()
    for position, item in enumerate(items):
        if item["id"] in evidence_ids:
            selected.update(range(max(0, position - 2), min(len(items), position + 3)))
    nearby = [
        item
        for n, item in enumerate(items)
        if n in selected and item["label"] != "picture" and item["text"].strip()
    ]
    from workbench.document_search.retain_original_column_context import retain_original_column_context

    # Reading-order neighbors alone can miss a sentence across PDF columns.
    # Add only original context; do not join quotations or assert source support.
    return retain_original_column_context(nearby, document)[0]



def search_parsed_document(document, queries):
    """Rank literal phrases and shared words to find useful review passages locally.

    Args:
        document: Parsed PDF text, OCR and table text, not images or external sources.
        queries: At most three short natural-language search phrases per finding.
    Returns:
        Up to six matching original items in score order. Matching is lexical,
        not semantic; no match never proves information is absent. No model calls.
    """
    scored = []
    for position, item in enumerate(document["items"]):
        if item["label"] == "picture" or not item["text"].strip():
            continue
        text = " ".join(item["text"].casefold().split())
        words = set(re.findall(r"\w+", text))
        score = 0
        for query in queries:
            phrase = " ".join(query.casefold().split())
            terms = set(re.findall(r"\w+", phrase)) - {
                "the",
                "a",
                "an",
                "is",
                "of",
                "to",
                "and",
                "in",
                "for",
            }
            if not terms:
                continue
            overlap = len(terms & words) / len(terms)
            score = max(
                score, (2 if phrase in text else 0) + (overlap if overlap >= 0.5 else 0)
            )
        if score:
            scored.append((-score, position, item))
    return [item for _, _, item in sorted(scored, key=lambda row: row[:2])[:6]]


def review_source_batches(document, group, phase, queries=None):
    """Create bounded local or search-result batches for the assigned findings.

    Args:
        document: Original parsed source document.
        group: Index/finding pairs sharing a request.
        phase: local or targeted source selection.
        queries: Per-index model-requested search phrases for the targeted phase.
    Returns:
        Complete bounded batches of selected sources. Search results include nearby
        context; broader coverage is a separate explicit phase, never implied here.
    """
    ids = set()
    for index, finding in group:
        if phase == "local":
            ids.update(finding["evidence_ids"])
        else:
            ids.update(
                item["id"]
                for item in search_parsed_document(
                    document, (queries or {}).get(index, [])
                )
            )
    batches = build_batches(nearby_sources(document, ids))
    # Put cited/search-hit passages before batches containing only neighbours.
    # Preserve original reading order within every batch.
    return sorted(batches, key=lambda batch: -sum(item["id"] in ids for item in batch))
