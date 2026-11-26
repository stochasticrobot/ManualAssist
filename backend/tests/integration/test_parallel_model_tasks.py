"""Check that independent analysis tasks can overlap while results, failures and
usage limits remain correctly recorded. Controlled delayed replies test actual
scheduling and recovery without sending requests to a provider."""
from fixture_source_choices import local_evidence_reply, fixture_payload

import hashlib
import json
import threading
import time
from collections import Counter

import pytest
from fastapi.testclient import TestClient
from test_large_manual_completion_and_resume import InlineWorker, ManualModel
from workbench.agentic_workflow import send_and_record_model_requests as calls
from workbench.agentic_workflow.model_call_allowances import BudgetPause
from workbench.agentic_workflow.run_source_group_tasks import run_stage
from workbench.data_models.analysis_and_question_models import FactExtraction
from workbench.document_search import index_and_search_parsed_text as index
from workbench.http_endpoints import background_worker_and_question_lock as runtime
from workbench.http_endpoints.serve_application import app
from workbench.job_storage import job_files_and_audit_log as storage
from workbench.manual_analysis.review_uncertainties_with_targeted_sources import (
    reconcile,
)
from workbench.model_access.model_requests_and_responses import (
    ModelError,
    ModelService,
    Result,
)
from workbench.model_prompts.analysis_task_prompts import facts_prompt


class OverlapModel(ManualModel):
    """Measure simultaneous transport calls with deterministic offline responses."""

    def __init__(self, fail=False, barrier=False):
        """Prepare transport counters and optional first-window failure synchronization.

        Args:
            fail: Fail the e0 fact request after all first-window calls have entered.
            barrier: Require three concurrent entrants for the first three calls.
        Returns:
            None; initializes only local test state, without network access.
        """
        self.lock = threading.Lock()
        self.active = 0
        self.peak = Counter()
        self.entered = 0
        self.fail = fail
        self.barrier = threading.Barrier(3) if barrier else None

    @local_evidence_reply
    def generate(self, request):
        """Delay fixture responses so true transport overlap can be observed.

        Args:
            request: Actual production request; prompt and schema are not substituted.
        Returns:
            Fixture response, or one explicit transport failure. Counters are always
            released, including failure paths; no actual model quality is measured.
        """
        title = request.schema["title"]
        with self.lock:
            self.active += 1
            self.entered += 1
            ordinal = self.entered
            self.peak[title] = max(self.peak[title], self.active)
        try:
            if self.barrier and ordinal <= 3:
                self.barrier.wait(timeout=3)
            if (
                self.fail
                and title == "FactExtraction"
                and any(s['id']=='e0' for s in request.prompt.sources)
            ):
                raise ModelError("Fixture transport failure")
            time.sleep(0.025)
            if title == "TargetedFindingsReview":
                findings = fixture_payload(request)["findings"]
                body = {
                    "assessments": [
                        {
                            "index": f["index"],
                            "disposition": "false_positive",
                            "evidence_effect": "refutes_proposal",
                            "reason": "Complete fixture instruction",
                            "citations": [
                                {"evidence_id": "e0", "quote": "Disconnect power."}
                            ],
                            "search_queries": [],
                        }
                        for f in findings
                    ]
                }
                return Result(
                    json.dumps(body), self.provider, self.model, "complete", 100, 50
                )
            return super().generate(request)
        finally:
            with self.lock:
                self.active -= 1


def source_batches(count):
    """Create small independent source groups for scheduling and replay tests.

    Args:
        count: Number of distinct source groups required by the scenario.
    Returns:
        Ordered one-item groups with stable citations and no external data.
    """
    return [
        [{"id": f"e{i}", "text": "Disconnect power.", "page": i + 1, "label": "text"}]
        for i in range(count)
    ]


def execute_facts(job, batches, run):
    """Use the production stage runner with real fact prompts and response validation.

    Args:
        job: Isolated job receiving normal stage checkpoints and receipts.
        batches: Independent fixture source groups.
        run: Real call owner with the test's bounded allowance and fixture service.
    Returns:
        Completed ordered task pairs or the production failure/pause exception.
    """
    return run_stage(
        job, "facts", "Extract facts", batches, facts_prompt, FactExtraction, run, 0.75
    )


