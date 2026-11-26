"""Check that a cut-short AI reply causes smaller requests and that completed pieces
survive continuation. Simulated responses exercise actual retry handling without
calling an external service."""
from fixture_source_choices import local_evidence_reply, fixture_payload

import json
import pytest
from workbench.job_storage import job_files_and_audit_log as storage
from workbench.model_access.model_requests_and_responses import (
    Capabilities,
    ModelService,
    ModelError,
    Result,
)
from workbench.data_models.analysis_and_question_models import FactExtraction
from workbench.agentic_workflow.execution import Run
from workbench.agentic_workflow.run_source_group_tasks import run_stage
from workbench.agentic_workflow.model_call_allowances import BudgetPause
from workbench.model_prompts.analysis_task_prompts import facts_prompt


class SplittingModel:
    """Simulate a truncated two-item reply, then complete each smaller task."""

    provider = "fixture"
    model = "split"
    capabilities = Capabilities(max_output_tokens=8000)
    calls = 0

    @local_evidence_reply
    def generate(self, request):
        """Return incomplete output only when a request contains both fixture records.

        Args:
            request: Actual task-runner request with a fact-only response schema.
        Returns:
            Truncated or complete fixture Result, including measured usage. No network.
        """
        self.calls += 1
        items = fixture_payload(request)
        assert request.max_tokens == 6000
        if len(items) > 1:
            return Result(
                '{"facts":[', self.provider, self.model, "max_tokens", 10, 6000
            )
        item = items[0]
        fact = {
            "category": "safety",
            "name": "Instruction",
            "value": item["text"],
            "applies_to": "fixture",
            "evidence_id": item["id"],
            "quote": item["text"],
        }
        return Result(
            json.dumps({"facts": [fact]}), self.provider, self.model, "complete", 10, 30
        )


def test_truncated_task_splits_then_resumes_without_repeating_completed_child():
    """Keep partial output rejected while preserving successful smaller requests.

    Args:
        None; automatic fixtures isolate storage and block real Bedrock clients.
    Returns:
        None; verifies one failed parent and exactly two successful child dispatches,
        unchanged earlier receipt bytes and rejection of a tampered saved task result.
    """
    job = storage.create("tasks.pdf", b"%PDF-fixture")
    path = storage.job_dir(job["id"])
    model = SplittingModel()
    service = ModelService({"text": model})
    batches = [
        [
            {
                "id": f"e{i}",
                "text": f"Disconnect power before operation {i}.",
                "page": 1,
                "label": "text",
            }
            for i in (1, 2)
        ]
    ]
    with pytest.raises(BudgetPause):
        run_stage(
            job["id"],
            "facts",
            "Extract facts",
            batches,
            facts_prompt,
            FactExtraction,
            Run(job["id"], limit=2, service=service),
            0.75,
        )
    previous = (path / "call-002-response.json").read_bytes()
    result = run_stage(
        job["id"],
        "facts",
        "Extract facts",
        batches,
        facts_prompt,
        FactExtraction,
        Run(job["id"], limit=1, service=service, replay=True),
        0.75,
    )
    assert len(result) == 2 and model.calls == 3
    assert (path / "call-002-response.json").read_bytes() == previous
    assert any(e["kind"] == "task_split" for e in storage.events(job["id"]))
    checkpoint = json.loads((path / "facts-stage.json").read_text())
    checkpoint["tasks"][0]["response"]["facts"][0]["value"] = "Changed after acceptance"
    storage.save(path / "facts-stage.json", checkpoint)
    with pytest.raises(ModelError, match="differs"):
        run_stage(
            job["id"],
            "facts",
            "Extract facts",
            batches,
            facts_prompt,
            FactExtraction,
            Run(job["id"], service=service, replay=True),
            0.75,
        )
    assert model.calls == 3


def test_fraction_requires_known_model_limit():
    """Do not treat the old application-wide 8K constant as every provider's limit.

    Args:
        None.
    Returns:
        None; verifies model-dependent fractions and refusal when a limit is unknown.
    """
    model = SplittingModel()
    service = ModelService({"text": model})
    assert service.output_allowance("text", 0.75) == 6000
    model.capabilities = Capabilities(max_output_tokens=32000)
    assert service.output_allowance("text", 0.75) == 24000
    model.capabilities = Capabilities()
    with pytest.raises(ModelError, match="known model output limit"):
        service.output_allowance("text", 0.75)
