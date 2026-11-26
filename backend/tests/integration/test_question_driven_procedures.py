"""Check that guide investigations work for different kinds of tasks and stop when
more searching adds no useful evidence. A simulated software-setup example
exercises real planning and storage without assuming every manual is for an
appliance."""
from fixture_source_choices import local_evidence_reply, fixture_payload

import json
import pytest
from workbench.agentic_workflow.model_call_allowances import BudgetPause
from behavior_review_fixture import confirmed_claims_reply
from behavior_review_fixture import behavior_reply

from fastapi.testclient import TestClient
from test_large_manual_completion_and_resume import InlineWorker
from workbench.agentic_workflow.send_and_record_model_requests import Run
from workbench.agentic_workflow import send_and_record_model_requests as calls
from workbench.http_endpoints import background_worker_and_question_lock as runtime
from workbench.http_endpoints.serve_application import app
from workbench.job_storage import job_files_and_audit_log as storage
from workbench.model_access.model_requests_and_responses import (
    Capabilities,
    ModelService,
    Result,
)
from workbench.procedure_guides.plan_source_linked_procedures import (
    plan_source_linked_procedure,
)


class SoftwareManualModel:
    """Supply setup leads, merge synonymous tasks, attach a warning and inspect a gap."""

    provider = "offline"
    model = "software-manual"
    capabilities = Capabilities(max_output_tokens=8000)

    @local_evidence_reply
    def generate(self, request):
        """Respond only to the real guide-generation request types.

        Args:
            request: Neutral production request; sources determine the fixture answer.
        Returns:
            Deterministic structured reply. Unexpected stages fail the test instead
            of silently providing a canned response unrelated to the request.
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
        data = fixture_payload(request)
        title = request.schema["title"]
        quote = {
            "evidence_id": "setup",
            "quote": "Run the installer for your operating system.",
        }
        if title == "ProcedureCandidates":
            body = {
                "procedures": [
                    dict(
                        kind="installation",
                        title=name,
                        role="procedure",
                        citations=[quote],
                    )
                    for name in ("Install the application", "Set up the software")
                ]
                + [
                    dict(
                        kind="installation",
                        title="Back up existing settings",
                        role="warning",
                        citations=[
                            {
                                "evidence_id": "backup",
                                "quote": "Back up existing settings before setup.",
                            }
                        ],
                    )
                ]
            }
        elif title == "OrganizedProcedurePlan":
            body = {
                "procedures": [
                    dict(
                        kind="installation",
                        title="Set up the application",
                        lead_ids=[
                            x["id"] for x in data["leads"] if x["role"] == "procedure"
                        ],
                        supporting_lead_ids=[
                            x["id"] for x in data["leads"] if x["role"] == "warning"
                        ],
                        applicability="Choose the installer for the operating system",
                    )
                ],
                "unassigned": [],
            }
        elif title == "ProcedureInspectionDecision":
            if not data["observations"]:
                body = dict(
                    action="read_page",
                    page=2,
                    question="How do I verify setup?",
                    questions=[
                        dict(
                            question="How do I verify setup?",
                            status="unresolved",
                            answer="",
                            evidence_ids=[],
                        )
                    ],
                    reason="Find the documented completion check",
                )
            else:
                assert "verify" in {x["id"] for x in data["sources"]}
                body = dict(
                    action="finish",
                    reason="The manual supports this short sequence",
                    questions=[
                        dict(
                            question="How do I verify setup?",
                            status="supported",
                            answer="Open the application and check the version.",
                            evidence_ids=["verify"],
                        )
                    ],
                    draft=dict(
                        title="Set up the application",
                        applies_to="Selected operating system",
                        prerequisites=[
                            dict(
                                text="Back up settings",
                                citations=[
                                    dict(
                                        evidence_id="backup",
                                        quote="Back up existing settings before setup.",
                                    )
                                ],
                            )
                        ],
                        steps=[
                            dict(
                                id="install",
                                title="Run installer",
                                instruction=quote["quote"],
                                applies_when="Use the installer for your OS",
                                after_step_ids=[],
                                citations=[quote],
                                warnings=[],
                                checks=[
                                    dict(
                                        text="Check the installed version",
                                        citations=[
                                            dict(
                                                evidence_id="verify",
                                                quote="Open the application and check the version.",
                                            )
                                        ],
                                    )
                                ],
                            )
                        ],
                        schedule=None,
                        troubleshooting=None,
                        unanswered_questions=[],
                    ),
                )
        elif title == "GuideBehaviorComparison":
            body = behavior_reply(request)
        else:
            raise AssertionError(title)
        return Result(json.dumps(body), self.provider, self.model, "complete", 100, 50)


def test_software_setup_guide_only_http_consolidates_and_keeps_interactive_steps(
    monkeypatch,
):
    """Build a software install assistant from three leads via the real HTTP action.

    Args:
        monkeypatch: Overrides only transport and the outer executor; storage is isolated.
    Returns:
        None; proves all leads map to one guide, supporting warnings stay attached,
        question feedback reaches planning, optional review advice is nonblocking,
        and old results remain unchanged. This is not live generalization evidence.
    """
    monkeypatch.setattr(runtime, "WORKER", InlineWorker())
    monkeypatch.setattr(
        calls,
        "configured_service",
        lambda: ModelService({"text": SoftwareManualModel()}),
    )
    with TestClient(app) as client:
        job = storage.create("software-setup.pdf", b"fixture")["id"]
        path = storage.job_dir(job)
        items = [
            dict(id=i, text=t, page=p, label="text")
            for i, t, p in [
                ("setup", "Run the installer for your operating system.", 1),
                ("backup", "Back up existing settings before setup.", 1),
                ("verify", "Open the application and check the version.", 2),
            ]
        ]
        storage.save(
            path / "document.json",
            dict(
                items=items,
                pages=2,
                outline=[],
                tables=[],
                figures=[],
                parser_status="success",
            ),
        )
        original = dict(
            document_type="software manual",
            purpose="setup",
            facts=[],
            faq=[],
            troubleshooting=[],
            findings=[],
            visual_observations=[],
            processing_notices=[],
        )
        storage.save(path / "profile.json", original)
        storage.update(job, status="ready")
        assert client.post(f"/api/jobs/{job}/procedure-guides").status_code == 200
        assert storage.state(job)["status"] == "ready", storage.state(job)
        profile = json.loads((path / "profile.json").read_text())
        assert all(profile[k] == v for k, v in original.items())
        assert profile["procedure_discovery"]["available_leads"] == 3
        assert profile["procedure_discovery"]["candidates"] == 1
        guide = profile["procedure_guides"][0]
        assert guide["status"] == "source_checked"
        assert guide["steps"][0]["checks"][0]["citations"][0]["page"] == 2
        assert guide["prerequisites"][0]["citations"][0]["evidence_id"] == "backup"
        assert guide["question_ledger"][0]["status"] == "supported"
        assert guide["review_suggestions"] == []
        # Conditions travel with their instruction, not as a separate support query.
        assert len(list(path.glob("call-*-request.json"))) == 6


class RepeatingModel(SoftwareManualModel):
    """Deliberately repeat an unproductive search until forced to report a gap."""

    @local_evidence_reply
    def generate(self, request):
        """Exercise the production no-progress guard, not a fixture-only stop limit.

        Args:
            request: Planner or review request from the actual procedure loop.
        Returns:
            A repeated request or an explicit insufficient-evidence draft once the
            application signals that further investigation must stop.
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
        data = fixture_payload(request)
        if request.schema["title"] == "GuideBehaviorComparison":
            body = behavior_reply(request)
        elif data["force_finish"]:
            body = dict(
                action="finish",
                reason="No new evidence found",
                draft=dict(
                    outcome="insufficient_evidence",
                    title="Maintenance",
                    applies_to="Unknown",
                    prerequisites=[],
                    steps=[],
                    schedule=None,
                    troubleshooting=None,
                    unanswered_questions=[
                        "The manual does not provide this procedure."
                    ],
                ),
            )
        else:
            body = dict(
                action="search_parsed_document",
                query="missing interval",
                question="Is an interval documented?",
                reason="Find the source",
            )
        return Result(json.dumps(body), self.provider, self.model, "complete", 100, 50)


