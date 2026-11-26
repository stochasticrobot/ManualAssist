"""Check that altered quotations, damaged structured replies and requests for private
files are rejected. Prepared examples exercise evidence and file-access boundaries
without asking a model to decide them."""

import pytest
from fastapi.testclient import TestClient
from workbench.manual_analysis.check_source_quotations import anchored
from workbench.model_access.parse_model_json import read_json
from workbench.http_endpoints.serve_application import app
from workbench.job_storage import job_files_and_audit_log as storage


def test_quote_anchor_rejects_altered_limit():
    """Reject changed numbers and nonexistent source references.

    Args:
        None.
    Returns:
        None; assertions fail if fabricated anchors pass validation.
    """
    sources = {"e1": {"text": "Use only between 4°C and 40°C."}}
    assert anchored("e1", "between 4°C and 40°C", sources)
    assert not anchored("e1", "between 4°C and 50°C", sources)
    assert not anchored("e2", "between 4°C and 40°C", sources)
    assert not anchored("e1", "4", sources)


def test_json_wrapper_is_lossless_and_rejects_extra_prose():
    """Accept complete fences while refusing content repair or extra commentary.

    Args:
        None.
    Returns:
        None; assertions fail if fields are coerced or extra prose accepted.
    """
    assert read_json('```json\n{"inside":"MAPLE","outside":"RIVER"}\n```') == {
        "inside": "MAPLE",
        "outside": "RIVER",
    }
    with pytest.raises(ValueError):
        read_json('Here is the result: {"inside":"MAPLE"}')
    with pytest.raises(ValueError):
        read_json('{"inside":}')


def test_upload_and_asset_boundaries(tmp_path, monkeypatch):
    """Reject invalid uploads, foreign mutations and private asset paths.

    Args:
        tmp_path: Isolated test storage directory.
        monkeypatch: Scoped storage override; never touches production jobs.
    Returns:
        None; isolated storage prevents startup checks from touching real jobs.
    """
    monkeypatch.setattr(storage, "JOBS", tmp_path / "jobs")
    with TestClient(app) as client:
        assert (
            client.post(
                "/api/jobs",
                files={"file": ("bad.pdf", b"not a pdf", "application/pdf")},
            ).status_code
            == 400
        )
        assert (
            client.post(
                "/api/jobs",
                headers={"origin": "https://foreign.example"},
                files={"file": ("bad.pdf", b"bad")},
            ).status_code
            == 403
        )
        assert client.get("/api/jobs/not-a-job/assets/.env").status_code == 404
        assert client.get("/.env").status_code == 404


def test_windows_cannot_create_an_artificial_quote():
    """Prevent separate source fragments from becoming a fabricated contiguous anchor.

    Args:
        None.
    Returns:
        None; rejects cross-window concatenation while accepting text within a window.
    """
    from workbench.manual_analysis.check_source_quotations import source_map

    sources = source_map(
        [
            {"id": "e1", "text": "Alpha ends here.", "page": 1},
            {"id": "e1", "text": "Beta starts here.", "page": 1},
        ]
    )
    assert anchored("e1", "Alpha ends here.", sources)
    assert not anchored("e1", "ends here. Beta starts", sources)
