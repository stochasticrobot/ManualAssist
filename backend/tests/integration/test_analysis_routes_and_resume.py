"""Check that browser analysis requests reach the real processing steps and can reuse
saved answers after a pause. Controlled model replies test routing, evidence
retention and usage records without a network request."""
from fixture_source_choices import local_evidence_reply, fixture_payload

import json
from fastapi.testclient import TestClient
from workbench.job_storage import job_files_and_audit_log as storage
from workbench.agentic_workflow import (
    run_manual_analysis as agent,
    send_and_record_model_requests as calls,
)
from workbench.document_search import index_and_search_parsed_text as knowledge
from workbench.pdf_processing import inspect_parsed_sources as inspection_tools
from workbench.http_endpoints.serve_application import app
from workbench.model_access.model_requests_and_responses import (
    ModelService,
    Capabilities,
    Result,
)


class FixtureModel:
    """Independent provider that asks for a real image tool call before extracting."""

    provider = "independent-fixture"
    model = "offline"
    capabilities = Capabilities(images=True, max_output_tokens=8000)

    @local_evidence_reply
    def generate(self, request):
        """Produce deterministic neutral results keyed by the requested contract.

        Args:
            request: Neutral application request from the actual agent workflow.
        Returns:
            Fixture result; asserts vision dispatch received actual PNG bytes.
        """
        if request.images:
            assert request.images[0].data.startswith(b"\x89PNG")
            text = "A label is visible."
        elif request.schema and request.schema.get("title") == "InspectionDecision":
            previous = (
                "inspect_image" in request.prompt.split("previous_observations", 1)[-1]
            )
            text = json.dumps(
                {
                    "document_type": "fixture manual",
                    "purpose": "Read limits",
                    "action": "finish" if previous else "inspect_image",
                    "reason": "Read the visible label",
                    "page": 1,
                    "query": "",
                    "evidence_id": "",
                }
            )
        elif request.schema and request.schema.get("title") in ("FactExtraction",):
            text = json.dumps(
                {
                    "facts": [
                        {
                            "category": "environment",
                            "name": "Limit",
                            "value": "4–40°C",
                            "applies_to": "fixture",
                            "evidence_id": "e1",
                            "quote": "Use only between 4°C and 40°C.",
                        }
                    ],
                    "findings": [],
                }
            )
        elif request.schema and request.schema.get("title") == "ProcedureCandidates":
            text = json.dumps({"procedures": []})
        elif request.schema and request.schema.get("title") == "UncertaintyCandidates":
            text = json.dumps({"findings": []})
        elif request.schema and request.schema.get("title") == "FAQGeneration":
            text = json.dumps({"faq": []})
        elif (
            request.schema
            and request.schema.get("title") == "TroubleshootingChecksGeneration"
        ):
            text = json.dumps({"troubleshooting_checks": []})
        else:
            text = json.dumps({"claims": [], "insufficient": True})
        if request.schema and request.schema.get("title") == "FactExtraction":
            value = json.loads(text)
            value.pop("findings", None)
            text = json.dumps(value)
        if request.schema and request.schema.get("title") == "InspectionDecision":
            value = json.loads(text)
            value["remaining_questions"] = []
            text = json.dumps(value)
        return Result(text, "independent-fixture", "offline", "complete", 10, 10)


