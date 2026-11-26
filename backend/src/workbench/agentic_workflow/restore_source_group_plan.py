"""Check that a saved analysis plan still contains the manual text it should cover.

A long AI request may be divided into smaller requests so the answers fit. Before
continuing that saved work, these checks ensure that the smaller pieces have not
lost or invented text. A damaged plan is rejected rather than counted as finished."""

import json

from workbench.job_storage import job_files_and_audit_log as storage
from workbench.model_access.model_requests_and_responses import ModelError


def coverage(batches):
    """Merge overlapping source windows so two task plans can be compared fairly.

    Args:
        batches: Lists of source records with original IDs, pages and optional offsets.
    Returns:
        Original text ranges grouped by source ID/page/type. Raises ModelError when
        two overlapping windows disagree; overlap does not duplicate the text.
    """
    grouped = {}
    for batch in batches:
        for item in batch:
            key = (item["id"], item["page"], item["label"])
            grouped.setdefault(key, []).append(
                (item.get("source_offset", 0), item["text"])
            )
    result = {}
    for key, windows in grouped.items():
        merged = []
        for start, text in sorted(windows):
            if not merged or start > merged[-1][0] + len(merged[-1][1]):
                merged.append((start, text))
                continue
            previous_start, previous = merged[-1]
            offset = start - previous_start
            overlap = min(len(text), len(previous) - offset)
            if previous[offset : offset + overlap] != text[:overlap]:
                raise ModelError("Saved source windows disagree in their overlap")
            if offset + len(text) > len(previous):
                merged[-1] = (previous_start, previous + text[overlap:])
        result[key] = merged
    return result


def load_plan(path, fingerprint, batches, cap, fraction):
    """Create a stage plan or verify that a saved plan still covers the same request.

    Args:
        path: Private stage checkpoint path.
        fingerprint: Hash of original prompts, model, schema and output allowance.
        batches: Original source groups supplied by this task.
        cap: Current task's output-token allowance.
        fraction: Fraction used to calculate the allowance, saved for inspection.
    Returns:
        Mutable saved plan. Changed instructions, missing text or altered source
        raises ModelError instead of spending again. Completion may be out of order
        because independent source groups run concurrently.
        Only an exact current plan is accepted; completed responses are revalidated.
    """
    if not path.exists():
        saved = {
            "input_hash": fingerprint,
            "output_allowance": cap,
            "fraction": fraction,
            "complete": False,
            "tasks": [
                {"batch": batch, "depth": 0, "response": None} for batch in batches
            ],
        }
        storage.save(path, saved)
        return saved
    saved = json.loads(path.read_text())
    if saved["input_hash"] != fingerprint:
        raise ModelError("Saved task inputs changed; refusing to reuse different work")
    if coverage([task["batch"] for task in saved["tasks"]]) != coverage(batches):
        raise ModelError("Saved task source coverage differs from its original input")
    return saved
