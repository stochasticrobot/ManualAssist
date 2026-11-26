"""Save each uploaded manual, its progress, results and history in its own folder.

The browser may read progress while analysis is saving it. These helpers replace
saved records safely and coordinate history writes so readers do not receive a
half-written file. They also list previously saved manuals for the library view."""

from datetime import datetime, timezone
import json
from pathlib import Path
import threading
from uuid import uuid4
from workbench.config import ROOT

DATA = ROOT / "data"
JOBS = DATA / "jobs"
LOCK = threading.RLock()


def now() -> str:
    """Get a sortable UTC receipt timestamp.

    Args:
        None.
    Returns:
        ISO timestamp including timezone; no persistence side effects.
    """
    return datetime.now(timezone.utc).isoformat()


def save(path: Path, value) -> None:
    """Atomically replace a JSON artifact so readers never see partial writes.

    Args:
        path: Destination inside private application storage.
        value: JSON-serializable data; never include credentials.
    Returns:
        None; writes a temporary sibling and atomically renames it.
    """
    with LOCK:
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_text(json.dumps(value, ensure_ascii=False, indent=2))
        temp.replace(path)


def job_dir(job_id: str) -> Path:
    """Resolve only a valid existing job ID, preventing filesystem traversal.

    Args:
        job_id: 32-character hexadecimal UUID identifier.
    Returns:
        Existing job directory; raises ValueError for invalid or absent IDs.
    """
    if len(job_id) != 32 or any(c not in "0123456789abcdef" for c in job_id):
        raise ValueError("Invalid job ID")
    path = JOBS / job_id
    if not path.is_dir():
        raise ValueError("Job not found")
    return path


def create(name: str, pdf: bytes) -> dict:
    """Store an original upload and initial durable job state.

    Args:
        name: Display-only filename; never used as a filesystem path.
        pdf: Validated PDF bytes.
    Returns:
        New queued job record; writes source.pdf and state.json in a private folder.
    """
    JOBS.mkdir(parents=True, exist_ok=True)
    job_id = uuid4().hex
    path = JOBS / job_id
    path.mkdir(mode=0o700)
    (path / "source.pdf").write_bytes(pdf)
    state = {
        "id": job_id,
        "name": name,
        "created": now(),
        "status": "queued",
        "stage": "Queued",
        "message": "",
        "calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "unknown_usage_calls": 0,
        "review": [],
    }
    save(path / "state.json", state)
    return state


def state(job_id: str) -> dict:
    """Read a complete persisted state snapshot.

    Args:
        job_id: Existing job identifier.
    Returns:
        State dictionary; propagates invalid IDs or storage failures.
    """
    return json.loads((job_dir(job_id) / "state.json").read_text())


def update(job_id: str, **fields) -> dict:
    """Merge changed fields under the process lock, preserving other state.

    Args:
        job_id: Existing job identifier.
        **fields: Fields to replace in the saved record.
    Returns:
        Updated record; atomically writes state.json.
    """
    with LOCK:
        record = state(job_id)
        record.update(fields)
        save(job_dir(job_id) / "state.json", record)
        return record


def event(job_id: str, kind: str, **detail) -> None:
    """Append a timestamped public audit event without credentials or hidden reasoning.

    Args:
        job_id: Existing job identifier.
        kind: Event category such as tool_start, tool_result or model_result.
        **detail: Safe tool arguments, results, concise decisions or usage receipts.
    Returns:
        None; appends one JSON line under a process lock.
    """
    with LOCK:
        with (job_dir(job_id) / "audit.jsonl").open("a") as stream:
            stream.write(json.dumps({"time": now(), "kind": kind, **detail}) + "\n")


def list_jobs() -> list[dict]:
    """List saved jobs newest first without loading document contents.

    Args:
        None.
    Returns:
        Job states, or an empty list before the first upload.
    """
    return sorted(
        [json.loads(p.read_text()) for p in JOBS.glob("*/state.json")],
        key=lambda x: x["created"],
        reverse=True,
    )


def events(job_id: str) -> list[dict]:
    """Read complete audit lines for progress and lifetime attempt accounting.

    Args:
        job_id: Existing job whose audit is private to this application.
    Returns:
        Ordered event dictionaries, or an empty list before the first event.
        Uses the writer lock so polling cannot observe a half-written line.
    """
    with LOCK:
        path = job_dir(job_id) / "audit.jsonl"
        return (
            [json.loads(line) for line in path.read_text().splitlines()]
            if path.exists()
            else []
        )
