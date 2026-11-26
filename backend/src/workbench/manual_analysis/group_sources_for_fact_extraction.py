"""Divide manual text into portions small enough to receive detailed fact lists.

A short page of warnings can require a much longer answer. These helpers consider
both text size and item count when planning requests, leaving room for the reply.
The estimate is only a planning aid; a cut-short answer still needs smaller work."""

import json

from workbench.manual_analysis.check_source_quotations import evidence_payload


def build_fact_batches(items, allowance=6000, planning_version=2):
    """Group source text using a conservative expected-output allowance.

    Args:
        items: Original source items or bounded windows in the current task.
        allowance: This model's output-token allowance for a fact request.
        planning_version: Two uses larger groups; one reproduces a saved older plan
            so Resume never changes the inputs of already dispatched requests.
    Returns:
        Ordered batches containing all non-picture source text. Large items split
        into overlapping windows; metadata retains original IDs, pages and offsets.
    """
    source_limit = (
        max(512, min(3000, allowance // 2))
        if planning_version == 1
        else max(512, min(6000, int(allowance * 0.9)))
    )
    window = (
        max(64, min(650, source_limit // 4 - 64))
        if planning_version == 1
        else max(64, min(1400, source_limit // 2 - 128))
    )
    overlap = min(64, window // 4)
    fragments = []
    for item in items:
        if not item["text"].strip() or item["label"] == "picture":
            continue
        if len(evidence_payload([item]).encode()) > source_limit:
            for offset in range(0, len(item["text"]), window - overlap):
                fragments.append(
                    {
                        **item,
                        "text": item["text"][offset : offset + window],
                        "source_offset": item.get("source_offset", 0) + offset,
                    }
                )
        else:
            fragments.append(item)
    batches, current = [], []
    for item in fragments:
        proposed = current + [item]
        size = len(evidence_payload(proposed).encode())
        expected_output = (
            size / 2 + 120 * len(proposed)
            if planning_version == 1
            else size / 3 + 80 * len(proposed)
        )
        if current and (
            (
                planning_version > 1
                and current[-1].get("section") != item.get("section")
                and len(evidence_payload(current).encode()) >= source_limit // 2
            )
            or size > source_limit
            or len(proposed) > (16 if planning_version == 1 else 32)
            or expected_output > allowance * (0.65 if planning_version == 1 else 0.7)
        ):
            batches.append(current)
            current = []
        current.append(item)
    if current:
        batches.append(current)
    return batches


def saved_grouping_version(path):
    """Keep the source grouping chosen when a stage first started.

    Args:
        path: Source-group stage checkpoint path, which may not exist yet.
    Returns:
        Saved planning version, or two for a fresh stage. Pre-versioned plans use
        version one, preserving their exact prompts and already-completed receipts.
    """
    return (
        json.loads(path.read_text()).get("planning_version", 1) if path.exists() else 2
    )