def test_repeated_search_stops_with_explicit_gap_and_reuses_saved_result():
    """Prove identical reads are suppressed and an honest no-guide result survives Resume.

    Args:
        None; automatic fixtures isolate storage and prohibit paid providers.
    Returns:
        None; verifies one executed request, bounded model calls, visible gaps and
        no additional calls when the completed result is loaded again.
    """
    job = storage.create("gaps.pdf", b"fixture")["id"]
    candidate = dict(
        id="maintenance",
        kind="maintenance",
        title="Maintenance",
        evidence_ids=["source"],
    )
    doc = dict(
        pages=1,
        outline=[],
        items=[dict(id="source", page=1, label="text", text="Read this manual.")],
    )
    service = ModelService({"text": RepeatingModel()})
    result = plan_source_linked_procedure(
        job, candidate, doc, Run(job, service=service)
    )
    assert result["outcome"] == "insufficient_evidence"
    assert result["status"] == "needs_review"
    state = json.loads(
        (storage.job_dir(job) / "procedure-plans-v3/maintenance.json").read_text()
    )
    assert len(state["request_keys"]) == 1
    assert state["no_new_evidence"] == 2
    assert storage.state(job)["calls"] == 3
    assert (
        plan_source_linked_procedure(
            job, candidate, doc, Run(job, service=service, replay=True)
        )
        == result
    )
    assert storage.state(job)["calls"] == 3


