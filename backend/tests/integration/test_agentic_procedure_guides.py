"""Check that a guide-writing investigation can request more text, receive it, and
save or resume its work. A simulated model chooses actions while the real planning
and storage code runs; no live AI judgment is tested."""
from fixture_source_choices import local_evidence_reply, fixture_payload

import hashlib
import json
from behavior_review_fixture import confirmed_claims_reply
from behavior_review_fixture import behavior_reply
import threading
import time

import pytest
from fastapi.testclient import TestClient
from test_large_manual_completion_and_resume import InlineWorker, ManualModel
from workbench.agentic_workflow import run_manual_analysis as analysis
from workbench.agentic_workflow import execution as calls
from workbench.document_search import index as index
from workbench.document_search.find_related_result_guides import (
    find_related_result_guides,
)
from workbench.http_endpoints import background_worker_and_question_lock as runtime
from workbench.http_endpoints.serve_application import app
from workbench.job_storage import job_files_and_audit_log as storage
from workbench.model_access.model_requests_and_responses import ModelService, Result
from workbench.procedure_guides.planner import (
    plan_source_linked_procedure,
)
from workbench.procedure_guides.procedure_reply_models import ProcedureDraft
from workbench.procedure_guides.validate_procedure_steps import validate_procedure_steps


def manual():
    """Supply separated installation, maintenance, diagnostic and safety passages.

    Args:
        None.
    Returns:
        Small parsed-manual fixture with a completion check on a different page.
    """
    rows = [
        ("install", "Connect the inlet hose.", 1),
        ("maintain", "Clean the filter with water.", 1),
        ("fault", "If the light flashes, stop and contact service.", 1),
        ("alarm", "If the alarm sounds, stop and contact service.", 1),
        ("safety", "Disconnect power before working.", 2),
        ("verify", "Check the connection for leaks after installation.", 3),
    ]
    return dict(
        pages=3,
        items=[
            dict(id=i, text=text, page=page, label="text") for i, text, page in rows
        ],
        tables=[],
        figures=[],
        outline=[],
        parser_status="success",
    )


def citation(source):
    """Create an exact fixture quotation, keeping expected source support independent.

    Args:
        source: ID of a source in the fixture manual.
    Returns:
        Evidence ID and verbatim text for checking the production citation validator.
    """
    return dict(
        evidence_id=source,
        quote=next(i["text"] for i in manual()["items"] if i["id"] == source),
    )


def draft(kind):
    """Build complete fixture instructions, with a deliberately unspecified recurrence.

    Args:
        kind: Installation, maintenance or troubleshooting procedure type.
    Returns:
        Proposed guide with exact quotations and a separate safety prerequisite.
    """
    source = {
        "installation": "install",
        "maintenance": "maintain",
        "troubleshooting": "fault",
    }[kind]
    step = dict(
        id="first",
        title="Perform the task",
        instruction=citation(source)["quote"],
        applies_when="Fixture product",
        after_step_ids=[],
        citations=[citation(source)],
        warnings=[
            dict(text=citation("safety")["quote"], citations=[citation("safety")])
        ],
        checks=[dict(text=citation("verify")["quote"], citations=[citation("verify")])]
        if kind == "installation"
        else [],
    )
    tree = dict(
        symptom="Flashing light",
        applies_to="Fixture product",
        prerequisites=[],
        root="stop",
        nodes=[
            dict(
                id="stop",
                kind="stop",
                text=citation("fault")["quote"],
                citations=[citation("fault")],
                branches=[],
            )
        ],
    )
    return dict(
        title={
            "installation": "Install the product",
            "maintenance": "Clean the filter",
            "troubleshooting": "Flashing light",
        }[kind],
        applies_to="Fixture product",
        prerequisites=[
            dict(text=citation("safety")["quote"], citations=[citation("safety")])
        ],
        steps=[] if kind == "troubleshooting" else [step],
        schedule=None,
        troubleshooting=tree if kind == "troubleshooting" else None,
        unanswered_questions=[],
    )


