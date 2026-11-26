"""Check that FAQs and troubleshooting paths with invented citations or broken
branches are rejected. Prepared examples distinguish genuine unanswered endpoints
from instructions that still require supporting passages."""

import copy
import pytest
from types import SimpleNamespace
from workbench.manual_analysis.validate_faq_and_troubleshooting import (
    check_tree,
)


def tree_fixture():
    """Create a tiny source-supported service-stop path for structural tests.

    Args:
        None.
    Returns:
        Fresh mutable tree fixture; it represents no real manufacturer's advice.
    """
    citation = {
        "evidence_id": "e1",
        "quote": "If E1 persists, stop use and contact service.",
    }
    return {
        "symptom": "E1",
        "applies_to": "Model A",
        "prerequisites": [],
        "root": "check",
        "nodes": [
            {
                "id": "check",
                "kind": "check",
                "text": "Does E1 persist?",
                "citations": [citation],
                "branches": [
                    {
                        "condition": "E1 persists",
                        "next_node": "service",
                        "citations": [citation],
                    }
                ],
            },
            {
                "id": "service",
                "kind": "stop",
                "text": "Stop use and contact service.",
                "citations": [citation],
                "branches": [],
            },
        ],
    }


@pytest.mark.parametrize(
    "failure", ["cycle", "dangling", "duplicate", "unreachable", "terminal_continues"]
)
def test_invalid_tree_rejected(failure):
    """Reject bad topology instead of silently repairing diagnostic instructions.

    Args:
        failure: Invalid shape applied to an otherwise valid fixture.
    Returns:
        None; each corrupted tree must raise ValueError before publication.
    """
    tree = tree_fixture()
    if failure == "cycle":
        tree["nodes"][0]["branches"][0]["next_node"] = "check"
    if failure == "dangling":
        tree["nodes"][0]["branches"][0]["next_node"] = "absent"
    if failure == "duplicate":
        tree["nodes"].append(copy.deepcopy(tree["nodes"][1]))
    if failure == "unreachable":
        node = copy.deepcopy(tree["nodes"][1])
        node["id"] = "other"
        tree["nodes"].append(node)
    if failure == "terminal_continues":
        tree["nodes"][1]["branches"] = copy.deepcopy(tree["nodes"][0]["branches"])
    with pytest.raises(ValueError):
        check_tree(tree)


def test_unmatched_guidance_is_retained_as_rejected(monkeypatch):
    """Keep an unsupported tree out of results through the current generation stage.

    Args:
        monkeypatch: Substitutes only model task execution with one controlled reply.
    Returns:
        None; verifies the real stage preserves a rejected proposal and its reason.
    """
    import json
    from workbench.manual_analysis import generate_faq_and_troubleshooting as generation
    from workbench.data_models.analysis_and_question_models import (
        TroubleshootingGeneration,
    )
    from workbench.job_storage import job_files_and_audit_log as storage

    job = storage.create("manual.pdf", b"fixture")["id"]
    batch = [
        {
            "id": "e1",
            "text": "This source has no such instructions.",
            "page": 2,
            "label": "text",
        }
    ]
    response = TroubleshootingGeneration(troubleshooting=[tree_fixture()])
    monkeypatch.setattr(
        generation, "run_stage", lambda *args, **kwargs: [(batch, response)]
    )
    run = SimpleNamespace(service=SimpleNamespace(output_allowance=lambda *args: 6000))
    accepted = generation.generate_aid(
        job, {"facts": []}, {"items": batch}, run, "troubleshooting"
    )
    saved = json.loads(
        (storage.job_dir(job) / "troubleshooting-complete.json").read_text()
    )
    assert not accepted
    assert saved["rejected"][0]["proposal"]["root"] == "check"
    assert "quotation" in saved["rejected"][0]["reason"]


@pytest.mark.parametrize("kind", ["check", "action", "stop", "unresolved"])
def test_only_unresolved_endpoints_may_omit_source_citations(kind):
    """Separate evidence gaps from instructions without weakening source requirements.

    Args:
        kind: Diagnostic node category under test.
    Returns:
        None; uncited unresolved endpoints pass, while uncited instructions fail.
        An unresolved endpoint with outgoing branches also fails validation.
    """
    from workbench.data_models.analysis_and_question_models import DiagnosticNode

    node = dict(
        id="gap",
        kind=kind,
        text="No next step established from passages examined.",
        citations=[],
        branches=[],
    )
    if kind == "unresolved":
        value = DiagnosticNode.model_validate(node)
        assert value.citations == []
        check_tree(dict(root="gap", nodes=[value.model_dump()]))
        node["branches"] = [
            dict(
                condition="Try another action",
                next_node="gap",
                citations=[dict(evidence_id="e1", quote="Source")],
            )
        ]
        with pytest.raises(ValueError, match="terminate"):
            DiagnosticNode.model_validate(node)
    else:
        with pytest.raises(ValueError, match="require source citations"):
            DiagnosticNode.model_validate(node)


def test_guide_kind_and_lead_role_are_separate_instructions():
    """Explain the two classification fields without accepting roles as guide types.

    Args:
        None; inspects the production prompt and validates independent fixture values.
    Returns:
        None; ensures a warning can support installation but is not a fourth kind.
    """
    from workbench.procedure_guides.generate_manual_procedure_guides import (
        procedure_discovery_prompt,
    )
    from workbench.procedure_guides.procedure_reply_models import ProcedureCandidate
    from workbench.model_prompts.analysis_task_prompts import TREES

    prompt = procedure_discovery_prompt([])
    assert "Use kind for installation, maintenance or troubleshooting" in prompt
    assert "use role separately" in prompt
    assert "do not claim that the entire manual lacks information" in TREES
    lead = dict(
        kind="installation",
        role="warning",
        title="Backup before setup",
        citations=[dict(evidence_id="e1", quote="Back up settings before setup.")],
    )
    assert ProcedureCandidate.model_validate(lead).role == "warning"
    with pytest.raises(ValueError):
        ProcedureCandidate.model_validate({**lead, "kind": "warning"})
