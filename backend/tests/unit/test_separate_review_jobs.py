"""Check that different guide-review questions receive the right information and
allowed answer choices. Controlled replies exercise uncertainty, source
preservation, heading handling and continuation without contacting a model."""

from workbench.procedure_guides import review_batches as batches, review_jobs

import json

import pytest
from pydantic import ValidationError
from workbench.agentic_workflow.model_call_allowances import BudgetPause
from workbench.agentic_workflow.execution import Run
from workbench.job_storage import job_files_and_audit_log as storage
from workbench.model_access.model_requests_and_responses import (
    Capabilities,
    ModelService,
    Result,
)
from workbench.procedure_guides import reviewer as review

TABLE = "| Problem | Remedy |\n| --- | --- |\n| Lock | Hold the blue key for three seconds. |\n| Noise | Clean the fan if clogged. |\n"


def fixture_guide():
    """Create a complete task with unrelated table content and a separate warning.

    Args:
        None.
    Returns:
        Guide, original sources and assigned task used to verify routing, not model
        accuracy. The real preparation code must retain the separate prerequisite.
    """
    sources = [
        {"id": "table", "text": TABLE, "label": "table"},
        {"id": "warning", "text": "Disconnect power before cleaning."},
    ]
    guide = {
        "title": "Lock controls",
        "applies_to": "",
        "prerequisites": [
            {
                "text": sources[1]["text"],
                "citations": [{"evidence_id": "warning", "quote": sources[1]["text"]}],
            }
        ],
        "steps": [
            {
                "id": "lock",
                "instruction": "Hold the blue key for three seconds.",
                "citations": [{"evidence_id": "table", "quote": TABLE}],
            }
        ],
    }
    return (
        guide,
        sources,
        {"title": "Lock controls", "kind": "maintenance", "applicability": ""},
    )


class RecordingOwner:
    """Inspect actual candidate requests with deterministic routing responses."""

    def __init__(self, relevance="required", support="established"):
        """Set fixture verdicts without creating a provider.

        Args:
            relevance: Synthetic routing result for each ambiguous source unit.
            support: Synthetic support result for each reader field.
        Returns:
            None; initializes request and evidence recording for assertions.
        """
        self.requests = []
        self.relevance = relevance
        self.support = support

    def call(self, role, prompt, schema, **kwargs):
        """Validate synthetic replies against the candidate's actual job schema.

        Args:
            role: Ordinary model role.
            prompt: Actual bound request containing original evidence.
            schema: Candidate job's strict schema with inventory validation.
            **kwargs: Normal output limits.
        Returns:
            Validated synthetic reply; assertions inspect job separation and source
            identity, never claim semantic model correctness.
        """
        payload = json.loads(prompt.rsplit("\n", 1)[-1])["task"]
        if schema.__name__ == "ObjectionReply":
            return schema.model_validate(
                {
                    "decisions": [
                        {
                            "objection": c["objection"],
                            "explanation": "Fixture uncertainty remains unresolved.",
                            "verdict": "uncertain",
                            "required_change": "",
                            "reader_positions": [],
                            "citations": [
                                {
                                    "evidence_id": prompt.sources[0]["id"],
                                    "quote": prompt.sources[0]["text"],
                                }
                            ],
                        }
                        for c in payload["reported_defects"]
                    ]
                }
            )
        definitions = schema.model_json_schema()["$defs"]
        stage = (
            "relevance"
            if "RelevanceJudgment" in definitions
            else ("support" if "SupportJudgment" in definitions else "coverage")
        )
        self.requests.append(
            {
                "stage": stage,
                "payload": payload,
                "sources": prompt.sources,
                "schema": schema.model_json_schema(),
            }
        )
        result = (
            self.relevance
            if stage == "relevance"
            else (self.support if stage == "support" else "present")
        )
        judgments = []
        for c in payload["comparisons"]:
            item = {
                "comparison": c["comparison"],
                "explanation": "Fixture judgment only.",
                "result": result,
            }
            if stage == "support":
                item["unsupported_detail"] = (
                    "Invented value." if result == "not_established" else ""
                )
            judgments.append(item)
        return schema.model_validate({"judgments": judgments})


