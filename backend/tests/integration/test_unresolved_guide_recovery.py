"""Check that blocked saved guides can complete review and reach the normal exports
without rewriting accepted neighbours. Controlled model replies exercise the real
recovery process, including revisions and changes in review policy."""

import copy
import json

from fixture_source_choices import fixture_payload, local_evidence_reply
from workbench.job_storage import job_files_and_audit_log as storage
from workbench.model_access.model_requests_and_responses import (
    Capabilities,
    ModelService,
    Result,
)
from workbench.procedure_guides.procedure_reply_models import ProcedureDraft
from workbench.procedure_guides.validate_procedure_steps import validate_procedure_steps
from workbench.procedure_guides.repair_unresolved_manual_guides import (
    repair_unresolved_manual_guides,
)


class RecoveryModel:
    """Script review failures until a real finalization request corrects the draft."""

    provider = "offline"
    model = "recovery-fixture"
    capabilities = Capabilities(max_output_tokens=8000)

    def __init__(self, draft, repairs):
        """Select how many changed revisions the fixture needs before acceptance.

        Args:
            draft: Original supported draft shape, copied before each response.
            repairs: Number of revisions required by scripted review judgments.
        Returns:
            Initialized fixture; no requests or files are created.
        """
        self.draft = draft
        self.repairs = repairs
        self.revisions = 0
        self.coverage_missing = bool(repairs)
        self.requests = []

    @local_evidence_reply
    def generate(self, request):
        """Return changed drafts; the fixture adapter supplies explicit review results.

        Args:
            request: Actual Run request, with finalization adapted for fixture routing.
        Returns:
            Scripted response, not semantic accuracy evidence. Rejects exploration
            and verifies that the previous draft reaches the production finalizer.
        """
        assert '"previous_draft":' in request.prompt
        payload = fixture_payload(request)
        assert not payload["navigation"]["headings"]
        assert payload["review_corrections"]
        duplicated = {
            f"{c['step_id']}: {c['issue']}" for c in payload["review_corrections"]
        }
        assert not duplicated.intersection(payload["problems"])
        assert payload["previous_draft"]["steps"]
        assert payload["review_reference_map"]
        self.revisions += 1
        self.coverage_missing = self.revisions < self.repairs
        draft = copy.deepcopy(self.draft)
        draft["steps"][0]["instruction"] = (
            f"Close the lid. Shake gently{' now' * self.revisions}."
        )
        return Result(
            json.dumps(
                {
                    "action": "finish",
                    "reason": "Fixture targeted correction",
                    "draft": draft,
                }
            ),
            self.provider,
            self.model,
            "end_turn",
            10,
            10,
        )


def prepare_saved_job():
    """Create an unresolved guide beside a previously accepted guide and original source.

    Args:
        None; test fixtures redirect storage to a private temporary directory.
    Returns:
        Job ID, draft and original profile. Both source citations and displayed pages
        pass production validation before the recovery worker is invoked.
    """
    source = {
        "id": "source",
        "text": "Close the lid. Shake gently.",
        "page": 1,
        "label": "text",
    }
    draft = {
        "title": "Clean container",
        "outcome": "guide",
        "applies_to": "Container",
        "prerequisites": [],
        "steps": [
            {
                "id": "s1",
                "title": "Shake",
                "instruction": "Shake gently.",
                "applies_when": "",
                "after_step_ids": [],
                "citations": [{"evidence_id": "source", "quote": source["text"]}],
                "warnings": [],
                "checks": [],
            }
        ],
        "schedule": None,
        "troubleshooting": None,
        "independent_checks": [],
        "unanswered_questions": [],
    }
    evidence = {"source": source}
    guide = {
        **validate_procedure_steps(
            ProcedureDraft.model_validate(draft), "maintenance", evidence
        ),
        "id": "blocked",
        "kind": "maintenance",
        "status": "needs_review",
        "completion": "review_unresolved",
        "review_issues": ["Previous reviewer objection"],
    }
    accepted = {
        **copy.deepcopy(guide),
        "id": "accepted",
        "completion": "finished",
        "status": "source_checked",
        "review_issues": [],
    }
    profile = {
        "facts": [],
        "findings": [],
        "visual_observations": [],
        "procedure_guides": [guide, accepted],
    }
    job = storage.create("fixture.pdf", b"fixture")["id"]
    path = storage.job_dir(job)
    (path / "procedure-plans-v3").mkdir()
    storage.save(path / "profile.json", profile)
    storage.save(
        path / "document.json",
        {"items": [source], "pages": 1, "tables": [], "outline": []},
    )
    storage.save(
        path / "procedure-candidates-v2.json",
        {
            "candidates": [
                {
                    "id": "blocked",
                    "kind": "maintenance",
                    "title": "Clean container",
                    "evidence_ids": ["source"],
                }
            ]
        },
    )
    storage.save(
        path / "procedure-plans-v3/blocked.json",
        {"result": guide, "evidence": evidence, "questions": [], "reviews": 2},
    )
    return job, draft, profile