class ProcedureModel(ManualModel):
    """Choose inspections based on received evidence rather than a fixed call number."""

    def __init__(self, reject_review=False):
        """Initialize observed request history and concurrency measurement.

        Args:
            reject_review: Return a concrete unresolved review concern for limit tests.
        Returns:
            None; initializes fixture-only state without provider credentials.
        """
        self.requests = []
        self.lock = threading.Lock()
        self.active = 0
        self.peak = 0
        self.reject_review = reject_review

    @local_evidence_reply
    def generate(self, request):
        """Answer real planning requests using only the supplied fixture evidence.

        Args:
            request: Production prompt and response fields selected by the workflow.
        Returns:
            Neutral fixture response; ordinary earlier stages use the independent
            manual fixture. Planning requires safety and completion passages first.
        """
        if request.schema["title"] == "BehaviorDefectVerification":
            return Result(
                json.dumps(confirmed_claims_reply(request)),
                self.provider,
                self.model,
                "complete",
                10,
                10,
            )
        title = request.schema["title"]
        with self.lock:
            self.requests.append(request)
        if title not in (
            "ProcedureCandidates",
            "OrganizedProcedurePlan",
            "ProcedureInspectionDecision",
            "GuideBehaviorComparison",
        ):
            return super().generate(request)
        with self.lock:
            self.active += 1
            self.peak = max(self.peak, self.active)
        try:
            time.sleep(0.02)
            payload = fixture_payload(request)
            if title == "OrganizedProcedurePlan":
                body = {
                    "procedures": [
                        dict(
                            kind=x["kind"],
                            title=x["title"],
                            lead_ids=[x["id"]],
                            supporting_lead_ids=[],
                            applicability="Fixture product",
                        )
                        for x in payload["leads"]
                    ],
                    "unassigned": [],
                }
            elif title == "ProcedureCandidates":
                ids = {item["id"] for item in payload}
                names = [
                    ("installation", "Install the product", "install"),
                    ("maintenance", "Clean the filter", "maintain"),
                    ("troubleshooting", "Flashing light", "fault"),
                    ("troubleshooting", "Alarm sounds", "alarm"),
                ]
                body = {
                    "procedures": [
                        dict(kind=k, title=t, citations=[citation(i)])
                        for k, t, i in names
                        if i in ids
                    ]
                }
            elif title == "GuideBehaviorComparison":
                assert "evidence_ids" not in payload["task"]
                assert "lead_ids" not in payload["task"]
                assert "safety" in {
                    i["id"]
                    for i in payload["sources"] + payload.get("context_sources", [])
                }
                body = behavior_reply(
                    request,
                    "Model applicability remains unclear."
                    if self.reject_review
                    else None,
                )
            elif not payload["observations"]:
                body = dict(
                    action="search_parsed_document",
                    question="What safety prerequisites apply?",
                    query="Disconnect power",
                    reason="Find safety gotchas before assembling steps.",
                )
            elif not any(o["action"] == "read_page" for o in payload["observations"]):
                body = dict(
                    action="read_page",
                    question="How is completion checked?",
                    page=3,
                    reason="Find the installation completion check on the next page.",
                )
            else:
                assert {"safety", "verify"} <= {i["id"] for i in payload["sources"]}
                proposed = draft(payload["task"]["kind"])
                if payload["task"].get("scope") == "top_level":
                    assert set(payload["task"]["related_symptoms"]) == {
                        "Flashing light",
                        "Alarm sounds",
                    }
                    proposed["title"] = "Troubleshoot from the beginning"
                    proposed["troubleshooting"] = {
                        "symptom": "Start with the displayed symptom",
                        "applies_to": "Fixture product",
                        "prerequisites": [],
                        "root": "choose",
                        "nodes": [
                            {
                                "id": "choose",
                                "kind": "check",
                                "text": "Which documented condition is present?",
                                "citations": [citation("fault"), citation("alarm")],
                                "branches": [
                                    {
                                        "condition": "Light flashes",
                                        "next_node": "light",
                                        "citations": [citation("fault")],
                                    },
                                    {
                                        "condition": "Alarm sounds",
                                        "next_node": "alarm",
                                        "citations": [citation("alarm")],
                                    },
                                ],
                            },
                            {
                                "id": "light",
                                "kind": "stop",
                                "text": citation("fault")["quote"],
                                "citations": [citation("fault")],
                                "branches": [],
                            },
                            {
                                "id": "alarm",
                                "kind": "stop",
                                "text": citation("alarm")["quote"],
                                "citations": [citation("alarm")],
                                "branches": [],
                            },
                        ],
                    }
                elif payload["task"]["title"] == "Alarm sounds":
                    proposed["title"] = "Alarm sounds"
                    proposed["troubleshooting"]["symptom"] = "Alarm sounds"
                    proposed["troubleshooting"]["nodes"][0].update(
                        text=citation("alarm")["quote"], citations=[citation("alarm")]
                    )
                body = dict(
                    action="finish",
                    reason="The supporting steps, warning and check are now available.",
                    draft=proposed,
                )
            return Result(
                json.dumps(body), self.provider, self.model, "complete", 100, 50
            )
        finally:
            with self.lock:
                self.active -= 1


