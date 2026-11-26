"""Find an earlier AI reply that can safely replace an identical new request.

Continuing a paused analysis should not pay for answers already received. Reuse
requires the same model, instructions, source material and reply requirements; a
merely similar question does not qualify."""

import hashlib
import json

from workbench.job_storage import job_files_and_audit_log as storage

SUCCESS_STOPS = ("end_turn", "stop_sequence", "complete")


def request_record(role, request, identity):
    """Describe every response-affecting request field without saving image bytes.

    Args:
        role: Application role such as text or vision.
        request: Neutral prompt, schema, images and output allowance.
        identity: Provider/model identifiers, never credentials.
    Returns:
        JSON-compatible receipt including private source bindings for exact replay.
        Binding records are never sent to the provider; changed IDs/windows cannot
        reuse a result merely because their visible text happens to be identical.
    """
    return {
        **(
            {"evidence_bindings": request.prompt.sources}
            if hasattr(request.prompt, "sources")
            else {}
        ),
        "role": role,
        "prompt": request.prompt,
        "system": request.system,
        "schema": request.schema,
        "max_tokens": request.max_tokens,
        "image_sizes": [len(i.data) for i in request.images],
        "identity": identity,
        "image_sha256": [hashlib.sha256(i.data).hexdigest() for i in request.images],
    }


def find_response(job_id, wanted):
    """Find a compatible successful receipt before charging a new call allowance.

    Args:
        job_id: Existing job containing private request/response pairs.
        wanted: Complete request record from request_record.
    Returns:
        Saved response dictionary or None. Logs zero-call replay when found.
        Source text, schema, prompt and all response-affecting settings must match
        exactly; older request formats are not migrated.
    """
    for path in sorted(storage.job_dir(job_id).glob("call-*-request.json")):
        saved = json.loads(path.read_text())
        response_path = path.with_name(path.name.replace("-request", "-response"))
        fields = ("role", "system", "max_tokens", "image_sha256")
        if not all(
            saved.get(key, [] if key == "image_sha256" else None) == wanted[key]
            for key in fields
        ):
            continue
        if (
            saved.get("evidence_bindings") != wanted.get("evidence_bindings")
            or saved.get("schema") != wanted["schema"]
            or saved.get("prompt") != wanted["prompt"]
        ):
            continue
        if not response_path.exists():
            continue
        response = json.loads(response_path.read_text())
        if response["stop_reason"] not in SUCCESS_STOPS:
            continue
        if not all(
            response.get(key) == value for key, value in wanted["identity"].items()
        ):
            continue
        storage.event(
            job_id,
            "model_replay",
            source_call=path.stem,
            role=wanted["role"],
            provider_calls=0,
        )
        return response
    return None
