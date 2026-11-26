"""Check that an old AI reply is reused only when the new request is identical in the
required ways. Changing the instructions or required reply fields must prevent
reuse of an incompatible answer."""

from copy import deepcopy
from workbench.job_storage import job_files_and_audit_log as storage
from workbench.agentic_workflow.reuse_saved_model_responses import find_response


def test_response_reuse_requires_identical_prompt_and_schema():
    """Reuse current replies while rejecting older or altered request definitions.

    Args:
        None; the automatic test fixture isolates saved job data.
    Returns:
        None; proves exact reuse and rejection of changed prompts or schema fields
        without provider calls or changes to the original saved response.
    """
    job = storage.create("manual.pdf", b"fixture")["id"]
    path = storage.job_dir(job)
    request = {
        "role": "text",
        "prompt": "Current task and source",
        "system": "Instructions",
        "schema": {"title": "CurrentReply", "required": ["facts"]},
        "max_tokens": 6000,
        "image_sha256": [],
        "identity": {"provider": "fixture", "model": "fixture"},
    }
    response = {
        "provider": "fixture",
        "model": "fixture",
        "text": '{"facts":[]}',
        "stop_reason": "end_turn",
    }
    storage.save(path / "call-001-request.json", request)
    storage.save(path / "call-001-response.json", response)
    before = (path / "call-001-response.json").read_bytes()
    assert find_response(job, request) == response
    changed = deepcopy(request)
    changed["prompt"] = "Former task wording and source"
    assert find_response(job, changed) is None
    changed = deepcopy(request)
    changed["schema"]["required"] = []
    assert find_response(job, changed) is None
    assert (path / "call-001-response.json").read_bytes() == before
    assert storage.state(job)["calls"] == 0