def test_saved_review_accepts_without_redrafting_and_preserves_other_outputs():
    """Prove re-review acceptance reaches exports without rewriting accepted material.

    Args:
        None; uses the real worker, planner, request owner, reviewer and publisher.
    Returns:
        None; verifies original checkpoint/profile backup, all-guide retention, JSON
        and HTML exports, and zero extra calls on recovery continuation.
    """
    job, draft, original = prepare_saved_job()
    model = RecoveryModel(draft, repairs=0)
    service = ModelService({"text": model})
    path = storage.job_dir(job)
    checkpoint = (path / "procedure-plans-v3/blocked.json").read_bytes()
    repair_unresolved_manual_guides(job, service=service)
    assert storage.state(job)["status"] == "ready", storage.state(job)
    result = json.loads((path / "profile.json").read_text())
    assert result["procedure_guides"][0]["completion"] == "finished"
    assert result["procedure_guides"][1] == original["procedure_guides"][1]
    assert model.revisions == 0
    assert (path / "procedure-plans-v3/blocked.json").read_bytes() == checkpoint
    assert (
        json.loads((path / "procedure-review-recovery.json").read_text())["profile"]
        == original
    )
    assert (
        json.loads((path / "procedure_guides.json").read_text())
        == result["procedure_guides"]
    )
    assert "Clean container" in (path / "report.html").read_text()
    count = storage.state(job)["calls"]
    repair_unresolved_manual_guides(job, resume=True, service=service)
    assert storage.state(job)["calls"] == count


def test_changed_revisions_can_resolve_after_old_two_review_limit():
    """Verify persistent repair can succeed after two rejections, without autoapproval.

    Args:
        None; fixture reviewer rejects until the second changed draft.
    Returns:
        None; verifies three complete reviews and a final accepted published result.
        Scripted judgments establish orchestration, not live semantic reliability.
    """
    job, draft, _ = prepare_saved_job()
    model = RecoveryModel(draft, repairs=2)
    repair_unresolved_manual_guides(job, service=ModelService({"text": model}))
    assert storage.state(job)["status"] == "ready", storage.state(job)
    saved = json.loads(
        (storage.job_dir(job) / "procedure-repairs-v1/blocked.json").read_text()
    )
    assert saved["reviews"] == 3
    assert saved["result"]["completion"] == "finished"
    assert model.revisions == 2


def test_recovery_route_reserves_once_and_resume_routes_to_recovery(monkeypatch):
    """Keep explicit repair and its continuation away from whole-manual extraction.

    Args:
        monkeypatch: Replaces background submission so no asynchronous work runs.
    Returns:
        None; asserts one reserved recovery, duplicate rejection, and Resume routing
        to the same bounded worker without changing the original saved profile.
    """
    from fastapi.testclient import TestClient
    from workbench.http_endpoints.serve_application import app
    from workbench.http_endpoints import background_worker_and_question_lock as runtime
    from workbench.http_endpoints import upload_and_analysis_routes as routes

    job, _, original = prepare_saved_job()
    storage.update(job, status="ready")
    queued = []
    monkeypatch.setattr(runtime.WORKER, "submit", lambda *args: queued.append(args))
    monkeypatch.setattr(
        routes, "analysis_preflight", lambda document: {"blocker": None}
    )
    client = TestClient(app)
    assert client.post(f"/api/jobs/{job}/repair-guide-reviews").status_code == 200
    assert client.post(f"/api/jobs/{job}/repair-guide-reviews").status_code == 409
    assert queued == [(repair_unresolved_manual_guides, job)]
    storage.update(job, status="paused")
    assert client.post(f"/api/jobs/{job}/resume").status_code == 200
    assert queued[-1] == (repair_unresolved_manual_guides, job, True)
    assert json.loads((storage.job_dir(job) / "profile.json").read_text()) == original


def test_changed_policy_archives_old_recovery_and_rechecks_only_blocked_guides():
    """Keep policy upgrades from silently accepting stale results or erasing history.

    Args:
        None; creates a legacy recovery checkpoint beside the original planner state.
    Returns:
        None; old files survive byte-for-byte in history, the blocked draft is newly
        reviewed, and its accepted sibling is neither redrafted nor changed.
    """
    job, draft, original = prepare_saved_job()
    path = storage.job_dir(job)
    legacy = {"policy": "legacy", "profile": original, "targets": []}
    storage.save(path / "procedure-review-recovery.json", legacy)
    (path / "procedure-repairs-v1").mkdir()
    prior = json.loads((path / "procedure-plans-v3/blocked.json").read_text())
    prior["evidence"]["removed-citation"] = {
        "id": "removed-citation", "text": "Shake gently.", "page": 1, "label": "text"
    }
    document = json.loads((path / "document.json").read_text())
    document["items"].append(prior["evidence"]["removed-citation"])
    storage.save(path / "document.json", document)
    prior["review_required_source_ids"] = ["removed-citation"]
    old = json.dumps(prior).encode()
    (path / "procedure-repairs-v1/blocked.json").write_bytes(old)
    model = RecoveryModel(draft, repairs=0)
    repair_unresolved_manual_guides(
        job, resume=True, service=ModelService({"text": model})
    )
    assert storage.state(job)["status"] == "ready", storage.state(job)
    archive = next((path / "procedure-review-recovery-history").iterdir())
    assert (archive / "procedure-repairs-v1/blocked.json").read_bytes() == old
    assert (
        json.loads((archive / "procedure-review-recovery.json").read_text()) == legacy
    )
    profile = json.loads((path / "profile.json").read_text())
    assert profile["procedure_guides"][0]["completion"] == "finished"
    assert profile["procedure_guides"][1] == original["procedure_guides"][1]
    assert model.revisions == 0

    saved = json.loads((path / "procedure-repairs-v1/blocked.json").read_text())
    assert "removed-citation" in saved["review_required_source_ids"]
    coverage = saved["behavior_reviews"][-1][0]["coverage"]
    assert any(row["source_id"] == "removed-citation" for row in coverage)
