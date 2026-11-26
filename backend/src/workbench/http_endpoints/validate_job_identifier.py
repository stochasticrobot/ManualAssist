"""Check that a requested manual has a valid identifier before opening its files.

Browser requests must not turn a supplied name into an arbitrary disk path. This
helper accepts only the expected saved-manual location and reports invalid or
missing requests instead of reading unrelated files."""

from pathlib import Path
from fastapi import HTTPException
from workbench.job_storage import job_files_and_audit_log as storage


def directory(job_id: str) -> Path:
    """Translate invalid job identifiers into an HTTP 404.

    Args:
        job_id: Untrusted route identifier.
    Returns:
        Valid job directory; raises HTTPException for nonexistent/invalid jobs.
    """
    try:
        return storage.job_dir(job_id)
    except ValueError:
        raise HTTPException(404, "Job not found") from None