@pytest.mark.parametrize("small_slices", [False, True])
def test_http_procedure_planning_and_resume(monkeypatch, small_slices):
    """Build all guide types through HTTP, proving tool feedback and parallel Resume.

    Args:
        monkeypatch: Replaces only provider, outer worker and vector embedding.
        small_slices: Grant four attempts per explicit slice to force repeated pauses.
    Returns:
        None; asserts source-linked steps, no invented schedule, true overlap,
        original issue-specific output, exact receipt preservation and guide links.
    """
    model = ProcedureModel()
    monkeypatch.setattr(
        calls,
        "configured_service",
        lambda: ModelService({"text": model, "vision": model}),
    )
    monkeypatch.setattr(runtime, "WORKER", InlineWorker())
    monkeypatch.setattr(index, "build", lambda job, document: [])
    if small_slices:
        monkeypatch.setattr(
            analysis,
            "Run",
            lambda job_id, service=None, replay=False: calls.Run(
                job_id, limit=4, service=service, replay=replay
            ),
        )
    with TestClient(app) as client:
        job = storage.create("procedures.pdf", b"fixture")["id"]
        path = storage.job_dir(job)
        storage.save(path / "document.json", manual())
        storage.update(job, status="parsed")
        assert client.post(f"/api/jobs/{job}/analyze").status_code == 200
        previous = {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in path.glob("call-*.json")
        }
        for _ in range(15):
            if storage.state(job)["status"] == "ready":
                break
            assert storage.state(job)["status"] == "paused", storage.state(job)
            assert client.post(f"/api/jobs/{job}/resume").status_code == 200
        assert storage.state(job)["status"] == "ready", storage.state(job)
        profile = json.loads((path / "profile.json").read_text())
        assert len(profile["procedure_guides"]) == 5
        assert all(g["status"] == "source_checked" for g in profile["procedure_guides"])
        top = next(
            g for g in profile["procedure_guides"] if g.get("scope") == "top_level"
        )
        assert len(top["troubleshooting"]["nodes"][0]["branches"]) == 2
        maintenance = next(
            g for g in profile["procedure_guides"] if g["kind"] == "maintenance"
        )
        assert maintenance["schedule"] is None
        installation = next(
            g for g in profile["procedure_guides"] if g["kind"] == "installation"
        )
        assert installation["steps"][0]["checks"][0]["citations"][0]["page"] == 3
        assert installation["prerequisites"][0]["citations"][0]["page"] == 2
        assert model.peak == (4 if small_slices else 5)
        assert all(
            hashlib.sha256((path / name).read_bytes()).hexdigest() == value
            for name, value in previous.items()
        )
        records = [json.loads(p.read_text()) for p in path.glob("call-*-request.json")]
        assert len({json.dumps(r, sort_keys=True) for r in records}) == len(records)
        assert (
            find_related_result_guides(profile, "installation instructions")[0]["id"]
            == installation["id"]
        )
        assert all(r["schema"]["title"] != "InspectionDecision" for r in records)
        assert (
            client.get(f"/api/jobs/{job}/assets/procedure_guides.json").status_code
            == 200
        )
        assert client.post(f"/api/jobs/{job}/procedure-guides").status_code == 409