def test_http_production_workflow_overlaps_independent_stages(monkeypatch):
    """Observe concurrent transport through actual HTTP start and full orchestration.

    Args:
        monkeypatch: Isolates transport, vector embedding and outer worker only.
    Returns:
        None; proves peak six for all four independent source stages, unique
        receipts and exact token accounting. No live-provider speed claim is made.
    """
    model = OverlapModel()
    monkeypatch.setattr(
        calls,
        "configured_service",
        lambda: ModelService({"text": model, "vision": model}),
    )
    monkeypatch.setattr(runtime, "WORKER", InlineWorker())
    monkeypatch.setattr(index, "build", lambda job, document: [])
    with TestClient(app) as client:
        job = storage.create("parallel.pdf", b"fixture")["id"]
        items = [
            dict(batch[0], text="Source text. " * 150) for batch in source_batches(30)
        ]
        storage.save(
            storage.job_dir(job) / "document.json",
            {
                "items": items,
                "pages": 30,
                "tables": [],
                "figures": [],
                "outline": [],
                "parser_status": "success",
            },
        )
        storage.update(job, status="parsed")
        assert client.post(f"/api/jobs/{job}/analyze").status_code == 200
        state = storage.state(job)
        assert state["status"] == "ready", state
        for title in (
            "FactExtraction",
            "UncertaintyCandidates",
            "FAQGeneration",
            "TroubleshootingChecksGeneration",
        ):
            assert model.peak[title] == 6
        assert model.peak["InspectionDecision"] == 0
        requests = list(storage.job_dir(job).glob("call-*-request.json"))
        responses = list(storage.job_dir(job).glob("call-*-response.json"))
        assert len(requests) == len(responses) == state["calls"]
        assert state["input_tokens"] == 100 * state["calls"]
        assert state["output_tokens"] == 50 * state["calls"]
        assert state["active_model_calls"] == []


def test_failure_saves_later_successes_and_resume_only_sends_missing_tasks():
    """Preserve non-prefix completions when an earlier parallel request fails.

    Args:
        None; isolated storage and blocked Bedrock are automatic fixtures.
    Returns:
        None; proves the next window was not sent, later replies were checkpointed,
        and Resume preserves their bytes while retrying only unfinished work.
    """
    job = storage.create("failure.pdf", b"fixture")["id"]
    path = storage.job_dir(job)
    model = OverlapModel(fail=True, barrier=True)
    service = ModelService({"text": model})
    with pytest.raises(ModelError, match="Fixture transport failure"):
        execute_facts(job, source_batches(6), calls.Run(job, service=service, concurrency=3))
    assert model.entered == 3
    saved = json.loads((path / "facts-stage.json").read_text())
    assert [t["response"] is not None for t in saved["tasks"]] == [
        False,
        True,
        True,
        False,
        False,
        False,
    ]
    receipts = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in path.glob("call-*.json")
    }
    model.fail = False
    results = execute_facts(
        job, source_batches(6), calls.Run(job, service=service, replay=True)
    )
    assert model.entered == 7
    assert [batch[0]["id"] for batch, _ in results] == [f"e{i}" for i in range(6)]
    assert all(
        hashlib.sha256((path / name).read_bytes()).hexdigest() == value
        for name, value in receipts.items()
    )
    assert storage.state(job)["unknown_usage_calls"] == 1
    assert storage.state(job)["active_model_calls"] == []


@pytest.mark.parametrize("budget", ["calls", "input"])
def test_parallel_reservations_never_exceed_allowance(monkeypatch, budget):
    """Exercise simultaneous budget admission against call and input-token ceilings.

    Args:
        monkeypatch: Sets a small input allowance for its matching scenario.
        budget: Either attempted calls or estimated input-token allowance.
    Returns:
        None; exactly two attempts dispatch and both responses survive the pause.
    """
    job = storage.create("budget.pdf", b"fixture")["id"]
    model = OverlapModel()
    if budget == "input":
        monkeypatch.setattr(calls, "estimate_input", lambda request: 10)
        monkeypatch.setattr(calls, "MAX_INPUT_TOKENS", 20)
    run = calls.Run(
        job,
        service=ModelService({"text": model}),
        limit=2 if budget == "calls" else 100,
    )
    with pytest.raises(BudgetPause):
        execute_facts(job, source_batches(6), run)
    assert run.count == model.entered == storage.state(job)["calls"] == 2
    saved = json.loads((storage.job_dir(job) / "facts-stage.json").read_text())
    assert sum(t["response"] is not None for t in saved["tasks"]) == 2


