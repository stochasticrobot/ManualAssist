"""Reject invalid troubleshooting branches while reading model replies, so the
existing single correction attempt receives the exact node and rule that failed.
These offline cases reproduce the shape of failed live guides without copying
private manuals or pretending to test a real model's judgment."""

import copy
import json

import pytest
from fixture_source_choices import local_evidence_reply
from workbench.model_access.code_owned_source_evidence import evidence_task
from pydantic import ValidationError

from workbench.agentic_workflow.execution import Run
from workbench.data_models.analysis_and_question_models import TroubleshootingTree
from workbench.job_storage import job_files_and_audit_log as storage
from workbench.model_access.model_requests_and_responses import (
    Capabilities, ModelError, ModelService, Result,
)
from workbench.procedure_guides.procedure_reply_models import ProcedureFinalization
from test_faq_and_tree_validation import tree_fixture


@pytest.mark.parametrize("kind", ["action", "stop", "unresolved", "check"])
def test_invalid_branches_rejected_before_guide_review(kind):
    """Catch every invalid kind/branch pairing inside the final guide response.

    Args:
        kind: Terminal kind with branches, or a check without branches.
    Returns:
        None; verifies nested validation names the faulty node, without mutating it.
    """
    tree = tree_fixture()
    node = tree["nodes"][0]
    node["kind"] = kind
    if kind == "check":
        node["branches"] = []
    payload = dict(reason="Finish", draft=dict(
        title="Diagnostic guide", applies_to="Model A", prerequisites=[], steps=[],
        schedule=None, troubleshooting=tree, unanswered_questions=[],
    ))
    original = copy.deepcopy(payload)
    with pytest.raises(ValidationError, match="Diagnostic node 'check'") as error:
        ProcedureFinalization.model_validate(payload)
    assert error.value.errors()[0]["loc"] == ("draft", "troubleshooting", "nodes", 0)
    assert payload == original


@pytest.mark.parametrize("kind", ["action", "stop", "unresolved"])
def test_valid_graph_is_preserved(kind):
    """Keep a branching check and a legitimate endpoint unchanged.

    Args:
        kind: Supported terminal kind under test.
    Returns:
        None; checks that response parsing does not rewrite accepted graphs.
    """
    tree = tree_fixture()
    tree["nodes"][1]["kind"] = kind
    assert TroubleshootingTree.model_validate(tree).model_dump() == tree


class BranchModel:
    """Return a terminal node with branches, then optionally correct its kind."""

    provider = "fixture"
    model = "branch-correction"
    capabilities = Capabilities(max_output_tokens=8000)

    def __init__(self, always_invalid):
        """Choose whether the single correction succeeds.

        Args:
            always_invalid: Keep returning the invalid node when true.
        Returns:
            None; initializes an offline request log.
        """
        self.always_invalid = always_invalid
        self.calls = []

    @local_evidence_reply
    def generate(self, request):
        """Supply controlled replies through the real model execution boundary.

        Args:
            request: Production request, including schema and correction feedback.
        Returns:
            Measured fixture reply; performs no network call or local output repair.
        """
        self.calls.append(request)
        tree = tree_fixture()
        if len(self.calls) == 1 or self.always_invalid:
            tree["nodes"][0]["kind"] = "action"
        return Result(json.dumps(tree), self.provider, self.model, "end_turn", 10, 20)


@pytest.mark.parametrize("always_invalid", [False, True])
def test_node_error_uses_one_recorded_correction(always_invalid):
    """Exercise real parsing and bounded correction, not just a helper validator.

    Args:
        always_invalid: Verify that a second bad reply remains a visible failure.
    Returns:
        None; verifies precise feedback, retained original reply, two calls maximum,
        schema instructions delivered to the provider, and no silent node rewriting.
    """
    job = storage.create("branches.pdf", b"%PDF-fixture")["id"]
    model = BranchModel(always_invalid)
    run = Run(job, service=ModelService({"text": model}))
    prompt = evidence_task("Create a source-supported diagnostic path.", {}, [
        dict(id="e1", page=1, text="If E1 persists, stop use and contact service.")
    ])
    if always_invalid:
        with pytest.raises(ModelError, match="single correction attempt also failed"):
            run.call("text", prompt, TroubleshootingTree)
    else:
        result = run.call("text", prompt, TroubleshootingTree)
        assert result.model_dump() == tree_fixture()
    assert len(model.calls) == 2
    assert "Diagnostic node 'check'" in model.calls[1].prompt
    assert "branches=[]" in model.calls[1].prompt
    properties = model.calls[0].schema["$defs"]["DiagnosticNode"]["properties"]
    assert "at least one" in properties["branches"]["description"]
    original = json.loads((storage.job_dir(job) / "call-001-response.json").read_text())
    assert json.loads(original["text"])["nodes"][0]["kind"] == "action"
