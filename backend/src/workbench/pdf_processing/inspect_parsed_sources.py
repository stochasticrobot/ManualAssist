"""Carry out the closer looks requested by the retired manual-preview process.

A closer look can read a page, search extracted text, inspect a table or ask an
image-capable AI about a specific page. Returned text is limited and any
shortening is disclosed so a small preview is not mistaken for the whole manual.
New analyses no longer run this preliminary process; direct image inspection can
still make a paid model request if this retained code is explicitly called."""

from workbench.job_storage import job_files_and_audit_log as storage
from workbench.model_access.model_requests_and_responses import Image
from workbench.pdf_processing.validate_and_render_pdf import page_image


def preview(items, limit=4000):
    """Bound inspection context while disclosing what was shortened.

    Args:
        items: Selected source records; originals remain unchanged on disk.
        limit: Maximum aggregate source-text UTF-8 bytes in this inspection preview.
    Returns:
        Original structured source windows plus counts and a truncation flag. This preview
        does not replace complete extraction, which later processes all source text.
    """
    chosen, remaining, truncated = [], limit, False
    for item in items:
        if remaining <= 0:
            truncated = True
            break
        text = item["text"].encode("utf-8")[:remaining].decode("utf-8", errors="ignore")
        truncated |= len(text) < len(item["text"])
        chosen.append({**item, "text": text})
        remaining -= len(text.encode("utf-8"))
    return {
        "source_records": chosen,
        "returned": len(chosen),
        "total_items": len(items),
        "preview_truncated": truncated,
    }


def inspect(job_id, decision, document, run, vision_count):
    """Execute one selected inspection and disclose exactly which evidence it used.

    Args:
        job_id: Job owning the original PDF and optional rendered page image.
        decision: Validated agent action with its stated reason and source target.
        document: Parsed items, tables and page count.
        run: Model-call owner used only for an explicit image inspection.
        vision_count: Completed image inspections in the current decision sequence.
    Returns:
        Tool result dictionary. Invalid targets return an error observation; vision
        failures propagate. Text previews are bounded and marked when shortened.
    """
    if (
        decision.action in ("read_page", "inspect_image")
        and not 1 <= decision.page <= document["pages"]
    ):
        return {"error": "Page outside source document"}
    if decision.action == "read_page":
        return preview([i for i in document["items"] if i["page"] == decision.page])
    if decision.action == "search_manual":
        matches = [
            i
            for i in document["items"]
            if decision.query.strip() and decision.query.lower() in i["text"].lower()
        ]
        return preview(matches)
    if decision.action == "inspect_table":
        return preview(
            [i for i in document["tables"] if i["id"] == decision.evidence_id]
        )
    if decision.action == "inspect_image":
        if vision_count >= 2:
            return {"error": "Vision inspection allowance exhausted"}
        path = storage.job_dir(job_id)
        image = page_image(path / "source.pdf", decision.page)
        (path / f"vision-page-{decision.page}.png").write_bytes(image)
        prompt = (
            "Answer this visual question about the manual page in at most 180 words: "
            + decision.reason
            + "\nMention only relevant visible labels and relationships. State unreadable text "
            "and uncertainty. Do not infer hidden wiring or parts."
        )
        description = run.call("vision", prompt, images=(Image(image),), cap=1200)
        return {
            "page": decision.page,
            "observation": description,
            "status": "unverified visual interpretation",
        }
    return {"error": "Unsupported inspection action"}