def test_analysis_endpoint_skips_inspection_and_persists_evidence(tmp_path, monkeypatch):
    """Exercise HTTP analysis using fake model/index transport but real agent dispatch.

    Args:
        tmp_path: Isolated pytest filesystem.
        monkeypatch: Fixture for replacing external model/index/render dependencies.
    Returns:
        None; asserts source-anchored publication without preliminary inspection calls.
        Does not prove live provider quality, actual PDF rendering or real Chroma IO.
    """
    monkeypatch.setattr(storage, "JOBS", tmp_path / "jobs")
    monkeypatch.setattr(
        calls,
        "configured_service",
        lambda: ModelService({"text": FixtureModel(), "vision": FixtureModel()}),
    )
    monkeypatch.setattr(
        inspection_tools, "page_image", lambda path, page: b"\x89PNGfixture"
    )
    monkeypatch.setattr(knowledge, "build", lambda job, doc: [{"id": "fixture"}])
    with TestClient(app) as client:
        job = storage.create("fixture.pdf", b"%PDF-fixture")
        item = {
            "id": "e1",
            "text": "Use only between 4°C and 40°C.",
            "page": 1,
            "label": "text",
            "section": [],
            "provenance": [],
        }
        storage.save(
            storage.job_dir(job["id"]) / "document.json",
            {
                "pages": 1,
                "items": [item],
                "outline": [],
                "figures": [],
                "tables": [],
                "parser_status": "success",
            },
        )
        storage.update(job["id"], status="parsed")
        # Execute the production worker synchronously so the test observes settlement.
        from workbench.http_endpoints import (
            background_worker_and_question_lock as app_module,
        )

        class InlineWorker:
            """Execute submitted work immediately within the isolated test."""

            def submit(self, function, *args):
                """Run a worker callback synchronously.

                Args:
                    function: Production worker callback.
                    *args: Callback arguments.
                Returns:
                    Callback result; exceptions propagate to the test.
                """
                return function(*args)

        monkeypatch.setattr(app_module, "WORKER", InlineWorker())
        assert client.post(f"/api/jobs/{job['id']}/analyze").status_code == 200
        result = client.get(f"/api/jobs/{job['id']}").json()
        assert result["state"]["status"] == "ready"
        assert result["profile"]["vision_calls"] == 0
        assert result["profile"]["inspection_status"] == "not_run"
        assert result["workflow"]["inspection_preview"] is None
        assert all(p["id"] != "inspect" for p in result["workflow"]["phases"])
        receipts = sorted(storage.job_dir(job["id"]).glob("call-*-request.json"))
        schemas = [json.loads(p.read_text())["schema"]["title"] for p in receipts]
        assert schemas[0] == "FactExtraction"
        assert "InspectionDecision" not in schemas
        assert not (storage.job_dir(job["id"]) / "decisions.json").exists()
        assert result["profile"]["facts"][0]["page"] == 1
        assert not any(
            e.get("tool") == "inspect_image" and e["kind"] == "tool_result"
            for e in result["audit"]
        )
        assert client.post(f"/api/jobs/{job['id']}/analyze").status_code == 409


