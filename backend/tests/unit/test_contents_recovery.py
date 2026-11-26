"""Check that the manual’s table of contents remains searchable and links only to
verified PDF pages. Different printed page numbers and uncertain title matches
must not create guessed navigation targets."""

from types import SimpleNamespace
from workbench.pdf_processing.normalize_parsed_pdf import item_text
from workbench.pdf_processing.build_contents_page_links import contents_outline


def test_document_index_exports_table_text():
    """Exercise the special Docling label that previously produced an empty source.

    Args:
        None.
    Returns:
        None; proves contents use table export rather than the absent text attribute.
    """
    item = SimpleNamespace(export_to_markdown=lambda doc: "|3|Safety|")
    assert item_text(item, "document_index", object()) == "|3|Safety|"


def test_contents_checks_printed_offset_and_refuses_ambiguous_target():
    """Resolve physical pages by headings without guessing from printed page labels.

    Args:
        None.
    Returns:
        None; checks correct offset, nested titles, and refusal of ambiguous/missing
        destinations while leaving original table cells unchanged.
    """
    cells = []
    for row, (number, title) in enumerate(
        [(3, "SAFETY"), (4, "Before use"), (5, "Ambiguous"), (99, "Missing")]
    ):
        for col, text in enumerate([str(number), title]):
            cells.append(
                {"start_row_offset_idx": row, "start_col_offset_idx": col, "text": text}
            )
    table = {
        "id": "toc",
        "label": "document_index",
        "page": 2,
        "cells": {"table_cells": cells},
    }
    items = [
        {"label": "section_header", "text": title, "page": page}
        for title, page in [
            ("SAFETY", 5),
            ("Before use", 6),
            ("Ambiguous", 7),
            ("Ambiguous", 9),
        ]
    ]
    result = contents_outline([table], items)
    assert [(h["page"], h["level"]) for h in result] == [(5, 1), (6, 2)]
    assert len(table["cells"]["table_cells"]) == 8
