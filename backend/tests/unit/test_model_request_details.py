"""Check that the Activity view can read a complete saved AI request but cannot open
arbitrary private files. The request is displayed without sending it to the model
again."""

from fastapi.testclient import TestClient
from workbench.http_endpoints.serve_application import app
from workbench.job_storage import job_files_and_audit_log as storage


def test_saved_request_details_are_complete_read_only_and_job_scoped():
    """Expose recorded inputs rather than a prompt summary or private configuration.

    Args:
        None; automatic fixtures isolate all storage and prohibit live providers.
    Returns:
        None; verifies complete text/schema, image metadata, no-store response, request
        filtering, missing-call behavior and unchanged job files after reading.
    """
    job = storage.create("prompts.pdf", b"%PDF-fixture")["id"]
    other = storage.create("other.pdf", b"%PDF-fixture")["id"]
    path = storage.job_dir(job)
    receipt = {
        "prompt": "Read the full source: " + "<source>\n" * 2000,
        "system": "Extract source-supported facts.",
        "role": "text",
        "schema": {"type": "object"},
        "identity": {"provider": "fixture", "model": "test"},
        "max_tokens": 6000,
        "image_sizes": [42],
        "image_sha256": ["a" * 64],
        "private_unknown_field": "must not be exposed",
    }
    storage.save(path / "call-001-request.json", receipt)
    with TestClient(app) as client:
        before = {p.name: p.read_bytes() for p in path.iterdir() if p.is_file()}
        response = client.get(f"/api/jobs/{job}/calls/1/request")
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        data = response.json()
        for key in (
            "prompt",
            "system",
            "schema",
            "identity",
            "max_tokens",
            "image_sizes",
            "image_sha256",
        ):
            assert data[key] == receipt[key]
        assert "private_unknown_field" not in data
        assert client.get(f"/api/jobs/{other}/calls/1/request").status_code == 404
        assert client.get(f"/api/jobs/{job}/calls/0/request").status_code == 404
        assert client.get(f"/api/jobs/{job}/calls/999/request").status_code == 404
        assert client.get(f"/api/jobs/{job}/calls/.env/request").status_code == 422
        assert (
            client.get(f"/api/jobs/{job}/assets/call-001-request.json").status_code
            == 404
        )
        assert before == {p.name: p.read_bytes() for p in path.iterdir() if p.is_file()}
