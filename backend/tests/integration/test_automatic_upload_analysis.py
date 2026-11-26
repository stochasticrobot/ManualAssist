"""Check that a usable PDF upload advances automatically into analysis, while failed
or empty imports do not. Parsing and model work are simulated so this test cannot
start a paid analysis."""

import pytest
from fastapi.testclient import TestClient
from test_large_manual_completion_and_resume import InlineWorker
from workbench.agentic_workflow import process_uploaded_manual as workflow
from workbench.http_endpoints import background_worker_and_question_lock as runtime
from workbench.http_endpoints import upload_and_analysis_routes as routes
from workbench.http_endpoints.serve_application import app
from workbench.job_storage import job_files_and_audit_log as storage


@pytest.mark.parametrize(
    "outcome", ["success", "partial", "failed", "empty", "oversized"]
)
def test_upload_automatically_advances_only_successful_usable_imports(
    monkeypatch, outcome
):
    """Exercise the upload endpoint, admission, duplicate guard and read-only reload.

    Args:
        monkeypatch: Replaces PDF conversion, outer executor and model-analysis body.
        outcome: Simulated parser result or request-size admission failure.
    Returns:
        None; asserts exactly one analysis for a successful upload, none on other
        outcomes, and no additional work from duplicate callbacks or reading jobs.
    """
    parsed, analyzed = [], []

    def parse(job_id):
        """Publish a controlled parser outcome in isolated job storage.

        Args:
            job_id: Job created through the real upload endpoint.
        Returns:
            None; saves a source document or a failed status without loading OCR.
        """
        parsed.append(job_id)
        if outcome == "failed":
            storage.update(job_id, status="failed")
            return
        storage.save(
            storage.job_dir(job_id) / "document.json",
            dict(
                parser_status="partial" if outcome == "partial" else "success",
                pages=1,
                tables=[],
                figures=[],
                outline=[],
                items=[]
                if outcome == "empty"
                else [
                    dict(id="e1", page=1, label="text", text="Read the instructions.")
                ],
            ),
        )
        storage.update(job_id, status="parsed")

    def analyze(job_id):
        """Record the automatic handoff and emulate a later allowance pause.

        Args:
            job_id: Successfully admitted job reserved for analysis.
        Returns:
            None; records one start and leaves it paused to prove no automatic Resume.
        """
        assert storage.state(job_id)["status"] == "analyzing"
        analyzed.append(job_id)
        storage.update(job_id, status="paused", stage="Analysis paused")

    monkeypatch.setattr(runtime, "WORKER", InlineWorker())
    monkeypatch.setattr(routes, "inspect_pdf", lambda data: None)
    monkeypatch.setattr(workflow.ingestion, "parse", parse)
    monkeypatch.setattr(workflow.analysis, "analyze", analyze)
    if outcome == "oversized":
        monkeypatch.setattr(
            workflow,
            "analysis_preflight",
            lambda doc: {"blocker": "Oversized source request"},
        )
    with TestClient(app) as client:
        response = client.post(
            "/api/jobs",
            files={"file": ("manual.pdf", b"%PDF-fixture", "application/pdf")},
        )
        assert response.status_code == 200
        job_id = response.json()["id"]
        assert parsed == [job_id]
        assert analyzed == ([job_id] if outcome == "success" else [])
        workflow.process_uploaded_manual(job_id)
        assert client.get("/api/jobs").status_code == 200
        assert client.get(f"/api/jobs/{job_id}").status_code == 200
        assert parsed == [job_id]
        assert analyzed == ([job_id] if outcome == "success" else [])
        if outcome == "success":
            assert storage.state(job_id)["status"] == "paused"
        elif outcome != "failed":
            assert storage.state(job_id)["automatic_analysis_blocker"]
