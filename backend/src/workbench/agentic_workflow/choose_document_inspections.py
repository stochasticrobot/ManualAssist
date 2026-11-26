"""Retain the earlier AI-led preview of a manual for historical checks.

Before extracting facts, this preview asked an AI what the manual was about and
what needed a closer look. A closer look meant reading a page or table, searching
its text, or asking an image-capable AI about a specific picture. The aim was to
identify useful context and unanswered questions before the main analysis.

New analyses no longer run this preview: its findings were not passed into the
later fact-extraction requests. The code remains so older saved decisions and
experiments can be checked. If called directly, it can send model requests and
save their results; it is not merely a description of the old behavior."""

import hashlib
import json

from workbench.agentic_workflow.estimate_inspection_allowance import (
    inspection_allowance,
)
from workbench.data_models.analysis_and_question_models import InspectionDecision
from workbench.job_storage import job_files_and_audit_log as storage
from workbench.model_access.code_owned_source_evidence import VERSION, evidence_task
from workbench.model_access.model_requests_and_responses import ModelError
from workbench.pdf_processing.inspect_parsed_sources import inspect


def overview(document):
    """Build a disclosed navigation preview, not a replacement for reading the manual.

    Args:
        document: Parsed manual, including all physical pages and outline headings.
    Returns:
        Compact overview with explicit preview limits and original totals. Extraction
        later reads every text/table item regardless of this inspection selection.
    """
    return {
        "pages": document["pages"],
        "outline_preview": [
            {"title": h["title"][:80], "page": h["page"]}
            for h in document["outline"][:20]
        ],
        "outline_total": len(document["outline"]),
        "table_ids": [t["id"] for t in document["tables"]][:40],
        "tables_total": len(document["tables"]),
        "figure_pages": sorted({f["page"] for f in document["figures"]}),
        "page_previews": [
            {
                "page": p,
                "preview": "\n".join(
                    i["text"] for i in document["items"] if i["page"] == p
                )[:50],
            }
            for p in range(1, document["pages"] + 1)
        ],
        "preview_limits": "First 20 headings (80 characters each), 40 table IDs and 50 characters per page; full extraction follows.",
    }


def investigate(job_id, document, run):
    """Inspect within a PDF-derived action allowance, reusing completed saved work.

    Args:
        job_id: Job receiving plan, decisions, observations and stopping evidence.
        document: Parsed source metadata used by navigation and the formula.
        run: Budgeted model-call owner supporting exact saved-response replay.
    Returns:
        Decisions, observations, allowance and explicit stopping outcome. Finish
        consumes no inspection action but its model request uses the call budget.
        One final decision after the last allowed action may finish or record an
        unexecuted request. Exhaustion continues extraction with a review notice,
        never a claim that inspection is complete. Completed saved inspections are reused without another model call.
    """
    path = storage.job_dir(job_id)
    saved = path / "decisions.json"
    if run.replay and saved.exists():
        previous = json.loads(saved.read_text())
        if previous.get("evidence_binding_version") != VERSION:
            raise ModelError(
                "Saved document inspection uses an older evidence format; start a new run."
            )
        return previous
    plan = inspection_allowance(document)
    plan["source_sha256"] = hashlib.sha256(
        json.dumps(document, sort_keys=True).encode()
    ).hexdigest()
    plan_path = path / "inspection-plan.json"
    if plan_path.exists():
        previous = json.loads(plan_path.read_text())
        if previous != json.loads(json.dumps(plan)):
            raise ModelError(
                "Saved inspection allowance inputs changed; refusing different work"
            )
    else:
        storage.save(plan_path, plan)
    decisions, observations = [], []
    outcome, remaining = "allowance_reached", []
    for step in range(plan["action_allowance"] + 1):
        vision_count = sum(
            o["action"] == "inspect_image" and "observation" in o["result"]
            for o in observations
        )
        left = plan["action_allowance"] - len(observations)
        storage.update(
            job_id,
            stage="Inspect the document",
            inspection_allowance=plan,
            message=f"Inspecting the document: {len(observations)} of {plan['action_allowance']} available actions used.",
        )
        available = document.get("tables", [])[:40]
        available = available + [
            source
            for observation in observations
            for source in observation["result"].get("source_records", [])
        ]
        prompt = evidence_task(
            "Identify this document's purpose and choose a useful inspection: read_page, search_manual, inspect_table or inspect_image. "
            "For a table choose its supplied passage number; for a page choose a physical page within the document. "
            "Use vision only for a specific visual uncertainty. Finish when no useful inspection remains. "
            "State unresolved questions; the allowance is a limit, not a target.",
            {
                "page_count": document["pages"],
                "previous_observations": observations,
                "inspection_actions_remaining": left,
                "vision_remaining": max(0, 2 - vision_count),
            },
            available,
        )
        decision = run.call("text", prompt, InspectionDecision, cap=1200)
        decisions.append(decision.model_dump())
        storage.event(job_id, "agent_decision", **decision.model_dump())
        remaining = decision.remaining_questions
        if decision.action == "finish":
            outcome = "inspection_complete" if not remaining else "unfinished"
            break
        if left == 0:
            remaining = remaining or [decision.reason]
            break
        storage.event(
            job_id,
            "tool_start",
            tool=decision.action,
            page=decision.page,
            evidence_id=decision.evidence_id,
            reason=decision.reason,
            query=decision.query,
        )
        result = inspect(job_id, decision, document, run, vision_count)
        observations.append({"action": decision.action, "result": result})
        storage.event(job_id, "tool_result", tool=decision.action, result=result)
    result = {
        "evidence_binding_version": VERSION,
        "decisions": decisions,
        "observations": observations,
        "allowance": plan,
        "inspection_status": outcome,
        "inspection_actions_used": len(observations),
        "remaining_questions": remaining,
    }
    storage.save(saved, result)
    storage.update(
        job_id, inspection_status=outcome, inspection_remaining_questions=remaining
    )
    storage.event(
        job_id,
        "inspection_summary",
        status=outcome,
        actions_used=len(observations),
        action_allowance=plan["action_allowance"],
        remaining_questions=remaining,
    )
    return result
