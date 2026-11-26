"""Turn a newly uploaded PDF into saved text, then start its first analysis.

The work continues on the server even if the reader closes the browser. Analysis
starts only when the PDF was successfully read and contains usable text. Viewing
an old manual does not restart a paused or failed analysis."""

import json

from workbench.agentic_workflow import run_manual_analysis as analysis
from workbench.job_storage import job_files_and_audit_log as storage
from workbench.manual_analysis.estimate_fact_extraction_work import analysis_preflight
from workbench.pdf_processing import parse_and_save_pdf as ingestion


def process_uploaded_manual(job_id):
    """Claim a new upload, parse it, then start analysis once if admission succeeds.

    Args:
        job_id: Newly queued upload whose PDF already passed upload validation.
    Returns:
        None; saves parsing and analysis progress through the existing workers.
        Duplicate invocations do nothing after the initial queued state is claimed.
        Failed or partial parsing, empty text and request-size blockers leave a
        visible explanation without starting model calls. Analysis receives one
        normal bounded work slice; later failure or budget pauses require Resume.
        Calls analysis outside the storage lock so parallel requests cannot deadlock.
    """
    with storage.LOCK:
        if storage.state(job_id)["status"] != "queued":
            return
        storage.update(
            job_id,
            status="parsing",
            stage="Layout-aware extraction",
            automatic_analysis_requested=True,
        )
    ingestion.parse(job_id)
    with storage.LOCK:
        if storage.state(job_id)["status"] != "parsed":
            return
        document = json.loads((storage.job_dir(job_id) / "document.json").read_text())
        blocker = None
        if document.get("parser_status") != "success":
            blocker = "PDF parsing was incomplete. Inspect the sources before starting analysis."
        elif not any(
            item.get("text", "").strip() for item in document.get("items", [])
        ):
            blocker = "No usable text was extracted. Inspect the PDF before starting analysis."
        else:
            blocker = analysis_preflight(document)["blocker"]
        if blocker:
            storage.update(job_id, message=blocker, automatic_analysis_blocker=blocker)
            storage.event(job_id, "automatic_analysis_blocked", reason=blocker)
            return
        storage.update(
            job_id,
            status="analyzing",
            stage="Queued for agent analysis",
            message="PDF processing finished. Starting agent analysis.",
        )
        storage.event(
            job_id, "automatic_analysis_started", reason="Successful PDF import"
        )
    analysis.analyze(job_id)