def test_independent_review_groups_overlap_and_merge_progress():
    """Run three independent finding groups without racing their saved coverage.

    Args:
        None; uses the production reconciler, validators and receipt machinery.
    Returns:
        None; all 17 findings close locally in three overlapping calls, and all
        group records survive the merged progress write and zero-call replay.
    """
    job = storage.create("review.pdf", b"fixture")["id"]
    model = OverlapModel(barrier=True)
    service = ModelService({"text": model})
    findings = [
        {
            "issue": f"Is instruction {i} incomplete?",
            "severity": "review",
            "evidence_ids": ["e0"],
        }
        for i in range(17)
    ]
    document = {"items": source_batches(1)[0]}
    profile = {"findings": findings}
    result = reconcile(job, profile, document, calls.Run(job, service=service))
    assert model.peak["TargetedFindingsReview"] == 3
    assert model.entered == 3 and result["findings"] == []
    progress = json.loads(
        (storage.job_dir(job) / "finding-review-progress.json").read_text()
    )
    assert len(progress["checks"]) == 17
    replay = reconcile(
        job, profile, document, calls.Run(job, service=service, replay=True)
    )
    assert replay == result and model.entered == 3


def test_six_workers_refill_while_the_first_request_is_still_running():
    """Require a seventh task to start before a slow first task can finish.

    Args:
        None; isolated storage prevents any interaction with the live manual.
    Returns:
        None; proves continuous refilling through the production task runner, not
        merely peak concurrency inside a six-task window. Checks all receipts too.
    """
    released = threading.Event()

    class RefillModel(OverlapModel):
        """Hold the first request until a later task uses a freed worker slot."""

        @local_evidence_reply
        def generate(self, request):
            """Use request evidence to synchronize independent transport calls.

            Args:
                request: Original fact task with a stable source ID in its prompt.
            Returns:
                Fixture reply; raises if the scheduler waits for the slow window.
            """
            if any(s['id']=='e6' for s in request.prompt.sources):
                released.set()
            if any(s['id']=='e0' for s in request.prompt.sources):
                assert released.wait(3), 'A free slot did not admit the seventh task'
            return super().generate(request)

    job = storage.create('refill.pdf', b'fixture')['id']
    model = RefillModel()
    result = execute_facts(job, source_batches(12), calls.Run(job, service=ModelService({'text':model})))
    assert len(result) == 12 and released.is_set()
    assert storage.state(job)['calls'] == 12
    assert len(list(storage.job_dir(job).glob('call-*-response.json'))) == 12


def test_usable_results_are_published_before_uncertainty_requests(monkeypatch):
    """Observe publication from inside the production uncertainty model request.

    Args:
        monkeypatch: Replaces only model and vector transports and the outer executor.
    Returns:
        None; proves guides/reports and a search manifest exist while review is still
        pending, without falsely setting the entire analysis to ready.
    """
    observed = []

    class PublishedResultsModel(ManualModel):
        """Inspect actual saved artifacts at the moment uncertainty work begins."""

        @local_evidence_reply
        def generate(self, request):
            """Check publication order before returning ordinary fixture analysis text.

            Args:
                request: Real production-stage request with its declared output fields.
            Returns:
                Fixture response; fails if uncertainty work blocks publication.
            """
            if request.schema['title'] == 'UncertaintyCandidates':
                path = next(storage.JOBS.iterdir())
                profile = json.loads((path/'profile.json').read_text())
                assert profile['review_pending'] is True
                assert (path/'faq.json').exists() and (path/'procedure_guides.json').exists()
                assert (path/'chunks.json').exists()
                state = storage.state(path.name)
                assert state['status'] == 'analyzing' and state['results_available']
                observed.append(True)
            return super().generate(request)

    model = PublishedResultsModel()
    monkeypatch.setattr(calls,'configured_service',lambda:ModelService({'text':model,'vision':model}))
    monkeypatch.setattr(runtime,'WORKER',InlineWorker())
    monkeypatch.setattr(index,'build',lambda job,document:[])
    with TestClient(app) as client:
        job=storage.create('publish-first.pdf',b'fixture')['id']
        storage.save(storage.job_dir(job)/'document.json',dict(items=source_batches(1)[0],pages=1,outline=[],tables=[],figures=[],parser_status='success'))
        storage.update(job,status='parsed')
        assert client.post(f'/api/jobs/{job}/analyze').status_code==200
        assert storage.state(job)['status']=='ready'
        assert observed
