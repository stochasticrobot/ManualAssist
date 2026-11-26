"""Read an uploaded PDF locally and save the text and layout the application will
use.

Text recognition is used where needed so scanned pages can be searched as well as
text PDFs. The saved records keep page locations and parsing information for later
inspection. This is document reading, not a language-model analysis of what the
instructions mean."""

import hashlib
import logging
from workbench.job_storage import job_files_and_audit_log as storage
from workbench.pdf_processing.normalize_parsed_pdf import normalize


def convert(path):
    """Configure the existing local OCR/layout parser with limited CPU parallelism.

    Args:
        path: Validated original PDF path, never a URL.
    Returns:
        Docling conversion result. Model weights may download on first use; no paid
        generative model is invoked. Conversion errors propagate to the worker.
    """
    from docling.document_converter import DocumentConverter, PdfFormatOption
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.datamodel.base_models import InputFormat

    options = PdfPipelineOptions()
    options.accelerator_options.num_threads = 2
    options.do_ocr = True
    converter = DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)}
    )
    return converter.convert(path)


def save_document(job_id, result):
    """Publish normalized evidence alongside raw parser outputs for later inspection.

    Args:
        job_id: Existing import job with immutable source.pdf.
        result: Completed Docling result with original layout and parser status.
    Returns:
        None; writes document/raw JSON and Markdown, then observed counts and audit.
        Partial parser status is retained rather than labelled successful extraction.
    """
    path = storage.job_dir(job_id)
    document = {
        **normalize(result.document),
        "sha256": hashlib.sha256((path / "source.pdf").read_bytes()).hexdigest(),
        "pages": len(result.document.pages),
        "parser": "docling",
        "parser_status": str(result.status).split(".")[-1].lower(),
        "page_numbering": "One-based physical PDF pages; printed labels may differ.",
    }
    storage.save(path / "document.json", document)
    result.document.save_as_json(path / "docling.json")
    (path / "extracted.md").write_text(result.document.export_to_markdown())
    counts = {key: len(document[key]) for key in ("items", "tables", "figures")}
    storage.event(
        job_id,
        "tool_result",
        tool="parse_pdf",
        pages=document["pages"],
        **counts,
        parser_status=document["parser_status"],
    )
    storage.update(
        job_id,
        status="parsed",
        stage="PDF imported",
        pages=document["pages"],
        **counts,
        message="Text, sections, tables and graphics extracted. Sources are available for inspection.",
    )


def parse(job_id):
    """Run local ingestion and expose a readable failure without losing source bytes.

    Args:
        job_id: Queued job whose PDF passed upload checks.
    Returns:
        None; transitions parsing to parsed or failed. Saves all derived evidence on
        success; logs failure type without credentials or model calls on error.
    """
    storage.update(job_id, status="parsing", stage="Layout-aware extraction")
    storage.event(job_id, "tool_start", tool="parse_pdf", parser="docling", ocr=True)
    try:
        save_document(job_id, convert(storage.job_dir(job_id) / "source.pdf"))
    except Exception as exc:
        storage.event(job_id, "tool_error", tool="parse_pdf", error=type(exc).__name__)
        storage.update(
            job_id,
            status="failed",
            stage="Parsing failed",
            message=f"{type(exc).__name__}: local parsing failed; see server diagnostics.",
        )
        logging.exception("Local PDF parsing failed for %s", job_id)
