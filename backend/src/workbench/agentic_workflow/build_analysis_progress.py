"""Collect the saved information needed to show a manual's progress in the browser.

Readers can see the current work, completed portions, recent extracted facts and
estimated work still to come without waiting for the whole manual to finish.
Reading this summary does not start analysis, change results or contact a model."""



import json

from workbench.manual_analysis.estimate_fact_extraction_work import analysis_preflight
from workbench.manual_analysis.extract_manual_facts import source_batches

from workbench.agentic_workflow.model_call_allowances import (
    MAX_CALLS,
    MAX_INPUT_TOKENS,
)
from workbench.agentic_workflow.current_analysis_preview import current_activity
from workbench.procedure_guides.summarize_guide_investigations import summarize_guide_investigations
from workbench.agentic_workflow.estimate_remaining_fact_tokens import remaining_estimate
from workbench.agentic_workflow.analysis_stage_status import (
    current_message,
    phase_status,
)


def action_summary(event: dict, document: dict | None) -> dict:
    """Describe a selected inspection using actual source metadata when available.

    Args:
        event: Saved agent_decision event with action, reason and optional source ID.
        document: Parsed source document, or None before import completes.
    Returns:
        Human-readable action and target, preserving the model's stated reason.
        An inspected table's actual page/section takes precedence over claimed labels.
    """
    item = next(
        (
            i
            for i in (document or {}).get("items", [])
            if i["id"] == event.get("evidence_id")
        ),
        None,
    )
    page = item["page"] if item else event.get("page")
    action = event.get("action")
    titles = {
        "read_page": "Read a source page",
        "inspect_table": "Inspect a table",
        "inspect_image": "Inspect a page image with the vision model",
        "search_manual": "Search the document",
        "finish": "Finish document inspection",
    }
    target = (
        f"PDF page {page}"
        if action in ("read_page", "inspect_table", "inspect_image") and page
        else ""
    )
    if item and item.get("section"):
        target += " · " + item["section"][-1]
    if action == "search_manual":
        target = event.get("query", "")
    return {
        "title": titles.get(action, action or "Inspect document"),
        "target": target,
        "page": page if target and action != "search_manual" else None,
        "reason": event.get("reason", ""),
        "time": event.get("time"),
        "action": action,
    }


def summarize(path, result):
    """Gather observed workflow progress without model calls or storage mutation.

    Args:
        path: Existing private job directory.
        result: Detail response with state, audit and any completed artifacts.
    Returns:
        View data with action history, measured usage, phase statuses and explicitly
        approximate extraction estimates. Availability follows real saved evidence.
    """
    state = result["state"]
    document = result.get("document")
    events = result.get("audit", [])
    profile = result.get("profile") or {}
    checkpoint_path = path / "facts-checkpoint.json"
    checkpoint = (
        json.loads(checkpoint_path.read_text()) if checkpoint_path.exists() else {}
    )
    batches = source_batches(path, document)[0] if document else []
    completed = checkpoint.get("batches_processed", profile.get("batches_processed", 0))
    progress = {
        "completed_batches": completed,
        "total_batches": len(batches),
        "accepted_facts": len(checkpoint.get("facts", profile.get("facts", []))),
        "rejected_facts": len(checkpoint.get("rejected", [])),
    }
    phases, active = phase_status(path, result, completed, len(batches))
    decisions = [
        action_summary(e, document) for e in events if e["kind"] == "agent_decision"
    ]
    finished = {
        e.get("call") for e in events if e["kind"] in ("model_result", "model_error")
    }
    pending = [
        e
        for e in events
        if e["kind"] == "model_start" and e.get("call") not in finished
    ]
    by_role = {}
    for event in events:
        if event["kind"] == "model_result":
            role = by_role.setdefault(
                event.get("role", "text"), {"input": 0, "output": 0, "calls": 0}
            )
            role["input"] += event.get("input_tokens") or 0
            role["output"] += event.get("output_tokens") or 0
            role["calls"] += 1
    preflight = analysis_preflight(document) if document else None
    blocked = state["status"] in ("failed", "interrupted", "paused")
    current = current_message(
        state, active, progress, profile, result.get("chunks", [])
    )
    return {
        "uncertainty_review_strategy": "local-search-broader-v2",
        "preflight": preflight,
        "inspection_preview": None,  # Retired; historical results remain below.
        "inspection_result": result.get("decisions"),
        "phases": phases,
        "current": current,
        "activity_focus": current_activity(path, state, active, current),
        "blocker": current["message"] if blocked else (preflight or {}).get("blocker"),
        "decisions": decisions,
        "latest_decision": decisions[-1] if decisions else None,
        "pending_call": pending[-1]
        if pending and state["status"] == "analyzing"
        else None,
        "usage_by_role": by_role,
        "progress": progress,
        # Only persisted, source-checked facts are shown; never stream unvalidated
        # proposals. A small recent window keeps polling responses lightweight.
        "recent_facts": [
            {
                key: fact.get(key)
                for key in (
                    "category",
                    "name",
                    "value",
                    "applies_to",
                    "page",
                    "evidence_id",
                )
            }
            for fact in checkpoint.get("facts", profile.get("facts", []))[-8:][::-1]
        ],
        "task_progress": state.get("task_progress"),
        "guide_progress": summarize_guide_investigations(path, result),
        "estimate": remaining_estimate(path, batches, completed, events),
        "allowance": {"calls": MAX_CALLS, "input_tokens": MAX_INPUT_TOKENS},
        "input_allowance": state.get("input_allowance"),
        "can_resume": blocked
        and bool(document)
        and not (preflight or {}).get("blocker"),
        "can_analyze": state["status"] == "parsed"
        and not (preflight or {}).get("blocker"),
    }