@pytest.mark.parametrize(
    "stage,allowed,forbidden",
    [
        ("relevance", "required", "present"),
        ("coverage", "present", "out_of_scope"),
        ("support", "established", "absent"),
        ("evidence_gap", "established", "out_of_scope"),
    ],
)
def test_job_schema_exposes_only_accepted_decisions(stage, allowed, forbidden):
    """Ensure advertised choices match the local validator for every item.

    Args:
        stage: Narrow job name.
        allowed: A permitted result for that job.
        forbidden: A decision belonging to a different responsibility.
    Returns:
        None; rejects cross-job verdicts and incomplete/duplicate inventories.
    """
    schema = review.job_schema(stage, [{"comparison": 1}, {"comparison": 2}])
    assert forbidden not in json.dumps(schema.model_json_schema())
    for numbers, result in [
        ([1, 2], forbidden),
        ([1], allowed),
        ([1, 1], allowed),
        ([1, 3], allowed),
    ]:
        items = [
            {"comparison": n, "explanation": "Fixture.", "result": result}
            for n in numbers
        ]
        if stage in {"support", "evidence_gap"}:
            for item in items:
                item["unsupported_detail"] = ""
        with pytest.raises(ValidationError):
            schema.model_validate({"judgments": items})


@pytest.mark.parametrize(
    "result,detail",
    [
        ("established", "Wrong quantity."),
        ("not_established", ""),
        ("unclear", "Invented action."),
    ],
)
def test_support_fields_cannot_hide_a_concrete_objection(result, detail):
    """Reject contradictions between verdict and alleged unsupported detail.

    Args:
        result: Deliberately inconsistent support verdict.
        detail: Detail that conflicts with that verdict.
    Returns:
        None; schema validation fails without converting the response to approval.
    """
    with pytest.raises(ValidationError):
        review_jobs.SupportJudgment(
            comparison=1,
            explanation="Fixture.",
            unsupported_detail=detail,
            result=result,
        )


@pytest.mark.parametrize(
    "scope_result", ["required", "out_of_scope", "not_instruction", "unclear"]
)
def test_real_preparation_preserves_accounting_and_separates_inputs(scope_result):
    """Classify sources without leaking the draft into scope or losing warning records.

    Args:
        scope_result: Synthetic relevance result to exercise each routing branch.
    Returns:
        None; every original comparison remains in the audit, uncertainty fails
        closed, support lacks the full draft and separate warnings retain explicit decisions.
    """
    guide, sources, task = fixture_guide()
    owner = RecordingOwner(relevance=scope_result)
    result, audit = review.compare_source_and_guide_behavior(
        guide, sources, owner, task
    )
    assert result.acceptable == (scope_result != "unclear")
    for request in owner.requests:
        assert ("reader_guide" in request["payload"]) == (
            request["stage"] == "coverage"
        )
        assert request["sources"] == sources
        assert request["payload"]["assigned_procedure"]["title"] == task["title"]
        assert all(
            not c.get("scope_check_required") for c in request["payload"]["comparisons"]
        )
    coverage = [r for r in owner.requests if r["stage"] == "coverage"]
    assert any(
        "Disconnect power" in c["statement_to_check"]
        for r in coverage
        for c in r["payload"]["comparisons"]
    )
    entries = audit[0]["coverage"] + audit[0]["support"]
    assert len(entries) == 6
    assert len({i["comparison"] for i in entries}) == 6
    if scope_result == "required":
        assert all(i["stage"] != "relevance" for i in audit[0]["coverage"])
    else:
        assert len([i for i in audit[0]["coverage"] if i["stage"] == "relevance"]) == 3


def test_oversized_jobs_split_without_truncating_source(monkeypatch):
    """Apply the same lossless input limit to relevance as to other jobs.

    Args:
        monkeypatch: Replaces only the input estimator with a controlled boundary.
    Returns:
        None; every requested comparison survives individual splitting, retaining
        the complete original source text and the same response schema choices.
    """

    def estimate(request):
        """Force multi-item requests to split while admitting single-item packets.

        Args:
            request: Actual candidate Request before provider dispatch.
        Returns:
            A controlled estimate based solely on supplied comparison count.
        """
        payload = json.loads(request.prompt.rsplit("\n", 1)[-1])["task"]
        return batches.MAX_REQUEST_INPUT + 1 if len(payload["comparisons"]) > 1 else 1

    monkeypatch.setattr(batches, "estimate_input", estimate)
    guide, sources, task = fixture_guide()
    owner = RecordingOwner()
    result, _ = review.compare_source_and_guide_behavior(guide, sources, owner, task)
    assert result.acceptable
    assert all(
        len(r["payload"]["comparisons"]) == 1 and r["sources"] == sources
        for r in owner.requests
    )


class FixtureProvider:
    """Exercise the normal provider interface without any external requests."""

    provider = "fixture"
    model = "separate-jobs"
    capabilities = Capabilities(max_output_tokens=8000)

    def generate(self, request):
        """Produce complete narrow-job judgments for real Run replay tests.

        Args:
            request: Production request with the candidate's actual response schema.
        Returns:
            Synthetic provider response; verifies accounting/replay, not semantics.
        """
        payload = json.loads(request.prompt.rsplit("\n", 1)[-1])["task"]
        definitions = request.schema["$defs"]
        result = (
            "required"
            if "RelevanceJudgment" in definitions
            else ("established" if "SupportJudgment" in definitions else "present")
        )
        items = [
            {"comparison": c["comparison"], "explanation": "Fixture.", "result": result}
            for c in payload["comparisons"]
        ]
        if result == "established":
            for item in items:
                item["unsupported_detail"] = ""
        return Result(
            json.dumps({"judgments": items}),
            self.provider,
            self.model,
            "complete",
            100,
            100,
        )


