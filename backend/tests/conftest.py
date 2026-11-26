"""Keep automated tests from reading or changing the user’s saved manuals and model
settings. Temporary folders and controlled connections isolate test work from the
real application."""

import pytest
from workbench.job_storage import job_files_and_audit_log as storage
from workbench.model_access.providers.bedrock import BedrockModel


@pytest.fixture(autouse=True)
def isolated_runtime(tmp_path, monkeypatch):
    """Isolate persistence before TestClient startup and prohibit paid adapter creation.

    Args:
        tmp_path: Per-test private filesystem supplied by pytest.
        monkeypatch: Restores original paths and constructor after the test.
    Returns:
        None; any accidental Bedrock construction fails immediately. Tests may inject
        a neutral fixture service, but cannot silently use the production key.
    """
    monkeypatch.setattr(storage, "DATA", tmp_path)
    monkeypatch.setattr(storage, "JOBS", tmp_path / "jobs")

    def forbidden(*args, **kwargs):
        """Reject live adapter construction in the offline suite.

        Args:
            *args: Ignored constructor positional arguments.
            **kwargs: Ignored constructor keyword arguments.
        Returns:
            Never; raises AssertionError without displaying credential arguments.
        """
        raise AssertionError("Live Bedrock adapters are forbidden in offline tests")

    monkeypatch.setattr(BedrockModel, "__init__", forbidden)

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