def test_organization_repairs_missing_lead_without_losing_original_evidence():
    """Require one targeted repair when the organizer silently omits a warning.

    Args:
        None; uses real request receipts with a deliberately incomplete fixture reply.
    Returns:
        None; verifies full lead accounting, retained source IDs and checkpoint reuse
        with no repeated organization requests after successful validation.
    """
    from workbench.procedure_guides.consolidate_source_linked_tasks import (
        consolidate_source_linked_tasks,
    )

    class OmittingOrganizer(SoftwareManualModel):
        """Omit support once, then acknowledge the explicit missing-reference feedback."""

        attempts = 0

        @local_evidence_reply
        def generate(self, request):
            """Return a bad plan once and a complete plan on the bounded correction.

            Args:
                request: Original or corrected production organization request.
            Returns:
                A neutral model result; asserts correction contains the missing ID.
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
            self.attempts += 1
            data = fixture_payload(request)
            if self.attempts == 2:
                assert request.schema["title"] == "OrganizationPlacementCorrection"
                assert [lead["choice"] for lead in data["flagged_leads"]] == [2]
                return Result(json.dumps({"placements": [{"lead_choice": 2,
                    "supporting_task_choices": [1]}]}), self.provider, self.model, "complete", 100, 50)
            body = dict(
                procedures=[
                    dict(
                        kind="installation",
                        title="Set up software",
                        applicability="Software",
                        lead_ids=["task"],
                        supporting_lead_ids=[] if self.attempts == 1 else ["warning"],
                    )
                ],
                unassigned=[],
            )
            return Result(
                json.dumps(body), self.provider, self.model, "complete", 100, 50
            )

    job = storage.create("organize.pdf", b"fixture")["id"]
    leads = [
        dict(
            id="task",
            kind="installation",
            role="procedure",
            title="Setup",
            evidence_ids=["a"],
        ),
        dict(
            id="warning",
            kind="installation",
            role="warning",
            title="Backup",
            evidence_ids=["b"],
        ),
    ]
    model = OmittingOrganizer()
    service = ModelService({"text": model})
    with pytest.raises(BudgetPause):
        consolidate_source_linked_tasks(job, leads, Run(job, service=service, limit=1))
    assert model.attempts == 1
    candidates, unassigned = consolidate_source_linked_tasks(
        job, leads, Run(job, service=service, replay=True)
    )
    assert candidates[0]["evidence_ids"] == ["a", "b"]
    assert not unassigned
    assert model.attempts == 2
    assert consolidate_source_linked_tasks(
        job, leads, Run(job, service=service, replay=True)
    ) == (candidates, unassigned)
    assert model.attempts == 2


def test_partial_question_is_retained_as_a_gap_after_review():
    """Preserve a partly answered question instead of failing schema validation.

    Args:
        None; uses a neutral fixture with one sourced but incomplete answer.
    Returns:
        None; confirms partial is a valid ledger state and prevents a clean
        source_checked result while the remaining question is unresolved.
    """

    class PartialModel(RepeatingModel):
        """Finish immediately with an explicit partial-evidence result."""

        @local_evidence_reply
        def generate(self, request):
            """Return a partially answered question and a reviewed partial guide.

            Args:
                request: Actual planner or reviewer request.
            Returns:
                Structured fixture response without any provider connection.
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
            if request.schema["title"] == "GuideBehaviorComparison":
                body = behavior_reply(request)
            else:
                body = dict(
                    action="finish",
                    reason="Only part of the answer is documented",
                    questions=[
                        dict(
                            question="Which interval and replacement schedule apply?",
                            status="partial",
                            answer="Cleaning is weekly; replacement is unspecified.",
                            evidence_ids=["source"],
                        )
                    ],
                    draft=dict(
                        outcome="partial",
                        title="Maintenance",
                        applies_to="Fixture",
                        prerequisites=[],
                        steps=[],
                        schedule=None,
                        troubleshooting=None,
                        unanswered_questions=["Replacement interval not established."],
                    ),
                )
            return Result(
                json.dumps(body), self.provider, self.model, "complete", 100, 50
            )

    job = storage.create("partial.pdf", b"fixture")["id"]
    candidate = dict(
        id="partial", kind="maintenance", title="Maintenance", evidence_ids=["source"]
    )
    document = dict(
        pages=1,
        outline=[],
        items=[dict(id="source", text="Clean weekly.", page=1, label="text")],
    )
    result = plan_source_linked_procedure(
        job,
        candidate,
        document,
        Run(job, service=ModelService({"text": PartialModel()})),
    )
    assert result["question_ledger"][0]["status"] == "partial"
    assert result["status"] == "needs_review"
    assert (
        "Which interval and replacement schedule apply?"
        in result["unanswered_questions"]
    )


