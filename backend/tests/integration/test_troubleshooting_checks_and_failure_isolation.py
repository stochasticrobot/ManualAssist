"""Check that separate troubleshooting checks remain usable without invented links
between them. Controlled replies exercise cross-page reading and confirm that one
malformed guide does not erase unrelated work."""
from fixture_source_choices import local_evidence_reply, fixture_payload

import json
from behavior_review_fixture import confirmed_claims_reply
from behavior_review_fixture import behavior_reply
import pytest
from fastapi.testclient import TestClient
from test_agentic_procedure_guides import ProcedureModel, manual, citation
from test_large_manual_completion_and_resume import InlineWorker
from workbench.agentic_workflow import execution as calls
from workbench.document_search import index as index
from workbench.http_endpoints import background_worker_and_question_lock as runtime
from workbench.http_endpoints.serve_application import app
from workbench.job_storage import job_files_and_audit_log as storage
from workbench.model_access.model_requests_and_responses import ModelService, Result
from workbench.procedure_guides.planner import (
    plan_source_linked_procedure,
)


class ChecksModel(ProcedureModel):
    """Exercise local malformed extraction and useful branch-free investigated guides."""

    @local_evidence_reply
    def generate(self, request):
        """Return malformed checks only; other requests use independent fixture decisions.

        Args:
            request: Production request including the real schema and correction prompt.
        Returns:
            Fixture reply; no network or source modification is performed.
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
        if request.schema["title"] == "TroubleshootingChecksGeneration":
            return Result(
                '{"troubleshooting_checks":[{"symptom":"broken"}]}',
                self.provider,
                self.model,
                "complete",
                100,
                50,
            )
        result = super().generate(request)
        if request.schema["title"] == "ProcedureInspectionDecision":
            body = json.loads(result.text)
            payload = fixture_payload(request)
            if body.get("draft") and payload["task"]["kind"] == "troubleshooting":
                source = (
                    "alarm" if payload["task"]["title"] == "Alarm sounds" else "fault"
                )
                body["draft"]["troubleshooting"] = None
                body["draft"]["independent_checks"] = [
                    dict(
                        symptom="Flashing light",
                        applies_to="Fixture product",
                        instruction=citation(source)["quote"],
                        citations=[citation(source)],
                    )
                ]
                return Result(
                    json.dumps(body), self.provider, self.model, "complete", 100, 50
                )
        return result


def test_http_invalid_check_group_does_not_block_other_guides(monkeypatch):
    """A twice-invalid extraction stays rejected while real guide orchestration finishes.

    Args:
        monkeypatch: Replaces provider, outer executor and embeddings, not orchestration.
    Returns:
        None; asserts saved failures, independent guides, exports and exact failed-call count.
    """
    model = ChecksModel()
    monkeypatch.setattr(
        calls,
        "configured_service",
        lambda: ModelService({"text": model, "vision": model}),
    )
    monkeypatch.setattr(runtime, "WORKER", InlineWorker())
    monkeypatch.setattr(index, "build", lambda job, document: [])
    with TestClient(app) as client:
        job = storage.create("independent-checks.pdf", b"fixture")["id"]
        path = storage.job_dir(job)
        storage.save(path / "document.json", manual())
        storage.update(job, status="parsed")
        assert client.post(f"/api/jobs/{job}/analyze").status_code == 200
        assert storage.state(job)["status"] == "ready", storage.state(job)
        profile = client.get(f"/api/jobs/{job}").json()["profile"]
        progress = client.get(f"/api/jobs/{job}").json()["workflow"]["guide_progress"]
        assert {group["kind"] for group in progress} == {
            "installation",
            "troubleshooting",
            "maintenance",
        }
        assert all(
            group["finished"] == group["total"] and group["total"] > 0
            for group in progress
        )
        assert profile["guidance_rejected_count"] == 1
        assert profile["troubleshooting"] == []
        assert profile["troubleshooting_checks"] == []
        assert {"installation", "maintenance", "troubleshooting"} == {
            g["kind"] for g in profile["procedure_guides"]
        }
        guides = [
            g for g in profile["procedure_guides"] if g["kind"] == "troubleshooting"
        ]
        assert guides and all(
            g["independent_checks"] and g["troubleshooting"] is None for g in guides
        )
        receipts = [
            p
            for p in path.glob("call-*-request.json")
            if json.loads(p.read_text())["schema"]["title"]
            == "TroubleshootingChecksGeneration"
        ]
        assert len(receipts) == 2
        stage = json.loads((path / "troubleshooting_checks-stage.json").read_text())
        assert stage["tasks"][0]["failure"] and stage["complete"]
        before = {p.name: p.read_bytes() for p in path.glob("call-*.json")}
        # Completed jobs cannot restart via Resume; replaying the production stage also costs no calls.
        assert client.post(f"/api/jobs/{job}/resume").status_code == 409
        from workbench.manual_analysis.generate_faq_and_troubleshooting import (
            generate_aid,
        )

        generate_aid(
            job,
            profile,
            manual(),
            calls.Run(job, service=ModelService({"text": model}), replay=True),
            "troubleshooting_checks",
        )
        assert before == {p.name: p.read_bytes() for p in path.glob("call-*.json")}


class ContinuationModel(ProcedureModel):
    """Choose a real neighbour read and search before finishing a cross-page question."""

    @local_evidence_reply
    def generate(self, request):
        """Select retrieval actions based on observed tool results, not direct document access.

        Args:
            request: Production planner or review request with its current evidence window.
        Returns:
            A supported path only when the continuation was actually retrieved, otherwise checks.
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
        payload = fixture_payload(request)
        if request.schema["title"] == "GuideBehaviorComparison":
            body = behavior_reply(request)
        elif not payload["observations"]:
            body = dict(
                action="read_source",
                evidence_id="seed",
                question="What follows a failed restart?",
                reason="Read the continuation and neighbouring passages.",
            )
        elif not any(
            o["action"] == "search_parsed_document" for o in payload["observations"]
        ):
            body = dict(
                action="search_parsed_document",
                query="restart fails",
                question="Is a next step documented elsewhere?",
                reason="Search beyond the current source group.",
            )
        else:
            sources = {s["id"]: s for s in payload["sources"]}
            c = dict(evidence_id="seed", quote=sources["seed"]["text"])
            proposed = dict(
                outcome="partial",
                title="No power",
                applies_to="Fixture",
                prerequisites=[],
                steps=[],
                schedule=None,
                independent_checks=[
                    dict(
                        symptom="No power",
                        applies_to="Fixture",
                        instruction=c["quote"],
                        citations=[c],
                    )
                ],
                troubleshooting=None,
                unanswered_questions=[
                    "No next step established from passages examined if restart fails."
                ],
            )
            if "continuation" in sources:
                c2 = dict(
                    evidence_id="continuation", quote=sources["continuation"]["text"]
                )
                proposed.update(
                    outcome="guide",
                    unanswered_questions=[],
                    independent_checks=[],
                    troubleshooting=dict(
                        symptom="Restart fails",
                        applies_to="Fixture",
                        prerequisites=[],
                        root="check",
                        nodes=[
                            dict(
                                id="check",
                                kind="check",
                                text="Did restart fail?",
                                citations=[c2],
                                branches=[
                                    dict(
                                        condition="Restart fails",
                                        next_node="stop",
                                        citations=[c2],
                                    )
                                ],
                            ),
                            dict(
                                id="stop",
                                kind="stop",
                                text="Stop and contact service.",
                                citations=[c2],
                                branches=[],
                            ),
                        ],
                    ),
                )
            body = dict(
                action="finish",
                reason="Supported instructions and remaining gap established.",
                draft=proposed,
            )
        return Result(json.dumps(body), self.provider, self.model, "complete", 100, 50)


