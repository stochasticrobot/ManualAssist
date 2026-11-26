"""Check that the analysis preview reports planned work and observed progress without
rejecting a manual solely for its total text length. The test uses prepared
records and does not start model work."""

from workbench.job_storage import job_files_and_audit_log as storage
from workbench.agentic_workflow.build_analysis_progress import summarize, action_summary


def test_large_document_plan_has_no_document_size_rejection():
    """Plan a long Unicode source without truncation or a whole-document ceiling.

    Args:
        None.
    Returns:
        None; proves every original character is represented in bounded requests,
        not that a live model can interpret the source correctly.
    """
    from workbench.manual_analysis.estimate_fact_extraction_work import (
        build_batches,
        analysis_preflight,
    )

    text = "温度条件40°C。" * 15000
    document = {
        "items": [{"id": "e1", "text": text, "label": "text", "page": 1, "section": []}]
    }
    plan = analysis_preflight(document)
    assert plan["blocker"] is None
    assert plan["source_characters"] > 100000
    batches = build_batches(document["items"])
    recovered = {}
    for batch in batches:
        for item in batch:
            for offset, char in enumerate(item["text"], item.get("source_offset", 0)):
                recovered[offset] = char
    assert "".join(recovered[i] for i in range(len(text))) == text


def test_summary_progress_estimates_and_actual_target(tmp_path):
    """Keep progress and rough estimates anchored to saved extraction evidence.

    Args:
        tmp_path: Private receipt/checkpoint directory.
    Returns:
        None; verifies source metadata wins over an agent's claimed page,
        extraction completion follows checkpoint, and remaining estimates reach zero.
    """
    document = {
        "items": [
            {
                "id": "e1",
                "text": "Operating temperature 4–40°C.",
                "label": "text",
                "page": 27,
                "section": ["Flexible zone"],
            }
        ]
    }
    result = {
        "document": document,
        "state": {
            "status": "analyzing",
            "stage": "Extracting batch 1 of 1",
            "calls": 2,
        },
        "audit": [],
    }
    view = summarize(tmp_path, result)
    assert view["phases"][0]["status"] == "running"
    assert view["estimate"]["input_range"][1] > view["estimate"]["input_range"][0] > 0
    assert view["estimate"]["output_range"] is None
    target = action_summary(
        {
            "action": "inspect_table",
            "evidence_id": "e1",
            "page": 12,
            "reason": "Cycle guide",
        },
        document,
    )
    assert target["page"] == 27 and "Flexible zone" in target["target"]
    assert target["reason"] == "Cycle guide"
    storage.save(
        tmp_path / "facts-checkpoint.json",
        {"batches_processed": 1, "facts": [], "rejected": []},
    )
    view = summarize(tmp_path, result)
    assert view["phases"][0]["status"] == "complete"
    assert view["estimate"]["input_range"] == [0, 0]
    assert view["estimate"]["output_range"] == [0, 0]