def test_checkpoint_resume_reuses_completed_batch(tmp_path, monkeypatch):
    """Verify timeout-style recovery through the same analysis worker with no lost facts.

    Args:
        tmp_path: Private isolated job storage.
        monkeypatch: Model and index overrides; no remote services are invoked.
    Returns:
        None; checks completed responses survive, missing response is regenerated,
        the call ledger persists, and changed checkpoint inputs are rejected.
    """
    from workbench.model_access.model_requests_and_responses import ModelError

    monkeypatch.setattr(storage, "JOBS", tmp_path / "jobs")

    class InterruptedModel(FixtureModel):
        """Finish inspection immediately, then fail the second extraction once."""

        attempts = 0

        @local_evidence_reply
        def generate(self, request):
            """Produce bounded fixtures and one controlled missing-response failure.

            Args:
                request: Neutral production-worker request.
            Returns:
                Fixture response; the second extraction attempt raises ModelError.
            """
            if request.schema.get("title") == "InspectionDecision":
                return Result(
                    json.dumps(
                        {
                            "document_type": "fixture",
                            "purpose": "limits",
                            "action": "finish",
                            "reason": "No inspection needed",
                            "remaining_questions": [],
                            "page": 1,
                            "query": "",
                            "evidence_id": "",
                        }
                    ),
                    self.provider,
                    self.model,
                    "complete",
                    10,
                    10,
                )
            if request.schema.get("title") != "FactExtraction":
                return super().generate(request)
            self.attempts += 1
            if self.attempts == 2:
                raise ModelError("Fixture timeout")
            records = fixture_payload(request)
            item = records[0]
            text = json.dumps(
                {
                    "facts": [
                        {
                            "category": "environment",
                            "name": "Limit",
                            "value": "4–40°C",
                            "applies_to": "fixture",
                            "evidence_id": item["id"],
                            "quote": "Use only between 4°C and 40°C.",
                        }
                    ],
                    "findings": [],
                }
            )
            value = json.loads(text)
            value.pop("findings", None)
            return Result(
                json.dumps(value), self.provider, self.model, "complete", 10, 10
            )

    model = InterruptedModel()
    monkeypatch.setattr(
        calls,
        "configured_service",
        lambda: ModelService({"text": model, "vision": model}),
    )
    monkeypatch.setattr(knowledge, "build", lambda job, doc: [{"id": "fixture"}])
    job = storage.create("fixture.pdf", b"%PDF-fixture")
    path = storage.job_dir(job["id"])
    items = [
        {
            "id": f"e{i}",
            "text": "Use only between 4°C and 40°C. " + "padding " * 480,
            "page": i,
            "label": "text",
            "section": [],
            "provenance": [],
        }
        for i in (1, 2)
    ]
    document = {
        "pages": 2,
        "items": items,
        "outline": [],
        "figures": [],
        "tables": [],
        "parser_status": "success",
    }
    storage.save(path / "document.json", document)
    agent.analyze(job["id"])
    assert storage.state(job["id"])["status"] == "failed"
    # An older saved inspection is retained byte-for-byte when this job resumes.
    historical = {"decisions": [{"document_type": "historical manual", "purpose": "limits"}],
                  "observations": [], "inspection_status": "inspection_complete"}
    storage.save(path / "decisions.json", historical)
    inspection_bytes = (path / "decisions.json").read_bytes()
    previous = (path / "call-001-response.json").read_bytes()
    assert storage.state(job["id"])["unknown_usage_calls"] == 1
    agent.analyze(job["id"], resume=True)
    assert storage.state(job["id"])["status"] == "ready"
    assert len(json.loads((path / "profile.json").read_text())["facts"]) == 2
    assert (path / "decisions.json").read_bytes() == inspection_bytes
    assert json.loads((path / "profile.json").read_text())["document_type"] == "historical manual"
    assert storage.state(job["id"])["calls"] == 9
    assert (path / "call-001-response.json").read_bytes() == previous
    document["items"][0]["text"] = "A different source."
    storage.save(path / "document.json", document)
    before = storage.state(job["id"])["calls"]
    agent.analyze(job["id"], resume=True)
    assert storage.state(job["id"])["status"] == "failed"
    assert storage.state(job["id"])["calls"] == before


def test_model_replay_preserves_usage_and_checks_image_hash(tmp_path, monkeypatch):
    """Verify offline replay cannot spend again or confuse equal-sized image payloads.

    Args:
        tmp_path: Isolated private job storage.
        monkeypatch: Scoped independent provider registry.
    Returns:
        None; checks identical requests replay and changed image bytes invoke anew.
    """
    from workbench.model_access.model_requests_and_responses import Image

    monkeypatch.setattr(storage, "JOBS", tmp_path / "jobs")

    class CountingModel:
        """Minimal independent adapter counting actual dispatched requests."""

        provider = "fixture"
        model = "counter"
        capabilities = Capabilities(images=True, max_output_tokens=8000)
        calls = 0

        @local_evidence_reply
        def generate(self, request):
            """Count the request and return a recognizable answer.

            Args:
                request: Neutral request; never sent to a network.
            Returns:
                Fixture response with known usage.
            """
            self.calls += 1
            return Result("READY", self.provider, self.model, "complete", 5, 1)

    model = CountingModel()
    monkeypatch.setattr(
        calls,
        "configured_service",
        lambda: ModelService({"text": model, "vision": model}),
    )
    job = storage.create("test.pdf", b"%PDF-test")
    run = calls.Run(job["id"])
    assert run.call("text", "hello") == "READY"
    run.replay = True
    assert run.call("text", "hello") == "READY"
    assert model.calls == 1 and storage.state(job["id"])["calls"] == 1
    run.call("vision", "describe", images=(Image(b"abc"),))
    run.call("vision", "describe", images=(Image(b"abc"),))
    assert model.calls == 2
    run.call("vision", "describe", images=(Image(b"xyz"),))
    assert model.calls == 3
