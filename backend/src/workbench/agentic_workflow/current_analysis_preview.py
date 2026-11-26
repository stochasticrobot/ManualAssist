"""Show a concrete example of the work the application is currently doing.

The progress display can show a recently extracted fact, a troubleshooting step,
or a question being checked against the manual. It uses actual saved work rather
than asking an AI to invent a progress explanation. After a pause, it describes
the last recorded request instead of claiming new work is underway."""

import json

from pydantic import ValidationError

from workbench.data_models.analysis_and_question_models import (
    TroubleshootingChecksGeneration,
    TroubleshootingGeneration,
)
from workbench.manual_analysis.check_source_quotations import source_map
from workbench.manual_analysis.validate_faq_and_troubleshooting import check_tree, cite


def recent_troubleshooting_nodes(path):
    """Read completed independent checks or legacy trees for an honest progress preview.

    Args:
        path: Job directory containing the saved troubleshooting stage.
    Returns:
        Up to eight node previews from recent completed batches, newest batch first.
        Schema, tree structure and exact source quotes are checked before display.
        Pending replies and rejected trees are omitted. Reads only; does not certify
        interpretation or modify checkpoints. Missing files yield no previews.
    """
    checks_stage = path / "troubleshooting_checks-stage.json"
    if checks_stage.exists():
        previews = []
        for task in reversed(json.loads(checks_stage.read_text()).get("tasks", [])):
            if task.get("response") is None:
                continue
            try:
                response = TroubleshootingChecksGeneration.model_validate(
                    task["response"]
                )
                for check in response.troubleshooting_checks:
                    value = cite(check.model_dump(), source_map(task["batch"]))
                    previews.append(
                        {
                            "name": value["symptom"],
                            "value": value["instruction"],
                            "category": "Documented check",
                            "applies_to": value["applies_to"],
                            "pages": sorted({c["page"] for c in value["citations"]}),
                        }
                    )
            except ValueError:
                continue
        return previews[:8]
    stage = path / "troubleshooting-stage.json"
    if not stage.exists():
        return []
    saved = json.loads(stage.read_text())
    items = []
    for task in reversed(saved.get("tasks", [])):
        if task.get("response") is None:
            continue
        try:
            response = TroubleshootingGeneration.model_validate(task["response"])
        except ValidationError:
            continue
        sources = source_map(task["batch"])
        for proposal in response.troubleshooting:
            tree = proposal.model_dump()
            try:
                check_tree(tree)
                tree = cite(tree, sources)
            except ValueError:
                continue
            for node in tree["nodes"]:
                items.append(
                    {
                        "name": tree["symptom"],
                        "value": node["text"],
                        "category": {
                            "check": "Decision",
                            "action": "Action",
                            "stop": "Stop",
                            "unresolved": "Missing information",
                        }.get(node["kind"], node["kind"]),
                        "applies_to": tree["applies_to"],
                        "pages": sorted({c["page"] for c in node["citations"]}),
                    }
                )
                if len(items) == 8:
                    return items
    return items


def review_context(path, state):
    """Read actual uncertainty proposals and source pages for the current review call.

    Args:
        path: Job directory containing private numbered model-request receipts.
        state: Persisted work status and current call number.
    Returns:
        Proposal/page mapping from explicit progress metadata, or from the known
        TargetedFindingsReview request format for paused calls. Missing/unrecognized
        receipts return empty findings, never fabricated findings. Paused workers
        use the last receipt because their progress may already describe an unsent
        next batch. Reads only.
    """
    progress = state.get("task_progress") or {}
    if state["status"] == "analyzing" and "current_findings" in progress:
        return {
            "findings": progress["current_findings"],
            "pages": progress.get("pages", []),
        }
    call = state.get("calls", 0)
    receipt = path / f"call-{call:03}-request.json"
    if not receipt.exists():
        return {"findings": [], "pages": []}
    request = json.loads(receipt.read_text())
    if (request.get("schema") or {}).get("title") not in {
        "TargetedFindingsReview",
    }:
        return {"findings": [], "pages": []}
    prompt = request.get("prompt", "")
    if "evidence_bindings" in request:
        try:
            payload, _ = json.JSONDecoder().raw_decode(
                prompt[prompt.index('{"task":') :]
            )
            sources = request["evidence_bindings"]
            findings = []
            for finding in payload["task"].get("findings", []):
                value = {k: v for k, v in finding.items() if k != "passages"}
                value["evidence_ids"] = list(
                    dict.fromkeys(
                        sources[i - 1]["id"]
                        for i in finding.get("passages", [])
                        if 1 <= i <= len(sources)
                    )
                )
                findings.append(value)
            return {"findings": findings, "pages": sorted({s["page"] for s in sources})}
        except (ValueError, KeyError, TypeError):
            return {"findings": [], "pages": []}
    try:
        value = json.loads(
            prompt.split("\nFindings: ", 1)[1].split("\nSource batch: ", 1)[0]
        )
    except (IndexError, ValueError):
        return {"findings": [], "pages": []}
    try:
        sources, _ = json.JSONDecoder().raw_decode(
            prompt.split("\nSource batch: ", 1)[1].lstrip()
        )
        pages = sorted({item["page"] for item in sources})
    except (IndexError, ValueError, KeyError, TypeError):
        return {"findings": [], "pages": []}
    return {"findings": value if isinstance(value, list) else [], "pages": pages}


def current_activity(path, state, active, message):
    """Give the progress strip stage-specific content derived from saved work.

    Args:
        path: Existing job directory, read only.
        state: Persisted worker state, including source pages and any current proposals.
        active: Phase ID selected from workflow status and completed artifacts.
        message: Existing human-readable current title/message dictionary.
    Returns:
        Kind, title, rotation scope and a small list of display items. Facts are filled
        by the caller only during extraction. Troubleshooting previews are completed,
        source-checked nodes, not a live stream of the pending reply. Paused review is labelled as previous
        work rather than falsely suggesting another model request is running.
    """
    task = state.get("task_progress") or {}
    scope = f"{active}:{task.get('task')}:{task.get('completed')}:{state.get('calls')}:{state['status']}"
    if active == "extract":
        return {
            "kind": "facts",
            "title": "Recently extracted facts",
            "scope": "facts",
            "items": [],
        }
    if active == "troubleshooting":
        nodes = recent_troubleshooting_nodes(path)
        if nodes:
            return {
                "kind": "troubleshooting",
                "title": "Recently generated troubleshooting steps",
                "scope": "troubleshooting",
                "items": nodes,
            }
    if active == "validate" and task.get("task") == "uncertainty_review":
        review = review_context(path, state)
        proposals = review["findings"]
        items = [
            {
                "name": "Uncertainty in the most recently started check"
                if task.get("parallel_limit", 1) > 1
                else "Uncertainty being checked",
                "value": item["issue"],
                "category": item.get("severity", "review"),
                "pages": review["pages"],
            }
            for item in proposals
            if isinstance(item, dict) and isinstance(item.get("issue"), str)
        ]
        if items:
            return {
                "kind": "uncertainties",
                "scope": scope,
                "title": "Checking uncertainties"
                if state["status"] == "analyzing"
                else "Last uncertainty checks",
                "items": items,
            }
    return {
        "kind": "status",
        "scope": scope,
        "title": message["title"],
        "items": [
            {
                "name": message["title"],
                "value": message["message"],
                "pages": task.get("pages", []),
            }
        ],
    }