def test_run_pause_reuses_exact_successful_relevance(tmp_path, monkeypatch):
    """Resume through production accounting without paying for scope twice.

    Args:
        tmp_path: Isolated job directory.
        monkeypatch: Redirects storage away from real analyses.
    Returns:
        None; a one-call pause retains scope receipts and two remaining calls finish
        coverage/support through the same candidate entry point. No extra allowance.
    """
    monkeypatch.setattr(storage, "JOBS", tmp_path / "jobs")
    guide, sources, task = fixture_guide()
    job = storage.create("fixture", b"fixture")["id"]
    service = ModelService({"text": FixtureProvider()})
    with pytest.raises(BudgetPause):
        review.compare_source_and_guide_behavior(
            guide, sources, Run(job, limit=1, service=service), task
        )
    receipt = storage.job_dir(job) / "call-001-response.json"
    original = receipt.read_bytes()
    owner = Run(job, limit=2, service=service, replay=True)
    result, _ = review.compare_source_and_guide_behavior(guide, sources, owner, task)
    assert result.acceptable and owner.count == 2
    assert receipt.read_bytes() == original


def test_production_review_preserves_directive_headings_and_classifies_topic_labels():
    """Route original heading text without assuming every heading is an obligation.

    Args:
        None; uses an original directive heading and a descriptive table heading
        with the actual production reviewer and controlled model responses.
    Returns:
        None; the directive reaches coverage after required classification, while
        the descriptive label is retained as an audited non-instruction. This checks
        routing, not whether a live model will make the right classification.
    """
    sources = [
        {
            "id": "safety-title",
            "label": "section_header",
            "text": "Disconnect power before cleaning.",
            "section": ["Disconnect power before cleaning."],
        },
        {
            "id": "brush",
            "text": "Wipe the brush.",
            "section": ["Disconnect power before cleaning."],
        },
        {
            "id": "error-title",
            "label": "section_header",
            "text": "Error Messages",
            "section": ["Error Messages"],
        },
        {"id": "table", "label": "table", "text": TABLE, "section": ["Error Messages"]},
    ]
    guide = {
        "title": "Clean the brush and lock controls",
        "steps": [
            {
                "id": "brush",
                "instruction": "Disconnect power before cleaning. Wipe the brush.",
                "citations": [{"evidence_id": "brush", "quote": "Wipe the brush."}],
            },
            {
                "id": "lock",
                "instruction": "Hold the blue key for three seconds.",
                "citations": [{"evidence_id": "table", "quote": TABLE}],
            },
        ],
    }
    requests = []

    class HeadingOwner(RecordingOwner):
        """Supply deterministic scope classifications for two heading types."""

        def call(self, role, prompt, schema, **kwargs):
            """Classify headings while leaving ordinary coverage/support fixtures intact.

            Args:
                role: Production model role.
                prompt: Candidate request with original heading source records.
                schema: Narrow response class.
                **kwargs: Normal output cap and correction options.
            Returns:
                Validated deterministic reply distinguishing a directive from a label.
            """
            payload = json.loads(prompt.rsplit("\n", 1)[-1])["task"]
            if "RelevanceJudgment" not in schema.model_json_schema()["$defs"]:
                return super().call(role, prompt, schema, **kwargs)
            requests.extend(payload["comparisons"])
            return schema.model_validate(
                {
                    "judgments": [
                        {
                            "comparison": c["comparison"],
                            "explanation": "Routing fixture only.",
                            "result": "not_instruction"
                            if c["statement_to_check"] == "Error Messages"
                            else "required",
                        }
                        for c in payload["comparisons"]
                    ]
                }
            )

    owner = HeadingOwner()
    result, audit = review.compare_source_and_guide_behavior(
        guide, [sources[1], sources[3]], owner, document={"items": sources}
    )
    assert result.acceptable
    assert any(
        c["statement_to_check"] == "Disconnect power before cleaning." for c in requests
    )
    assert any(c["statement_to_check"] == "Error Messages" for c in requests)
    assert any(
        c["unit"]["text"] == "Disconnect power before cleaning."
        and c["stage"] == "coverage"
        for c in audit[0]["coverage"]
    )
    assert any(
        c["unit"]["text"] == "Error Messages" and c["stage"] == "relevance"
        for c in audit[0]["coverage"]
    )
