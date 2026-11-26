"""Check the stopping rules of the retired preliminary manual preview. A simulated
inspector tests its calculated limits and saved continuation; these checks do not
mean new analyses still run that preview."""
from fixture_source_choices import local_evidence_reply, fixture_payload

import json

import pytest
from workbench.model_access.model_requests_and_responses import (
    Capabilities,
    ModelService,
    Result,
)
from workbench.job_storage import job_files_and_audit_log as storage
from workbench.agentic_workflow.model_call_allowances import BudgetPause
from workbench.agentic_workflow.execution import Run
from workbench.agentic_workflow.choose_document_inspections import investigate
from workbench.agentic_workflow.estimate_inspection_allowance import (
    inspection_allowance,
)


def document():
    """Create a minimal parsed source with a three-action formula allowance.

    Args:
        None.
    Returns:
        One-page document without figures, tables or density additions.
    """
    return {
        "pages": 1,
        "items": [
            {"id": "e1", "page": 1, "label": "text", "text": "Read this source."}
        ],
        "tables": [],
        "figures": [],
        "outline": [],
    }


class Inspector:
    """Request repeated real page reads followed optionally by an explicit finish."""

    provider = "fixture"
    model = "inspector"
    capabilities = Capabilities(max_output_tokens=8000)

    def __init__(self, finish_at=3):
        """Set the action at which the fixture believes inspection is complete.

        Args:
            finish_at: Number of tool results required before finish, or None to never finish.
        Returns:
            None; starts an empty list of actual provider dispatches.
        """
        self.finish_at = finish_at
        self.requests = []

    @local_evidence_reply
    def generate(self, request):
        """Respond to the real inspection prompt without external model access.

        Args:
            request: Production prompt with original navigation and observations.
        Returns:
            Structured decision with known token usage; no tool results are fabricated.
        """
        self.requests.append(request)
        data = fixture_payload(request)
        done = (
            self.finish_at is not None
            and len(data["previous_observations"]) >= self.finish_at
        )
        body = {
            "document_type": "manual",
            "purpose": "understand",
            "action": "finish" if done else "read_page",
            "page": 1,
            "query": "",
            "evidence_id": "",
            "reason": "Inspect the operating instruction.",
        }
        if request.schema["title"] == "InspectionDecision":
            body["remaining_questions"] = (
                [] if done else ["What does the operating instruction say?"]
            )
        return Result(json.dumps(body), self.provider, self.model, "end_turn", 10, 10)


def test_formula_and_sparse_blank_distinction():
    """Count actual complexity signals without treating blank pages as OCR failures.

    Args:
        None.
    Returns:
        None; checks all additive terms, repeated figures, density and exact thresholds.
    """
    doc = document()
    doc["pages"] = 44
    doc["tables"] = [{"id": str(n)} for n in range(14)]
    doc["items"] += [{"id": "dense", "page": 2, "label": "text", "text": "word " * 601}]
    box = {"l": 0, "r": 200, "t": 100, "b": 0}
    doc["figures"] = [
        {"page": 3, "provenance": [{"page_no": 3, "bbox": box}]} for _ in range(4)
    ]
    plan = inspection_allowance(doc)
    assert plan["action_allowance"] == 13  # 2 + 5 + 3 + 1 + 1 + 1
    assert plan["figure_pages"] == [3]
    assert plan["dense_pages"] == [2]
    assert plan["possible_extraction_problem_pages"] == [3]
    assert 4 not in plan["possible_extraction_problem_pages"]


@pytest.mark.parametrize(
    "finish_at,status,actions,calls",
    [
        (0, "inspection_complete", 0, 1),
        (3, "inspection_complete", 3, 4),
        (None, "allowance_reached", 3, 4),
    ],
)
def test_production_stopping_outcomes(finish_at, status, actions, calls):
    """Exercise actual inspection dispatch at early finish and the allowance boundary.

    Args:
        finish_at: Fixture's chosen finishing point, or None.
        status: Expected explicit completion or exhaustion outcome.
        actions: Expected executed inspection count.
        calls: Expected decision requests, including the free-in-actions final choice.
    Returns:
        None; asserts real tool observations, persistence and absence of excess actions.
    """
    job = storage.create("manual.pdf", b"fixture")["id"]
    model = Inspector(finish_at)
    result = investigate(
        job, document(), Run(job, service=ModelService({"text": model}))
    )
    assert result["inspection_status"] == status
    assert len(result["observations"]) == actions
    assert len(model.requests) == calls
    assert bool(result["remaining_questions"]) == (status == "allowance_reached")
    assert json.loads((storage.job_dir(job) / "decisions.json").read_text()) == result


def test_inspection_pause_replay_and_completed_results():
    """Continue inspection without repeated calls and reuse its completed result.

    Args:
        None.
    Returns:
        None; verifies exact replay, unchanged original response and zero-call saved reuse.
    """
    job = storage.create("manual.pdf", b"fixture")["id"]
    model = Inspector(3)
    service = ModelService({"text": model})
    with pytest.raises(BudgetPause):
        investigate(job, document(), Run(job, limit=1, service=service))
    original = (storage.job_dir(job) / "call-001-response.json").read_bytes()
    result = investigate(
        job, document(), Run(job, limit=3, service=service, replay=True)
    )
    assert len(model.requests) == 4
    assert (storage.job_dir(job) / "call-001-response.json").read_bytes() == original
    assert (
        investigate(job, document(), Run(job, limit=0, service=service, replay=True))
        == result
    )
