"""Check that the progress display shows only a limited set of accepted facts, not
rejected proposals. The tests also retain the separate request-count and input-
usage stopping limits."""

import pytest
from workbench.job_storage import job_files_and_audit_log as storage
from workbench.agentic_workflow.build_analysis_progress import summarize
from workbench.agentic_workflow.execution import Run
from workbench.agentic_workflow.model_call_allowances import BudgetPause


def test_recent_facts_are_bounded_and_exclude_rejected_proposals():
    """Expose the newest accepted facts without leaking rejected or unfinished output.

    Args:
        None; test storage is isolated from real user documents.
    Returns:
        None; verifies eight newest-first facts with source links and correct allowance.
    """
    job = storage.create("recent.pdf", b"%PDF-fixture")
    path = storage.job_dir(job["id"])
    facts = [
        {
            "name": f"Fact {i}",
            "value": str(i),
            "category": "inspection",
            "applies_to": "all",
            "page": 2,
            "evidence_id": f"e{i}",
        }
        for i in range(12)
    ]
    storage.save(
        path / "facts-checkpoint.json",
        {"facts": facts, "rejected": [{"name": "Rejected"}], "batches_processed": 0},
    )
    result = summarize(path, {"state": job, "audit": []})
    assert result["allowance"] == {"calls": 1000, "input_tokens": 6000000}
    assert [f["name"] for f in result["recent_facts"]] == [
        f"Fact {i}" for i in range(11, 3, -1)
    ]
    assert all(f["page"] == 2 for f in result["recent_facts"])


def test_new_work_allowance_preserves_both_stop_boundaries():
    """Increase useful work per action without eliminating call and input safeguards.

    Args:
        None; a dummy service avoids constructing a live provider.
    Returns:
        None; verifies the 1,000th call boundary and 6,000,000 input-usage boundary.
    """
    job = storage.create("allowance.pdf", b"%PDF-fixture")
    run = Run(job["id"], service=object())
    assert run.limit == 1000
    run.count = 999
    run.check_allowance("text", 1000)
    run.count = 1000
    with pytest.raises(BudgetPause):
        run.check_allowance("text", 1000)
    run.count = 0
    run.reported_input = 5999000
    run.check_allowance("text", 1000)
    with pytest.raises(BudgetPause):
        run.check_allowance("text", 1001)
