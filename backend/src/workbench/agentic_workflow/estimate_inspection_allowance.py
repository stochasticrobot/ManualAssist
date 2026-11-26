"""Calculate a stopping limit for the retired AI-led preview of a manual.

The calculation counts pages, tables and substantial pictures to decide how many
closer looks that preview could request. It prevents the old preview from running
indefinitely; it does not measure understanding or guarantee complete coverage.
New manual analyses do not use this preliminary preview."""

import math


def inspection_allowance(document):
    """Calculate a reproducible, uncalibrated inspection-action allowance.

    Args:
        document: Normalized PDF items, physical page count, tables and figures.
    Returns:
        Versioned formula, measured page lists, word counts and additive terms.
        Words are whitespace-separated parsed tokens, excluding picture placeholders.
        Sparse visual pages have fewer than 40 words and a figure box of at least
        20,000 square PDF points. Missing geometry contributes no sparse-page claim.
        Page-specific parser warnings are unavailable and are explicitly disclosed.
        Does not mutate the document, invoke OCR or make model calls.
    """
    pages = document["pages"]
    words = {page: 0 for page in range(1, pages + 1)}
    for item in document["items"]:
        if item["label"] != "picture" and item["page"] in words:
            words[item["page"]] += len(item["text"].split())
    figure_pages = {f["page"] for f in document["figures"] if f["page"] in words}
    substantial = set()
    for figure in document["figures"]:
        for location in figure.get("provenance", []):
            box = location.get("bbox", {})
            if all(
                isinstance(box.get(key), (int, float)) for key in ("l", "r", "t", "b")
            ):
                area = abs(box["r"] - box["l"]) * abs(box["t"] - box["b"])
                page = location.get("page_no", figure["page"])
                if area >= 20_000 and page in words:
                    substantial.add(page)
    dense = [page for page, count in words.items() if count > 600]
    sparse = sorted(page for page in substantial if words[page] < 40)
    terms = {
        "base": 2,
        "pages": math.ceil(pages / 10),
        "tables": math.ceil(len(document["tables"]) / 5),
        "figure_pages": math.ceil(len(figure_pages) / 5),
        "dense_pages": math.ceil(len(dense) / 10),
        "possible_extraction_problem_pages": math.ceil(len(sparse) / 3),
    }
    return {
        "version": 1,
        "action_allowance": sum(terms.values()),
        "terms": terms,
        "counts": {
            "pages": pages,
            "tables": len(document["tables"]),
            "figure_pages": len(figure_pages),
            "dense_pages": len(dense),
            "possible_extraction_problem_pages": len(sparse),
        },
        "figure_pages": sorted(figure_pages),
        "dense_pages": dense,
        "possible_extraction_problem_pages": sparse,
        "words_by_page": {str(page): count for page, count in words.items()},
        "warning_page_coverage": "unavailable: page-specific parser/OCR warnings are not retained",
        "basis": "Uncalibrated heuristic; sparse substantial-figure pages are a proxy, not confirmed extraction failures.",
    }