@pytest.mark.parametrize("has_continuation", [True, False])
def test_production_planner_retrieves_continuation_or_keeps_independent_checks(
    has_continuation,
):
    """Check both a real cross-page connection and genuinely missing next-step evidence.

    Args:
        has_continuation: Whether the manual contains an explicit conditional next action.
    Returns:
        None; asserts real retrieval observations, final checked instructions and absent invented edges.
    """
    document = dict(
        pages=2,
        outline=[],
        items=[
            dict(
                id="seed",
                page=1,
                label="text",
                text="If there is no power, restart the device.",
            )
        ],
    )
    document["items"].append(
        dict(
            id="continuation" if has_continuation else "other",
            page=2,
            label="text",
            text="If restart fails, stop and contact service."
            if has_continuation
            else "Clean the outside with a dry cloth.",
        )
    )
    job = storage.create("continuation.pdf", b"fixture")["id"]
    model = ContinuationModel()
    result = plan_source_linked_procedure(
        job,
        dict(
            id="power", kind="troubleshooting", title="No power", evidence_ids=["seed"]
        ),
        document,
        calls.Run(job, service=ModelService({"text": model})),
    )
    state = json.loads(
        (storage.job_dir(job) / "procedure-plans-v3/power.json").read_text()
    )
    assert [o["action"] for o in state["observations"]] == [
        "read_source",
        "search_parsed_document",
    ]
    assert state["observations"][0]["new_evidence_ids"]
    if has_continuation:
        assert (
            result["troubleshooting"]["nodes"][0]["branches"][0]["citations"][0]["page"]
            == 2
        )
        assert not result["independent_checks"]
    else:
        assert result["troubleshooting"] is None
        assert result["independent_checks"][0]["citations"][0]["page"] == 1
        assert result["unanswered_questions"] and result["status"] == "needs_review"


@pytest.mark.parametrize("kind", ["installation", "maintenance"])
def test_ordered_steps_and_independent_checks_are_both_retained(kind):
    """Preserve compatible ordered instructions and additional checks without weakening citations.

    Args:
        kind: Non-troubleshooting guide category affected by the old rejection.
    Returns:
        None; both fields survive source validation, and an invented quotation still fails.
    """
    from test_agentic_procedure_guides import draft
    from workbench.procedure_guides.procedure_reply_models import ProcedureDraft
    from workbench.procedure_guides.validate_procedure_steps import (
        validate_procedure_steps,
    )

    proposal = draft(kind)
    proposal["independent_checks"] = [
        dict(
            symptom="Flashing light",
            applies_to="Fixture product",
            instruction=citation("fault")["quote"],
            citations=[citation("fault")],
        )
    ]
    evidence = {s["id"]: s for s in manual()["items"]}
    result = validate_procedure_steps(
        ProcedureDraft.model_validate(proposal), kind, evidence
    )
    assert (
        len(result["steps"]) == len(proposal["steps"]) and result["independent_checks"]
    )
    proposal["independent_checks"][0]["citations"][0]["quote"] = (
        "An invented instruction."
    )
    with pytest.raises(ValueError, match="quotation"):
        validate_procedure_steps(
            ProcedureDraft.model_validate(proposal), kind, evidence
        )
