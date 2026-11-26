"""Check that a reply with missing or invalid fields gets one recorded correction
attempt and can resume after a pause. Controlled model answers verify that a
second invalid reply remains a failure rather than being silently repaired."""
from fixture_source_choices import local_evidence_reply, fixture_payload

import json
from workbench.model_access.code_owned_source_evidence import evidence_task

import pytest
from workbench.data_models.analysis_and_question_models import FactExtraction
from workbench.model_access.model_requests_and_responses import (
    Capabilities,
    ModelError,
    ModelService,
    Result,
)
from workbench.job_storage import job_files_and_audit_log as storage
from workbench.agentic_workflow.model_call_allowances import BudgetPause
from workbench.agentic_workflow.send_and_record_model_requests import Run
from workbench.agentic_workflow.run_source_group_tasks import run_stage


class CategoryModel:
    """Omit a required fact name before producing a structurally complete answer."""

    provider = "fixture"
    model = "categories"
    capabilities = Capabilities(max_output_tokens=8000)

    def __init__(self, always_invalid=False, malformed=False):
        """Configure whether the fixture can produce a valid corrected answer.

        Args:
            malformed: Emit a missing key quotation mark instead of a missing field.
            always_invalid: Simulate a second validation failure when True.
        Returns:
            None; records calls without network access.
        """
        self.always_invalid = always_invalid
        self.malformed = malformed
        self.calls = []

    @local_evidence_reply
    def generate(self, request):
        """Return a complete JSON response with either missing or present required fields.

        Args:
            request: Actual application request, including correction instructions.
        Returns:
            Fixture response with fixed source quotation and measured token counts.
            The category stays installation; only the required name is supplied on correction.
        """
        self.calls.append(request)
        fact = {
            "category": "installation",
            "name": "Connection",
            "value": "Connect the drain hose.",
            "applies_to": "all",
            "evidence_id": "e1",
            "quote": "Connect the drain hose.",
        }
        invalid = self.always_invalid or len(self.calls) == 1
        if invalid and not self.malformed:
            fact.pop("name")
        text = json.dumps({"facts": [fact]})
        if invalid and self.malformed:
            text = text.replace('"evidence_id":', 'evidence_id":')
        return Result(text, self.provider, self.model, "end_turn", 10, 20)


def prompt(batch):
    """Provide stable test instructions so corrected receipts can be matched exactly.

    Args:
        batch: Original source group used in this task.
    Returns:
        Deterministic text containing the original source data.
    """
    return evidence_task("Extract facts", {}, batch)


@pytest.mark.parametrize("malformed", [False, True])
def test_correction_pause_resume_and_completed_task_replay(malformed):
    """Resume the missing required name without repeating original or accepted work.

    Args:
        malformed: Exercise JSON syntax recovery when true, field recovery otherwise.
    Returns:
        None; verifies one original call, one correction, exact completed-task replay,
        retained original invalid reply, and preserved quotation.
    """
    job = storage.create("category.pdf", b"%PDF-fixture")["id"]
    model = CategoryModel(malformed=malformed)
    service = ModelService({"text": model})
    batches = [
        [{"id": "e1", "text": "Connect the drain hose.", "page": 3, "label": "text"}]
    ]
    with pytest.raises(BudgetPause):
        run_stage(
            job,
            "facts",
            "Extract facts",
            batches,
            prompt,
            FactExtraction,
            Run(job, service=service, limit=1),
            0.75,
        )
    original = (storage.job_dir(job) / "call-001-response.json").read_bytes()
    result = run_stage(
        job,
        "facts",
        "Extract facts",
        batches,
        prompt,
        FactExtraction,
        Run(job, service=service, replay=True, limit=1),
        0.75,
    )
    assert result[0][1].facts[0].category == "installation"
    assert result[0][1].facts[0].quote == batches[0][0]["text"]
    run_stage(
        job,
        "facts",
        "Extract facts",
        batches,
        prompt,
        FactExtraction,
        Run(job, service=service, replay=True, limit=0),
        0.75,
    )
    assert len(model.calls) == 2
    assert ("invalid JSON" if malformed else "facts.0.name") in model.calls[1].prompt
    assert (storage.job_dir(job) / "call-001-response.json").read_bytes() == original


@pytest.mark.parametrize("malformed", [False, True])
def test_second_invalid_response_stops_with_field_detail(malformed):
    """Limit automatic schema correction to one attempt and expose the actual field.

    Args:
        malformed: Exercise syntax failure when true, field failure otherwise.
    Returns:
        None; verifies two total dispatches, a useful message, and no retry loop.
    """
    job = storage.create("invalid.pdf", b"%PDF-fixture")["id"]
    model = CategoryModel(always_invalid=True, malformed=malformed)
    run = Run(job, service=ModelService({"text": model}))
    with pytest.raises(
        ModelError, match="invalid JSON" if malformed else "facts.0.name"
    ):
        run.call("text", evidence_task("Extract", {}, [{"id": "e1", "page": 1, "text": "Connect the drain hose."}]), FactExtraction)
    assert len(model.calls) == 2
