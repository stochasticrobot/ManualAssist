"""Check uploaded PDFs and turn selected original pages into viewable images.

The application needs file and page-count limits before accepting work, and
readers need to see the page behind a citation. These helpers inspect or render
the PDF; they do not extract facts, interpret pictures or send requests to an AI."""

from io import BytesIO
from pathlib import Path
import threading
import pypdfium2 as pdfium

PDF_LOCK = threading.RLock()


def inspect_pdf(data: bytes) -> int:
    """Check a bounded PDF before it is admitted to the local queue.

    Args:
        data: Uploaded PDF bytes, at most 25 MiB.
    Returns:
        Number of pages; raises ValueError for invalid, encrypted or oversized PDFs.
    """
    if len(data) > 25 * 1024 * 1024 or not data.startswith(b"%PDF-"):
        raise ValueError("Upload a PDF no larger than 25 MiB")
    with PDF_LOCK:
        try:
            doc = pdfium.PdfDocument(data)
            count = len(doc)
            doc.close()
        except Exception:
            raise ValueError(
                "PDF could not be opened; encrypted PDFs are not supported"
            ) from None
    if not 1 <= count <= 80:
        raise ValueError("This demo accepts 1–80 pages per PDF")
    return count


def page_image(path: Path, page: int) -> bytes:
    """Render one actual PDF page for source inspection or the vision tool.

    Args:
        path: Original PDF path.
        page: One-based physical page number, not a printed page label.
    Returns:
        PNG bytes; raises ValueError for invalid pages. No remote calls occur.
    """
    with PDF_LOCK:
        doc = pdfium.PdfDocument(path)
        try:
            if not 1 <= page <= len(doc):
                raise ValueError("Page outside document")
            pdf_page = doc[page - 1]
            bitmap = pdf_page.render(scale=1.5)
            image = bitmap.to_pil()
            buf = BytesIO()
            image.save(buf, format="PNG")
            bitmap.close()
            pdf_page.close()
            return buf.getvalue()
        finally:
            doc.close()
