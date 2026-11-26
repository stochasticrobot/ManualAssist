"""Prepare selected original manual pictures for the Results pages.

The application finds overview figures, crops them from the PDF and checks whether
they are suitable as reference images. Their captions and links keep their
original page context. This can request an AI image assessment, but it never
generates a replacement diagram or treats the picture as proof that a procedure is
correct."""

import hashlib
import io
import json
import re
from pathlib import Path
import pypdfium2 as pdfium
from workbench.pdf_processing.validate_and_render_pdf import PDF_LOCK
from workbench.job_storage import job_files_and_audit_log as storage
from workbench.model_access.model_requests_and_responses import (
    Image,
    InvalidModelResponseError,
)
from workbench.result_illustrations.assess_static_illustration import (
    VisualAssessment,
    PROMPT,
    decide,
)

VERSION = "static-reference-v2"
MAX_FIGURES = 12
OVERVIEW = re.compile(
    r"^(?:(?:product |component )?overview|(?:front|rear|back|interior|exterior) view|accessories|parts (?:not provided|provided|supplied)|tools (?:needed|required))$",
    re.I,
)


def content_hash(value):
    """Identify exact source data or bytes for cache invalidation.

    Args:
        value: Raw bytes or JSON-serializable source data.
    Returns:
        SHA-256 digest, stable for equivalent JSON key order.
    """
    raw = (
        value
        if isinstance(value, bytes)
        else json.dumps(value, sort_keys=True).encode()
    )
    return hashlib.sha256(raw).hexdigest()


def bounds(item):
    """Normalize a single original PDF rectangle without guessing coordinate origins.

    Args:
        item: Parsed source record with exactly one provenance rectangle.
    Returns:
        Left, bottom, right, top coordinates, or None for unsupported geometry.
        Current placement intentionally supports BOTTOMLEFT records only.
    """
    records = item.get("provenance", [])
    if len(records) != 1:
        return None
    box = records[0].get("bbox", {})
    if box.get("coord_origin") != "BOTTOMLEFT":
        return None
    try:
        result = tuple(float(box[k]) for k in ["l", "b", "r", "t"])
        return result if result[0] < result[2] and result[1] < result[3] else None
    except (KeyError, TypeError, ValueError):
        return None


def source_candidates(document):
    """Locate overview figures with spatially compatible headings and references.

    Args:
        document: Existing parsed document, with original items and PDF rectangles.
    Returns:
        Deterministic candidates, each tied to the nearest heading above it in its
        column and the text in that heading's same-page region. Unknown headings,
        ambiguous overlaps and unsupported geometry exclude; no model matching is used.
        These source-region links mean contextual relevance, not depicted action.
    """
    items = document["items"]
    results = []
    for figure in items:
        if figure.get("label") != "picture" or not re.fullmatch(
            r"[A-Za-z0-9_-]+", figure["id"]
        ):
            continue
        fb = bounds(figure)
        if not fb:
            continue
        left, bottom, right, top = fb
        headings = []
        for h in items:
            hb = bounds(h)
            if (
                h.get("page") != figure["page"]
                or h.get("label") != "section_header"
                or not hb
            ):
                continue
            if hb[1] >= top - 3 and abs(hb[0] - left) < max(70, (right - left) * 0.4):
                headings.append(h)
        if not headings:
            continue
        headings.sort(key=lambda h: bounds(h)[1] - top)
        if (
            len(headings) > 1
            and abs(bounds(headings[0])[1] - bounds(headings[1])[1]) < 1
        ):
            continue
        heading = headings[0]
        title = heading.get("text", "").strip()
        if not OVERVIEW.fullmatch(title):
            continue
        hb = bounds(heading)
        # A subsequent same-column heading bounds the region; adjacent columns do not.
        below = [
            bounds(h)[3]
            for h in items
            if h.get("page") == figure["page"]
            and h.get("label") == "section_header"
            and bounds(h)
            and bounds(h)[3] < bottom
            and abs(bounds(h)[0] - hb[0]) < 35
        ]
        floor = max(below, default=0)
        refs = [figure["id"], heading["id"]]
        for item in items:
            b = bounds(item)
            if (
                item.get("page") != figure["page"]
                or not b
                or item.get("label") in ["picture", "section_header"]
            ):
                continue
            # Whole text rectangle must lie within the figure column (with modest
            # label margins); never attach a reference from the neighbouring column.
            if (
                b[0] >= min(left, hb[0]) - 12
                and b[2] <= max(right, hb[2]) + 18
                and b[1] >= floor
                and b[3] <= hb[1] + 3
            ):
                refs.append(item["id"])
        results.append(
            {
                "id": figure["id"],
                "page": figure["page"],
                "heading": title,
                "heading_id": heading["id"],
                "source_ids": refs,
                "original_bbox": figure["provenance"][0]["bbox"],
                "source_record": figure,
            }
        )
    return results


