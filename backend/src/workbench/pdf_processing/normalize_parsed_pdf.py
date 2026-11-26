"""Organize extracted PDF text, tables and pictures into page-linked records.

Later searches, citations and the manual viewer need consistent references and
reading order, even when the PDF reader returns different types of content. This
file preserves the original page locations and builds navigation headings; it does
not ask an AI to interpret the manual."""

from workbench.pdf_processing.build_contents_page_links import contents_outline

TABLE_LABELS = ("table", "document_index")


def item_text(item, label, document):
    """Choose a readable representation without discarding original table cells.

    Args:
        item: Docling text, table or picture item.
        label: Normalized item type.
        document: Docling document required for table/caption export.
    Returns:
        Extracted text, Markdown table, or picture caption. A missing caption is
        explicitly labelled; it is not replaced by a model-generated description.
    """
    if label in TABLE_LABELS:
        return item.export_to_markdown(doc=document)
    if label == "picture":
        return item.caption_text(document) or "[Figure without an extracted caption]"
    return getattr(item, "text", "")


def normalize(document):
    """Preserve source order, physical pages, geometry and inferred section hierarchy.

    Args:
        document: Converted Docling document with item provenance and page metadata.
    Returns:
        Mapping of items, outline, tables and figures. Contents tables retain text
        and cells; checked contents links replace the heading-only outline when found.
        The original heading outline remains available as inferred_outline.
        Items without page provenance
        are excluded; raises ValueError if nothing source-linked remains.
    """
    result = {"items": [], "outline": [], "tables": [], "figures": []}
    headings = []
    for item, depth in document.iterate_items():
        if not getattr(item, "prov", []):
            continue
        label = str(getattr(item, "label", "")).split(".")[-1]
        text = item_text(item, label, document)
        page = item.prov[0].page_no
        if label in ("section_header", "title"):
            level = getattr(item, "level", None) or (
                1 if label == "title" else max(1, depth)
            )
            headings = headings[: max(0, level - 1)] + [text]
            result["outline"].append(
                {
                    "title": text,
                    "level": level,
                    "page": page,
                    "basis": "Docling layout/heading inference; may need review",
                }
            )
        entry = {
            "id": f"e{len(result['items']) + 1:05}",
            "label": label,
            "text": text,
            "page": page,
            "section": list(headings),
            "provenance": [p.model_dump(mode="json") for p in item.prov],
            "confidence": {
                "status": "unreviewed",
                "basis": "Local layout/OCR extraction; not calibrated factual confidence",
            },
        }
        result["items"].append(entry)
        if label in TABLE_LABELS:
            result["tables"].append(
                {**entry, "cells": item.data.model_dump(mode="json")}
            )
        if label == "picture":
            result["figures"].append(entry)
    if not result["items"]:
        raise ValueError("No source-linked content was extracted")
    result["inferred_outline"] = list(result["outline"])
    checked = contents_outline(result["tables"], result["items"])
    if checked:
        result["outline"] = checked
    return result
