"""Check that grouping several review questions does not drop source text, separate
prerequisites or unresolved comparisons. Controlled replies also verify that
continuation reuses completed requests instead of paying for them again."""

import hashlib
import json
import pytest
from pydantic import ValidationError
from workbench.procedure_guides.prepare_batched_guide_review import prepare_comparisons
from workbench.procedure_guides.review_actions_with_code_owned_evidence import (
    batch_schema,
    compare_source_and_guide_behavior,
    text_units,
)
from workbench.model_access.model_requests_and_responses import (
    ModelService,
    Capabilities,
    Result,
)
from workbench.agentic_workflow.send_and_record_model_requests import Run
from workbench.agentic_workflow.model_call_allowances import BudgetPause
from workbench.job_storage import job_files_and_audit_log as storage

TABLE = "| Problem | Solution |\n| --- | --- |\n| Noise | Turn off the robot, then clean the brush. |\n| Charging | Wipe the charging contacts. |\n"


def test_scope_retains_separate_prerequisite_and_all_support_context():
    """Select only an exact symptom row while retaining a separately cited warning.

    Args:
        None; uses two distinct original source records and a structured guide.
    Returns:
        None; the complete matched row and separate prerequisite are obligations,
        while the unrelated table row remains unchanged in the original evidence.
    """
    sources = [
        {"id": "table", "text": TABLE, "label": "table", "page": 2},
        {"id": "warning", "text": "Disconnect power before cleaning.", "page": 1},
    ]
    guide = {
        "independent_checks": [
            {
                "symptom": "Noise",
                "instruction": "Clean the brush.",
                "citations": [{"evidence_id": "table", "quote": TABLE}],
            }
        ],
        "prerequisites": [
            {
                "text": "Disconnect power before cleaning.",
                "citations": [{"evidence_id": "warning", "quote": sources[1]["text"]}],
            }
        ],
    }
    before = json.dumps(sources)
    comparisons, scope, problems = prepare_comparisons(guide, sources, text_units)
    coverage = [c for c in comparisons if c["kind"] == "coverage"]
    assert len(coverage) == 3 and not problems
    assert any("Turn off" in c["statement_to_check"] for c in coverage)
    assert any("Disconnect power" in c["statement_to_check"] for c in coverage)
    assert not any("charging contacts" in c["statement_to_check"] for c in coverage)
    assert scope[0]["mode"] == "exact_symptom_rows"
    assert json.dumps(sources) == before


def test_ambiguous_table_reference_keeps_every_row():
    """Avoid deciding relevance from invented synonyms or partial keyword matches.

    Args:
        None; a broad symptom label does not exactly identify one original row.
    Returns:
        None; both rows require explicit scope decisions and the fallback is explicit in the audit.
    """
    guide = {
        "independent_checks": [
            {
                "symptom": "Various problems",
                "instruction": "Check the robot.",
                "citations": [{"evidence_id": "table", "quote": TABLE}],
            }
        ]
    }
    comparisons, scope, _ = prepare_comparisons(
        guide, [{"id": "table", "text": TABLE, "label": "table"}], text_units
    )
    assert len([c for c in comparisons if c["kind"] == "coverage"]) == 3
    assert scope[0]["mode"] == "ambiguous_table_scope_review"


@pytest.mark.parametrize("numbers", [[], [1, 1], [1, 3]])
def test_batch_requires_each_comparison_exactly_once(numbers):
    """Reject partial, duplicate and invented accounting before accepting a review.

    Args:
        numbers: Deliberately invalid returned comparison numbers.
    Returns:
        None; the normal response validator raises, enabling bounded correction.
    """
    schema = batch_schema(
        [{"comparison": 1, "kind": "coverage"}, {"comparison": 2, "kind": "support"}]
    )
    with pytest.raises(ValidationError):
        schema.model_validate(
            {
                "judgments": [
                    {"comparison": n, "result": "present", "explanation": "Fixture."}
                    for n in numbers
                ]
            }
        )