def crop_figure(pdf_path, candidate):
    """Render an original figure with a small margin, preserving visible markings.

    Args:
        pdf_path: Original source PDF, never rewritten.
        candidate: Code-selected record with original page and PDF coordinates.
    Returns:
        PNG bytes. Invalid/out-of-page geometry raises ValueError; PDF access is locked
        to avoid concurrent PDFium operations. No extraction or image generation.
    """
    with PDF_LOCK, pdfium.PdfDocument(pdf_path) as pdf:
        page = pdf[candidate["page"] - 1]
        width, height = page.get_size()
        left, bottom, right, top = bounds(candidate["source_record"])
        if not (0 <= left < right <= width and 0 <= bottom < top <= height):
            raise ValueError("Invalid figure bounds")
        bitmap = page.render(scale=2)
        raster = bitmap.to_pil().copy()
        bitmap.close()
        page.close()
    sx, sy = raster.width / width, raster.height / height
    crop = raster.crop(
        (
            max(0, int((left - 8) * sx)),
            max(0, int((height - top - 8) * sy)),
            min(raster.width, int((right + 8) * sx + 1)),
            min(raster.height, int((height - bottom + 8) * sy + 1)),
        )
    )
    output = io.BytesIO()
    crop.save(output, format="PNG")
    return output.getvalue()


def prepare(job_id, document, run):
    """Assess at most twelve source-selected figures with audited, replayable calls.

    Args:
        job_id: Existing job, or isolated test job, with original source.pdf.
        document: Parsed original source records, not generated guide text.
        run: Shared budgeted Run with separately configured image_captioning role.
    Returns:
        Persisted illustration manifest. Records all candidates and excluded/unprocessed
        counts, original hashes, source links, model identity and decisions. Cached
        compatible completed assessments avoid calls; malformed output excludes.
        Provider/budget failures propagate after marking incomplete preparation, while
        prior accepted assets remain readable. Never rewrites guides or source records.
    """
    path = storage.job_dir(job_id)
    folder = path / "illustrations"
    folder.mkdir(exist_ok=True)
    candidates = source_candidates(document)
    identity = run.service.identity("image_captioning") if candidates else None
    key = content_hash(
        {
            "version": VERSION,
            "document": document,
            "pdf": content_hash((path / "source.pdf").read_bytes()),
            "model": identity,
            "prompt": PROMPT,
            "schema": VisualAssessment.model_json_schema(),
        }
    )
    manifest_path = folder / "manifest.json"
    old = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    records = old.get("records", []) if old.get("key") == key else []
    records = [
        r
        for r in records
        if r.get("status") == "excluded"
        or (
            (folder / (r["id"] + ".png")).is_file()
            and content_hash((folder / (r["id"] + ".png")).read_bytes())
            == r.get("image_sha256")
        )
    ]
    state = {
        "version": VERSION,
        "key": key,
        "document_hash": content_hash(document),
        "source_pdf_hash": content_hash((path / "source.pdf").read_bytes()),
        "model": identity,
        "candidate_count": len(candidates),
        "limit": MAX_FIGURES,
        "records": records,
        "status": "preparing",
        "unprocessed": len(candidates) - len(records),
    }
    storage.save(manifest_path, state)
    try:
        for c in candidates[:MAX_FIGURES]:
            if any(r["id"] == c["id"] for r in records):
                continue
            image = crop_figure(path / "source.pdf", c)
            try:
                a = run.call(
                    "image_captioning",
                    PROMPT,
                    VisualAssessment,
                    images=[Image(image)],
                    cap=600,
                    correct=False,
                )
            except InvalidModelResponseError:
                a = None
            result = decide(
                a,
                use="general_overview",
                source_role="overview",
                source_verified=True,
                precision_required=False,
            )
            record = {
                **c,
                "image_sha256": content_hash(image),
                "assessment": a.model_dump() if a else None,
                "decision": result,
                "status": "accepted" if result["eligible"] else "excluded",
            }
            if result["eligible"]:
                (folder / (c["id"] + ".png")).write_bytes(image)
            records.append(record)
            state["unprocessed"] = len(candidates) - len(records)
            storage.save(manifest_path, state)
        state["status"] = "complete" if not state["unprocessed"] else "limited"
    except Exception:
        state["status"] = "incomplete"
        storage.save(manifest_path, state)
        raise
    storage.save(manifest_path, state)
    return state


def public_manifest(job_id, document):
    """Expose accepted reference metadata only when it still matches parsed sources.

    Args:
        job_id: Existing job identifier.
        document: Current original parsed records from the job detail endpoint.
    Returns:
        Status and accepted image metadata without model-generated prose. Missing or
        stale manifests expose no images. Reading never renders or calls a model.
    """
    path = storage.job_dir(job_id) / "illustrations/manifest.json"
    if not path.exists():
        return {"status": "not_prepared", "images": []}
    manifest = json.loads(path.read_text())
    if manifest.get("document_hash") != content_hash(document):
        return {"status": "stale", "images": []}
    images = [
        {k: r[k] for k in ["id", "page", "heading", "heading_id", "source_ids"]}
        for r in manifest["records"]
        if r["status"] == "accepted"
    ]
    return {
        "status": manifest["status"],
        "images": images,
        "candidates": manifest["candidate_count"],
        "processed": len(manifest["records"]),
        "unprocessed": manifest["unprocessed"],
    }