def test_bad_review_does_not_cancel_other_guides_and_preserves_validated_draft(
    monkeypatch,
):
    """Isolate exhausted formatting errors inside the production guide scheduler.

    Args:
        monkeypatch: Replaces only the model transport; discovery, organization,
            planner, scheduler, correction and persistence use production code.
    Returns:
        None; proves a failed review retains its draft, later tasks finish even
        with one worker, and failures are reported instead of labelled successful.
    """
    from test_agentic_procedure_guides import ProcedureModel, manual
    from workbench.procedure_guides.generate_manual_procedure_guides import (
        generate_manual_procedure_guides,
    )

    class BadReviewModel(ProcedureModel):
        """Produce invalid review fields only for the installation guide."""

        def generate(self, request):
            """Keep one guide invalid through its single correction, then let siblings run.

            Args:
                request: Real request, including correction attempts.
            Returns:
                Invalid review JSON for installation; normal fixture replies elsewhere.
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
            if (
                request.schema["title"] == "JobReply"
                and 'Connect the inlet hose.' in request.prompt
            ):
                return Result(
                    '{"acceptable":"not a boolean","issues":[]}',
                    self.provider,
                    self.model,
                    "complete",
                    100,
                    50,
                )
            return super().generate(request)

    job = storage.create("local-failure.pdf", b"fixture")["id"]
    model = BadReviewModel()
    run = Run(job, service=ModelService({"text": model}), concurrency=1)
    result = generate_manual_procedure_guides(
        job, {"facts": [], "processing_notices": []}, manual(), run
    )
    guides = result["procedure_guides"]
    failed = [g for g in guides if g.get("generation_failed")]
    assert len(failed) == 1
    assert failed[0]["kind"] == "installation"
    assert failed[0]["steps"] and not failed[0]["model_reviewed"]
    assert failed[0]["status"] == "needs_review"
    assert sum(g["status"] == "source_checked" for g in guides) == 4
    assert run.dispatch_error is None
    assert result["processing_notices"]
    assert not result["procedure_generation_pending"]
