"""Translate controlled test answers into the numbered passage choices the
application expects. These helpers preserve existing test scenarios; they do not
prove that a live AI chooses the right evidence."""

import json
from dataclasses import replace
from functools import wraps
from workbench.model_access.model_requests_and_responses import Result


def fixture_payload(request):
    """Expose scenario records to deterministic tests without altering wire input.

    Args:
        request: Actual production request; bound prompts retain private records.
    Returns:
        Fixture-oriented task data with named source records. Plain legacy requests
        are read unchanged. This accessor must never be used in application code.
    """
    if not hasattr(request.prompt, "sources"):
        return json.loads(request.prompt.split("\n")[-1])
    if request.schema["title"] == "OrganizedProcedurePlan":
        data = json.loads(request.prompt.split("\n")[-1])
        data["leads"] = request.prompt.sources
        return data
    start = request.prompt.index('{"task":')
    data, _ = json.JSONDecoder().raw_decode(request.prompt[start:])
    title = request.schema["title"]
    if title in {"FactExtraction", "UncertaintyCandidates", "ProcedureCandidates"}:
        return request.prompt.sources
    result = dict(data["task"])
    result["sources"] = request.prompt.sources
    result["source"] = request.prompt.sources
    return result


def local_evidence_reply(function):
    """Migrate named fixture responses to selections without changing real providers.

    Args:
        function: Scenario model's generate method.
    Returns:
        Wrapped fixture method; unsupported identities produce invalid choices so
        production validation can reject them. Focused reviewer responses are canned
        routing controls, not live or independently generated semantic evidence.
    """

    @wraps(function)
    def generate(self, request):
        """Dispatch a fixture and encode its selected source locations.

        Args:
            self: Test-only provider with optional rejection flags.
            request: Actual workflow request and its private test bindings.
        Returns:
            Fixture Result in the new wire shape; malformed replies stay malformed.
        """
        title = (request.schema or {}).get("title")
        focused = {
            "RequiredBehaviors",
            "ReaderClaims",
            "RequiredBehaviorAnswer",
            "ClaimSupportAnswer",
            "BatchedProcedureReview",
            "JobReply",
            "ObjectionReply",
        }
        if title in focused:
            data = fixture_payload(request)
            if hasattr(self, "requests"):
                self.requests.append(request)
            if title == "ObjectionReply":
                body = {
                    "decisions": [
                        {
                            "objection": c["objection"],
                            "explanation": "Scripted defect remains.",
                            "verdict": "needs_change",
                            "required_change": c["issue"],
                            "reader_positions": [],
                            "citations": [{"passage": 1}],
                        }
                        for c in data["reported_defects"]
                    ]
                }
            elif title == "JobReply":
                definitions = request.schema["$defs"]
                relevance = "RelevanceJudgment" in definitions
                support = "SupportJudgment" in definitions
                reject = getattr(self, "reject_review", False) or getattr(
                    self, "coverage_missing", False
                )
                result = (
                    "required"
                    if relevance
                    else "established"
                    if support
                    else "absent"
                    if reject
                    else "present"
                )
                explanation = (
                    "Close the lid is missing."
                    if getattr(self, "coverage_missing", False)
                    and not support
                    and not relevance
                    else "Model applicability remains unclear."
                    if reject and not support and not relevance
                    else "Fixture judgment only."
                )
                body = {
                    "judgments": [
                        {
                            "comparison": c["comparison"],
                            "explanation": explanation,
                            "result": result,
                            **({"unsupported_detail": ""} if support else {}),
                        }
                        for c in data["comparisons"]
                    ]
                }
            elif title == "BatchedProcedureReview":
                reject = getattr(self, "reject_review", False) or getattr(
                    self, "coverage_missing", False
                )
                body = {
                    "judgments": [
                        {
                            "comparison": c["comparison"],
                            "explanation": "Close the lid is missing."
                            if getattr(self, "coverage_missing", False)
                            else "Model applicability remains unclear."
                            if reject
                            else "Fixture judgment only.",
                            "result": ("absent" if reject else "present")
                            if c["kind"] == "coverage"
                            else "established",
                        }
                        for c in data["comparisons"]
                    ]
                }
            elif title == "RequiredBehaviors":
                body = {
                    "requirements": [
                        {"behavior": "Fixture required behavior", "passages": [1]}
                    ]
                }
            elif title == "ReaderClaims":
                reader = data["reader_text"][0]
                body = {
                    "claims": [
                        {
                            "statement": reader["text"],
                            "reader_position": reader["position"],
                        }
                    ]
                }
            elif title == "RequiredBehaviorAnswer":
                reject = getattr(self, "reject_review", False) or getattr(
                    self, "coverage_missing", False
                )
                body = {
                    "explanation": "Close the lid is missing."
                    if getattr(self, "coverage_missing", False)
                    else "Model applicability remains unclear."
                    if reject
                    else "Fixture behavior preserved.",
                    "result": "absent" if reject else "present",
                }
            else:
                body = {
                    "explanation": "Fixture support established.",
                    "result": "established",
                }
            return Result(
                json.dumps(body), self.provider, self.model, "complete", 10, 10
            )
        # Legacy scenario providers express drafts as finish decisions. Translate
        # their fixture-only envelope; dedicated finalization tests inspect the
        # actual wire schema and never use this compatibility adapter.
        fixture_request = (
            replace(
                request,
                schema={**request.schema, "title": "ProcedureInspectionDecision"},
            )
            if title == "ProcedureFinalization"
            else request
        )
        result = function(self, fixture_request)
        if not hasattr(request.prompt, "sources"):
            return result
        try:
            body = json.loads(result.text)
        except json.JSONDecodeError:
            return result
        if title == "ProcedureFinalization" and body.get("action") == "finish":
            body = {
                k: v for k, v in body.items() if k in {"reason", "questions", "draft"}
            }
        sources = request.prompt.sources

        def encode(value):
            """Translate only fixture identity fields into request-local selections.

            Args:
                value: Fixture JSON body or nested record.
            Returns:
                New wire-shaped record; factual fields and deliberate bad values stay.
            """
            if isinstance(value, list):
                return [encode(v) for v in value]
            if not isinstance(value, dict):
                return value
            out = {
                k: encode(v)
                for k, v in value.items()
                if k not in {"evidence_id", "evidence_ids", "quote"}
            }
            if "evidence_id" in value:
                identifier = value["evidence_id"]
                matches = [
                    i
                    for i, s in enumerate(sources, 1)
                    if s["id"] == identifier
                    and (not value.get("quote") or value["quote"] in s["text"])
                ]
                out["passage"] = (
                    matches[0] if matches else 0 if not identifier else len(sources) + 1
                )
            if "evidence_ids" in value:
                out["passages"] = [
                    next(
                        (i for i, s in enumerate(sources, 1) if s["id"] == identifier),
                        len(sources) + 1,
                    )
                    for identifier in value["evidence_ids"]
                ]
            for old_key, new_key, multiple in [
                ("lead_id", "lead_choice", False),
                ("lead_ids", "lead_choices", True),
                ("supporting_lead_ids", "supporting_lead_choices", True),
            ]:
                if old_key in value:
                    out.pop(old_key, None)
                    selected = value[old_key] if multiple else [value[old_key]]
                    numbers = [
                        next(
                            (
                                i
                                for i, s in enumerate(sources, 1)
                                if s["id"] == identifier
                            ),
                            len(sources) + 1,
                        )
                        for identifier in selected
                    ]
                    out[new_key] = numbers if multiple else numbers[0]
            return out

        return replace(result, text=json.dumps(encode(body)))

    return generate
