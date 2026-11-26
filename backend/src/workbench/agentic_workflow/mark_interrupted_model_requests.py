"""Stop showing old AI requests as active after the application restarts.

A provider may have processed a request even when its reply was never saved. This
file keeps those attempts in the history and marks missing usage as unknown,
rather than inventing a response or assuming the provider did not charge for it."""

from workbench.job_storage import job_files_and_audit_log as storage


def mark_interrupted_model_requests(job_id):
    """Mark unmatched request starts once, without altering any original receipt.

    Args:
        job_id: Existing manual whose audit may contain requests interrupted by restart.
    Returns:
        Count of newly marked attempts. Appends model_error events, adds unknown-usage
        counts and clears stale in-flight indicators. Repeated startup is idempotent.
    """
    with storage.LOCK:
        events = storage.events(job_id)
        starts = {e["call"]: e for e in events if e["kind"] == "model_start"}
        finished = {
            e["call"] for e in events if e["kind"] in ("model_result", "model_error")
        }
        pending = sorted(set(starts) - finished)
        for call in pending:
            storage.event(
                job_id,
                "model_error",
                call=call,
                role=starts[call]["role"],
                usage="unknown",
                reason="Application restarted before a response was recorded.",
            )
        if pending or storage.state(job_id).get("active_model_calls"):
            state = storage.state(job_id)
            storage.update(
                job_id,
                unknown_usage_calls=state["unknown_usage_calls"] + len(pending),
                active_model_calls=[],
            )
        return len(pending)
