"""Make the manual's table of contents open the correct pages in the PDF viewer.

Printed page numbers may differ from the file's page positions. A contents entry
becomes a navigation link only when its title can be matched to a source page.
Unmatched entries remain readable text rather than pointing to a guessed page."""

import re


def title_key(text):
    """Compare headings despite case, punctuation and leading printed page numbers.

    Args:
        text: A contents title or extracted heading.
    Returns:
        Lowercase words without punctuation or a leading standalone page number.
        This is used for navigation matching only, never for validating quotations.
    """
    return re.sub(r"[^\w]+", " ", re.sub(r"^\s*\d+\s+", "", text)).strip().casefold()


def contents_outline(tables, items):
    """Build checked outline links from two-column contents tables when available.

    Args:
        tables: Extracted table records including original structured cells.
        items: All extracted source items with physical page numbers.
    Returns:
        Outline entries with checked physical targets and contents provenance.
        Unrecognized layouts or ambiguous targets are skipped, leaving the original
        table intact. Uppercase titles start top-level sections; other titles nest
        beneath them. That hierarchy is explicitly labelled as inferred.
    """
    headings = {}
    for item in items:
        if item["label"] in ("title", "section_header"):
            headings.setdefault(title_key(item["text"]), set()).add(item["page"])
    outline = []
    for table in tables:
        if table["label"] != "document_index":
            continue
        rows = {}
        for cell in table["cells"]["table_cells"]:
            rows.setdefault(cell["start_row_offset_idx"], []).append(cell)
        parent = False
        for _, cells in sorted(rows.items()):
            texts = [
                c["text"].strip()
                for c in sorted(cells, key=lambda c: c["start_col_offset_idx"])
            ]
            if len(texts) != 2:
                continue
            numbers = [text for text in texts if text.isdigit()]
            if len(numbers) != 1:
                continue
            printed = int(numbers[0])
            title = texts[1] if texts[0].isdigit() else texts[0]
            candidates = headings.get(title_key(title), set())
            target = (
                printed
                if printed in candidates
                else next(iter(candidates))
                if len(candidates) == 1
                else None
            )
            if target is None:
                continue
            level = 1 if title.isupper() or not parent else 2
            parent = True
            outline.append(
                {
                    "title": title,
                    "level": level,
                    "page": target,
                    "printed_page": printed,
                    "contents_page": table["page"],
                    "evidence_id": table["id"],
                    "basis": "Manufacturer contents; target checked against extracted headings; hierarchy inferred from capitalization",
                }
            )
    return outline
