"""Show the actual saved instructions and source text for a selected AI request.

The Activity screen loads this information only when the reader opens a request,
rather than repeatedly downloading every long prompt during progress updates. Only
existing request records for the chosen manual can be read; opening one does not
send it to the AI again."""

import json
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from workbench.http_endpoints.validate_job_identifier import directory

router = APIRouter()


@router.get("/api/jobs/{job_id}/calls/{call_number}/request")
def model_request(job_id: str, call_number: int):
    """Return the saved instructions and supplied text for one numbered model call.

    Args:
        job_id: Existing document job; validated before resolving its directory.
        call_number: Positive call number shown in the activity log, not a filename.
    Returns:
        Private, noncached JSON containing prompt, system instructions, response
        schema, model identity, output allowance and image hashes/sizes. HTTP 404
        indicates an invalid number or missing receipt. No model or image-generation
        call occurs; credentials and unrecognized receipt fields are not exposed.
    """
    path = directory(job_id)
    if call_number < 1:
        raise HTTPException(404, "Model request not available")
    target = path / f"call-{call_number:03}-request.json"
    if not target.is_file():
        raise HTTPException(404, "Model request not available")
    saved = json.loads(target.read_text())
    fields = (
        "role",
        "prompt",
        "system",
        "schema",
        "identity",
        "max_tokens",
        "image_sizes",
        "image_sha256",
    )
    return JSONResponse(
        {"call": call_number, **{key: saved.get(key) for key in fields}},
        headers={"Cache-Control": "no-store"},
    )