def test_rejected_review_stays_visible_and_invalid_steps_fail():
    """Require a rejected semantic review and unsupported structure to remain visible.

    Args:
        None; uses isolated real planner files and fixture model responses.
    Returns:
        None; confirms no repeated review of an unchanged draft, explicit gaps, no guessed
        interval, invalid dependencies/quotes rejected and saved-source revalidation.
    """
    job = storage.create("review.pdf", b"fixture")["id"]
    model = ProcedureModel(reject_review=True)
    candidate = dict(
        id="fixture-install",
        kind="installation",
        title="Install the product",
        evidence_ids=["install"],
    )
    result = plan_source_linked_procedure(
        job, candidate, manual(), calls.Run(job, service=ModelService({"text": model}))
    )
    assert result["status"] == "needs_review"
    assert result["review_issues"]
    assert all(
        "Model applicability remains unclear." in issue
        for issue in result["review_issues"][:-1]
    )
    assert "did not change the rejected guide" in result["review_issues"][-1]
    assert (
        sum(r.schema["title"] == "JobReply" for r in model.requests) == 2
    )
    invalid = draft("installation")
    invalid["steps"][0]["after_step_ids"] = ["nonexistent"]
    with pytest.raises(ValueError, match="dependencies"):
        validate_procedure_steps(
            ProcedureDraft.model_validate(invalid),
            "installation",
            {i["id"]: i for i in manual()["items"]},
        )
    invalid = draft("maintenance")
    invalid["schedule"] = dict(
        text="Every month",
        citations=[dict(evidence_id="maintain", quote="Every month")],
    )
    with pytest.raises(ValueError, match="quotation"):
        validate_procedure_steps(
            ProcedureDraft.model_validate(invalid),
            "maintenance",
            {i["id"]: i for i in manual()["items"]},
        )
    before = len(model.requests)
    assert (
        plan_source_linked_procedure(
            job,
            candidate,
            manual(),
            calls.Run(job, service=ModelService({"text": model}), replay=True),
        )
        == result
    )
    assert len(model.requests) == before


def test_saved_manual_guide_build_preserves_existing_results(monkeypatch):
    """Add guides through the dedicated endpoint without re-running prior analysis.

    Args:
        monkeypatch: Replaces provider and worker; all route/planner/storage code is real.
    Returns:
        None; original facts, FAQ, issue trees and human review notes remain equal,
        and only discovery/planning/review models are called by the extension route.
    """
    model = ProcedureModel()
    monkeypatch.setattr(
        calls, "configured_service", lambda: ModelService({"text": model})
    )
    monkeypatch.setattr(runtime, "WORKER", InlineWorker())
    with TestClient(app) as client:
        job = storage.create("saved.pdf", b"fixture")["id"]
        path = storage.job_dir(job)
        storage.save(path / "document.json", manual())
        original = dict(
            document_type="fixture",
            purpose="installation",
            facts=[],
            faq=[],
            troubleshooting=[],
            findings=[],
            visual_observations=[],
            processing_notices=[],
        )
        storage.save(path / "profile.json", original)
        notes = [dict(issue="Human note", status="deferred", note="Retain this")]
        storage.update(job, status="ready", review=notes)
        assert client.post(f"/api/jobs/{job}/procedure-guides").status_code == 200
        assert storage.state(job)["status"] == "ready", storage.state(job)
        published = json.loads((path / "profile.json").read_text())
        assert all(published[key] == value for key, value in original.items())
        assert storage.state(job)["review"] == notes
        assert {r.schema["title"] for r in model.requests} == {
            "ProcedureCandidates",
            "OrganizedProcedurePlan",
            "ProcedureInspectionDecision",
            "JobReply",
        }
        assert client.post(f"/api/jobs/{job}/procedure-guides").status_code == 409
