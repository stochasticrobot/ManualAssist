"""Recover the missing beginning or end of a sentence split between page columns.

PDF extraction can separate text that belongs together. These checks use the
original wording and page positions to include an unambiguous neighbouring
fragment. They leave uncertain layouts alone and never invent a continuation."""

import copy
import re

BODY_LABELS = {"text", "list_item"}


def body_box(source):
    """Read a single body-text rectangle without guessing missing geometry.

    Args:
        source: Original parsed source record with optional PDF provenance.
    Returns:
        Bottom-left rectangle and page, or None for pictures, headings, multi-box
        records, other coordinate systems or absent geometry. No layout is inferred.
    """
    if source.get("label") not in BODY_LABELS:
        return None
    spans = source.get("provenance", [])
    if len(spans) != 1:
        return None
    box = spans[0].get("bbox", {})
    if box.get("coord_origin") != "BOTTOMLEFT" or not all(
        k in box for k in ("l", "r", "t", "b")
    ):
        return None
    if box["r"] <= box["l"] or box["t"] <= box["b"]:
        return None
    return {**box, "page": spans[0]["page_no"]}


def preceding_column_fragment(source, items):
    """Find possible preceding context for a lowercase column-start fragment.

    Args:
        source: Selected original text beginning with a lowercase word of two or more
            letters; single-letter diagram/list markers are excluded conservatively.
        items: Complete original document, not just retrieved source snippets.
    Returns:
        One original body record at the bottom of the immediately preceding column,
        or None when layout is absent/ambiguous or punctuation suggests completion.
        This identifies nearby context only: it does not join sentences, assert a
        semantic relationship, create a quotation or establish source support.
    """
    if not re.match(r"^[a-z]{2,}\b", source["text"].lstrip()):
        return None
    box = body_box(source)
    if not box:
        return None
    page = [(s, b) for s in items if (b := body_box(s)) and b["page"] == box["page"]]
    same_column = [
        b
        for _, b in page
        if min(b["r"], box["r"]) - max(b["l"], box["l"])
        > 0.5 * min(b["r"] - b["l"], box["r"] - box["l"])
    ]
    if any(b["t"] > box["t"] + 1 for b in same_column):
        return None
    left = [(s, b) for s, b in page if b["r"] <= box["l"]]
    if not left:
        return None
    nearest = max(b["r"] for _, b in left)
    # Disjoint earlier columns are not the immediately preceding column.
    left = [(s, b) for s, b in left if b["r"] >= nearest - 0.5 * (box["r"] - box["l"])]
    bottom = min(b["b"] for _, b in left)
    candidates = [s for s, b in left if abs(b["b"] - bottom) <= 1]
    if len(candidates) != 1:
        return None
    candidate = candidates[0]
    if not candidate["text"].strip() or re.search(
        r"[.!?:;]$", candidate["text"].rstrip()
    ):
        return None
    return candidate


def retain_original_column_context(sources, document):
    """Add missing original context without changing selected evidence or references.

    Args:
        sources: Selected original records or exact source windows.
        document: Complete parsed document containing original text and geometry.
    Returns:
        Copied selected records with any missing boundary fragment immediately
        before its candidate continuation, or the following fragment after its beginning,
        plus a private selection audit. Existing
        IDs are not duplicated. Missing original IDs or altered text raise ValueError.
        Ambiguous layout adds nothing and never becomes evidence of absence.
    """
    originals = {s["id"]: s for s in document["items"]}
    if len(originals) != len(document["items"]):
        raise ValueError("Duplicate original source IDs")
    pairs = []
    for record in document["items"]:
        prior = preceding_column_fragment(record, document["items"])
        if prior:
            pairs.append((prior["id"], record["id"]))
    seen = {s["id"] for s in sources}
    output = []
    audit = []
    for source in sources:
        original = originals.get(source["id"])
        if not original or source["text"] not in original["text"]:
            raise ValueError("Selected source differs from original text or identity")
        complete = source["text"] == original["text"]
        previous = [a for a, b in pairs if b == source["id"]] if complete else []
        following = [b for a, b in pairs if a == source["id"]] if complete else []
        if len(previous) == 1 and previous[0] not in seen:
            prior = originals[previous[0]]
            output.append(copy.deepcopy(prior))
            seen.add(prior["id"])
            audit.append(
                {
                    "selected_source": source["id"],
                    "added_source": prior["id"],
                    "reason": "possible preceding-column sentence context; not a semantic join",
                }
            )
        output.append(copy.deepcopy(source))
        if len(following) == 1 and following[0] not in seen:
            continuation = originals[following[0]]
            output.append(copy.deepcopy(continuation))
            seen.add(continuation["id"])
            audit.append(
                {
                    "selected_source": source["id"],
                    "added_source": continuation["id"],
                    "reason": "possible following-column sentence context; not a semantic join",
                }
            )
    return output, audit
