"""Check that the server’s version report describes code loaded at startup, not later
edits on disk. The diagnostic is exercised without starting analysis or rereading
changed source files."""

from fastapi.testclient import TestClient
from workbench.http_endpoints import read_backend_review_version as runtime
from workbench.http_endpoints.serve_application import app


def test_runtime_snapshot_is_loaded_once(monkeypatch):
    """Keep an old process from advertising later on-disk or module-name edits.

    Args:
        monkeypatch: Changes the module version label after initialization.
    Returns:
        None; the real HTTP route reports its original snapshot and returns copies.
        Offline suite isolation forbids live provider construction.
    """
    original = runtime.review_runtime()
    assert original["reviewer_version"] == "verified-objections-review-v17"
    assert original["scope_verdict_available"]
    assert not original["coverage_scope_verdict_available"]
    assert original["planner_uses_loaded_reviewer"]
    monkeypatch.setattr(runtime.reviewer, "VERSION", "unloaded-future-release")
    response = TestClient(app).get("/api/runtime")
    assert response.status_code == 200 and response.json() == original
    response.json()["startup_source_sha256"].clear()
    assert runtime.review_runtime() == original
