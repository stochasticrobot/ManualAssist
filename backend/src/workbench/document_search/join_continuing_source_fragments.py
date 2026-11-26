"""Keep sentences split by PDF extraction understandable when they are searched.

A useful instruction may continue in a neighbouring text fragment. These helpers
combine only supported continuations while retaining the original pieces and page
references. Ambiguous fragments stay separate rather than being turned into a
sentence the manual never actually contained."""

import re


def continuation_reason(left: dict, right: dict) -> str | None:
    """Recognize adjacent prose continuations without merging other structures.

    Args:
        left: Earlier original parser item in reading order.
        right: Immediately following original item with layout provenance.
    Returns:
        Layout reason, or None for uncertain boundaries. Does not mutate sources.
    """
    prose = {"text", "paragraph", "list_item"}
    a, b = left["text"].strip(), right["text"].strip()
    if (
        left["label"] not in prose
        or right["label"] not in prose
        or left["page"] != right["page"]
        or left["section"] != right["section"]
        or not a
        or not b
        or not b[0].islower()
        or len(re.findall(r"[A-Za-z]+", a)) < 3
        or re.match(r"^[a-z][.)]?\s+(?:[A-Z]|\d)", b)
        or re.search(r'[.!?:;]["\u201d\')\]]*$', a)
    ):
        return None
    lp, rp = left.get("provenance", []), right.get("provenance", [])
    if len(lp) != 1 or len(rp) != 1:
        return None
    x, y = lp[0].get("bbox", {}), rp[0].get("bbox", {})
    if not all(
        k in box for box in (x, y) for k in ("l", "r", "t", "b", "coord_origin")
    ):
        return None
    if x["coord_origin"] != y["coord_origin"] or x["coord_origin"] not in {
        "BOTTOMLEFT",
        "TOPLEFT",
    }:
        return None
    direction = -1 if x["coord_origin"] == "BOTTOMLEFT" else 1
    gap = direction * (y["t"] - x["b"])
    height = min(abs(x["t"] - x["b"]), abs(y["t"] - y["b"]))
    overlap = min(x["r"], y["r"]) - max(x["l"], y["l"])
    if overlap > 0 and 0 <= gap <= min(24, height):
        return "adjacent_lines"
    if (
        y["l"] > x["r"]
        and direction * (y["t"] - x["t"]) < 0
        and re.search(
            r"\b(by|the|a|an|to|of|with|and|or|into|from)\s*$", a, re.IGNORECASE
        )
    ):
        return "column_continuation"
    return None


def source_groups(document: dict) -> list[list[dict]]:
    """Group supported consecutive fragments while retaining original items.

    Args:
        document: Normalized document in parser reading order.
    Returns:
        Groups of at most eight original items. Empty and non-prose items remain
        barriers. Does not edit parser data or bridge pages or section changes.
    """
    groups = []
    for item in document["items"]:
        if groups and len(groups[-1]) < 8 and continuation_reason(groups[-1][-1], item):
            groups[-1].append(item)
        else:
            groups.append([item])
    return groups


def prepare_source_chunks(document: dict) -> list[dict]:
    """Build embedding windows with all original source references and offsets.

    Args:
        document: Normalized items with IDs, pages, sections and layout.
    Returns:
        Chunk manifest; joins insert only newlines. Source spans refer to the
        complete group, with window_start locating each 1200-character window.
        Long groups use 150-character overlap and retrieve as complete groups.
    """
    chunks = []
    for group in source_groups(document):
        searchable = [i for i in group if i["text"].strip() and i["label"] != "picture"]
        if not searchable:
            continue
        text, spans = "", []
        for item in searchable:
            if text:
                text += "\n"
            start = len(text)
            text += item["text"]
            spans.append(
                {
                    "evidence_id": item["id"],
                    "page": item["page"],
                    "start": start,
                    "end": len(text),
                }
            )
        first = searchable[0]
        for start in range(0, len(text), 1050):
            chunks.append(
                {
                    "id": f"{first['id']}_{start}",
                    "text": text[start : start + 1200],
                    "evidence_id": first["id"],
                    "evidence_ids": [i["id"] for i in searchable],
                    "page": first["page"],
                    "section": " > ".join(first["section"]),
                    "label": first["label"],
                    "source_spans": spans,
                    "window_start": start,
                    "boundary_version": 2,
                }
            )
    return chunks