def test_batch_rejects_wrong_kind_result():
    """Prevent a support verdict from masquerading as a coverage decision.

    Args:
        None; supplies a valid enum value for the wrong comparison kind.
    Returns:
        None; invalid decision is rejected rather than converted into approval.
    """
    schema = batch_schema([{"comparison": 1, "kind": "coverage"}])
    with pytest.raises(ValidationError):
        schema.model_validate(
            {
                "judgments": [
                    {
                        "comparison": 1,
                        "result": "established",
                        "explanation": "Fixture.",
                    }
                ]
            }
        )


class ReviewFixture:
    """Inspect actual production requests and return fixed routing judgments."""

    provider = "fixture"
    model = "batched-review"
    capabilities = Capabilities(max_output_tokens=8000)

    def __init__(self):
        """Initialize recording without contacting a provider.

        Args:
            self: Fixture instance.
        Returns:
            None; starts an empty list of actual request payloads.
        """
        self.requests = []

    def generate(self, request):
        """Respond to real model-visible batches without modifying their inputs.

        Args:
            self: Request-recording fixture.
            request: Production Request with schema and private source bindings.
        Returns:
            Fixed positive judgments for every supplied number. This verifies
            transport/coverage accounting, not language-model semantic quality.
        """
        data = json.loads(request.prompt.rsplit("\n", 1)[-1])["task"]
        self.requests.append(data)
        assert len(data["comparisons"]) <= 6
        kinds = {c["kind"] for c in data["comparisons"]}
        assert len(kinds) == 1
        assert ("reader_guide" in data) == (kinds == {"coverage"})
        assert "private-original" not in str(request.prompt)
        body = {
            "judgments": [
                {
                    "comparison": c["comparison"],
                    "explanation": "Fixture routing only.",
                    "result": "present" if c["kind"] == "coverage" else "established",
                }
                for c in data["comparisons"]
            ]
        }
        return Result(json.dumps(body), self.provider, self.model, "complete", 100, 100)


def test_production_batches_resume_without_repeating_completed_work(
    tmp_path, monkeypatch
):
    """Exercise batching and budget pause through the same Run used by the planner.

    Args:
        tmp_path: Isolated test directory.
        monkeypatch: Redirects all persisted job records for this test.
    Returns:
        None; fourteen comparisons take four requests, completed receipts replay
        unchanged, all source/reader units survive and each result maps to its source.
    """
    monkeypatch.setattr(storage, "JOBS", tmp_path / "jobs")
    source = {
        "id": "private-original",
        "text": " ".join(f"Perform action {n}." for n in range(7)),
        "page": 1,
    }
    guide = {
        "steps": [
            {
                "id": str(n),
                "instruction": f"Perform action {n}.",
                "citations": [{"evidence_id": source["id"], "quote": source["text"]}],
            }
            for n in range(7)
        ]
    }
    job = storage.create("fixture.pdf", b"fixture")["id"]
    model = ReviewFixture()
    service = ModelService({"text": model})
    with pytest.raises(BudgetPause):
        compare_source_and_guide_behavior(
            guide, [source], Run(job, limit=1, service=service)
        )
    receipt = storage.job_dir(job) / "call-001-response.json"
    before = hashlib.sha256(receipt.read_bytes()).hexdigest()
    review, audit = compare_source_and_guide_behavior(
        guide, [source], Run(job, limit=3, service=service, replay=True)
    )
    assert review.acceptable and len(model.requests) == 4
    assert [len(r["comparisons"]) for r in model.requests] == [6, 1, 6, 1]
    assert len(audit[0]["coverage"]) == 7 and len(audit[0]["support"]) == 7
    assert all(c["source_id"] == source["id"] for c in audit[0]["coverage"])
    assert hashlib.sha256(receipt.read_bytes()).hexdigest() == before
