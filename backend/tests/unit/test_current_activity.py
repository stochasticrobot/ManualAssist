"""Check that the progress strip shows the work actually recorded for the current
stage. Prepared examples cover running reviews, paused requests and
troubleshooting output without modifying saved work."""

from workbench.job_storage import job_files_and_audit_log as storage
from workbench.agentic_workflow.current_analysis_preview import current_activity


def test_review_strip_uses_actual_proposals_and_checked_pages():
    """Expose the assigned uncertainty, not a generated explanation of model thinking.

    Args:
        None; storage is isolated by the test fixture.
    Returns:
        None; verifies review text, checked source pages and honest paused labels.
    """
    job = storage.create("review.pdf", b"%PDF-fixture")
    state = {
        **job,
        "status": "analyzing",
        "calls": 7,
        "task_progress": {
            "task": "uncertainty_review",
            "completed": 2,
            "pages": [5, 6],
            "current_findings": [
                {"issue": "Is the required voltage specified?", "severity": "review"}
            ],
        },
    }
    message = {"title": "Checking uncertainties", "message": "Checking group"}
    result = current_activity(storage.job_dir(job["id"]), state, "validate", message)
    assert result["kind"] == "uncertainties"
    assert result["items"][0]["value"] == "Is the required voltage specified?"
    assert result["items"][0]["pages"] == [5, 6]
    state["status"] = "paused"
    assert (
        current_activity(storage.job_dir(job["id"]), state, "validate", message)[
            "title"
        ]
        == message["title"]
    )


def test_paused_review_receipt_is_read_without_mutation():
    """Recover the actual last submitted review context when progress points ahead.

    Args:
        None.
    Returns:
        None; verifies exact known-format extraction, unchanged receipt and fallback
        to stage status for a different schema rather than displaying invented checks.
    """
    job = storage.create("older.pdf", b"%PDF-fixture")
    path = storage.job_dir(job["id"])
    receipt = path / "call-001-request.json"
    storage.save(
        receipt,
        {
            "schema": {"title": "TargetedFindingsReview"},
            "prompt": 'Check.\nFindings: [{"index":0,"issue":"Which cable is required?"}]\nSource batch: [{"page":3}]',
        },
    )
    before = receipt.read_bytes()
    state = {
        **job,
        "status": "analyzing",
        "calls": 1,
        "task_progress": {"task": "uncertainty_review", "pages": [99]},
    }
    message = {"title": "Review", "message": "Checking"}
    assert (
        current_activity(path, state, "validate", message)["items"][0]["value"]
        == "Which cable is required?"
    )
    result = current_activity(path, state, "validate", message)
    assert result["items"][0]["pages"] == [3]
    state["status"] = "paused"
    assert (
        current_activity(path, state, "validate", message)["title"]
        == "Last uncertainty checks"
    )
    assert receipt.read_bytes() == before
    storage.save(
        receipt, {"schema": {"title": "FactExtraction"}, "prompt": "Different task"}
    )
    assert current_activity(path, state, "validate", message)["kind"] == "status"


def test_discovery_shows_current_source_group_not_old_facts():
    """Describe discovery honestly before any specific proposal has been produced.

    Args:
        None.
    Returns:
        None; verifies source context, status message and separate extraction mode.
    """
    job = storage.create("discovery.pdf", b"%PDF-fixture")
    state = {
        **job,
        "status": "analyzing",
        "task_progress": {"task": "uncertainties", "pages": [4]},
    }
    message = {"title": "Identify ambiguities", "message": "Source group 2 of 16"}
    result = current_activity(storage.job_dir(job["id"]), state, "validate", message)
    assert result["kind"] == "status" and result["items"][0]["pages"] == [4]
    assert result["items"][0]["value"] == message["message"]
    assert (
        current_activity(storage.job_dir(job["id"]), state, "extract", message)["kind"]
        == "facts"
    )


def test_troubleshooting_preview_checks_sources_and_preserves_checkpoint():
    """Show completed source-checked nodes, never pending or invalid proposals.

    Args:
        None; job storage is isolated by the test fixture.
    Returns:
        None; verifies content, source pages, stage switching and unchanged storage.
    """
    job = storage.create("trees.pdf", b"%PDF-fixture")
    path = storage.job_dir(job["id"])
    stage = path / "troubleshooting-stage.json"
    tree = {
        "symptom": "Does not drain",
        "applies_to": "Model A",
        "prerequisites": [],
        "root": "a",
        "nodes": [
            {
                "id": "a",
                "kind": "action",
                "text": "Check the drain hose.",
                "citations": [{"evidence_id": "e1", "quote": "Check the drain hose."}],
                "branches": [],
            }
        ],
    }
    task = {
        "batch": [{"id": "e1", "page": 16, "text": "Check the drain hose."}],
        "response": {"troubleshooting": [tree]},
    }
    storage.save(stage, {"tasks": [task, {"response": None}]})
    before = stage.read_bytes()
    message = {"title": "Generating", "message": "Source group 2"}
    result = current_activity(path, job, "troubleshooting", message)
    assert result["kind"] == "troubleshooting"
    assert result["items"][0]["name"] == "Does not drain"
    assert result["items"][0]["value"] == "Check the drain hose."
    assert result["items"][0]["pages"] == [16]
    assert result["items"][0]["category"] == "Action"
    assert stage.read_bytes() == before
    assert current_activity(path, job, "faq", message)["kind"] == "status"
    tree["nodes"][0]["citations"][0]["quote"] = "Invented unsupported quotation."
    storage.save(stage, {"tasks": [task]})
    assert current_activity(path, job, "troubleshooting", message)["kind"] == "status"
