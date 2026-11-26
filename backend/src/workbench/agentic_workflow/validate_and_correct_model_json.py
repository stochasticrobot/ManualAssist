"""Handle AI answers whose required fields are missing, invalid or unreadable.

An answer can arrive successfully but still be unusable by the application. These
helpers explain the problem and prepare one limited request for the model to
correct its answer. They do not invent missing facts or silently rewrite the
original response into something that appears valid."""

import json

from workbench.model_access.model_requests_and_responses import ModelError
from workbench.model_access.parse_model_json import read_json


class ModelJSONError(ModelError):
    """Malformed model JSON eligible for one provider correction, never local repair."""


def validation_message(error):
    """Describe invalid fields without exposing a complete private model response.

    Args:
        error: Field validation failure or ModelJSONError from a structured response.
    Returns:
        Short explanation with field paths and expected values, suitable for the UI.
        At most five errors are included; source passages and credentials are excluded.
    """
    if isinstance(error, ModelJSONError):
        return str(error)
    details = error.errors(include_input=False, include_url=False)
    return "Model response needs correction: " + "; ".join(
        f"{'.'.join(map(str, item['loc']))}: {item['msg']}" for item in details[:5]
    )


def correction_prompt(prompt, text, error):
    """Ask the model to correct invalid fields while retaining source-supported content.

    Args:
        prompt: Original instructions and source evidence.
        text: Original complete but invalid JSON reply, retained in its call receipt.
        error: Field or JSON syntax failure describing the required correction.
    Returns:
        Deterministic correction instructions. The caller still enforces input,
        output and call allowances; this function does not send a model request.
    """
    return (
        prompt
        + "\n\nCorrect the previous response below. "
        + (
            "Use the required fields and value types in the supplied response schema. "
            "Preserve the original descriptive category; unfamiliar labels are valid. "
            "Do not change factual values or quotations to make validation pass. "
            "Do not add unsupported content. Return the complete corrected JSON.\n"
        )
        + (
            "Correct JSON punctuation and quoting without changing source-supported content.\n"
            if isinstance(error, ModelJSONError)
            else ""
        )
        + validation_message(error)
        + "\nPrevious response:\n"
        + text
    )


def parse_response(schema, text):
    """Validate a response, giving malformed JSON a clear non-repairing failure.

    Args:
        schema: Expected Pydantic response type.
        text: Complete response text from a saved or newly completed call.
    Returns:
        Validated response. Field errors remain ValidationError for the bounded
        correction path; malformed JSON raises ModelJSONError for the same one-correction path.
        Neither path edits or fabricates the returned content locally.
    """
    try:
        return schema.model_validate(read_json(text))
    except json.JSONDecodeError as exc:
        raise ModelJSONError(
            f"Model returned invalid JSON at character {exc.pos}: {exc.msg}"
        ) from None


def bounded_correction_prompt(prompt, text, error, schema, system, images=()):
    """Fit a procedure correction without repeating unrelated investigation history.

    Args:
        prompt: Unchanged original request, retained in its receipt.
        text: Complete invalid reply; always included unchanged in the correction.
        error: Original field or JSON validation failure.
        schema: Response schema dictionary used by the original request.
        system: Standing instructions included by the request dispatcher.
        images: Original image payloads included in input accounting.
    Returns:
        Original correction prompt when it fits. Bound evidence requests fail closed
        if the original reply and evidence cannot fit; choices are never renumbered
        or silently deprived of evidence. Oversized legacy procedure corrections
        retain task scope and original source records, omitting navigation/history
        and, only if necessary, unreferenced sources with explicit omission IDs.
        Every source referenced anywhere in the JSON reply is retained unchanged.
        Raises ModelError if this lossless reply/cited-source context still cannot
        fit. Never rewrites replies, invents citations, or raises the input limit.
    """
    from workbench.agentic_workflow.model_call_allowances import (
        MAX_REQUEST_INPUT,
        estimate_input,
    )
    from workbench.model_access.model_requests_and_responses import Request

    def fits(value):
        """Check the entire correction against the same estimate used by dispatch.

        Args:
            value: Candidate correction prompt.
        Returns:
            True only when system, schema and images also fit; performs no IO.
        """
        return (
            estimate_input(Request(value, system, tuple(images), schema=schema))
            <= MAX_REQUEST_INPUT
        )

    original = correction_prompt(prompt, text, error)
    if fits(original):
        return original
    from workbench.model_access.code_owned_source_evidence import EvidencePrompt

    if isinstance(prompt, EvidencePrompt):
        raise ModelError(
            "Correction exceeds the input allowance with its original evidence and reply; "
            "no evidence was removed or renumbered. Original receipts are retained."
        )
    if schema.get("title") not in {
        "ProcedureInspectionDecision",
        "ProcedureEvidenceReview",
    }:
        return original
    try:
        context = json.loads(prompt.rsplit("\n", 1)[-1])
        reply = read_json(text)
    except (ValueError, TypeError):
        raise ModelError(
            "Procedure correction cannot fit with its unchanged reply; original receipts are retained."
        ) from None
    required = set()

    def collect_references(value):
        """Collect citation and question-ledger IDs from all parts of the invalid reply.

        Args:
            value: Parsed reply subtree, including unexpected fields and substeps.
        Returns:
            None; adds IDs to the local required set without editing reply content.
        """
        if isinstance(value, dict):
            if isinstance(value.get("evidence_id"), str):
                required.add(value["evidence_id"])
            if isinstance(value.get("evidence_ids"), list):
                required.update(x for x in value["evidence_ids"] if isinstance(x, str))
            for child in value.values():
                collect_references(child)
        elif isinstance(value, list):
            for child in value:
                collect_references(child)

    collect_references(reply)
    if "guide" in context:
        collect_references(context["guide"])
    task = context.get("task", {})
    compact = {
        "task": {
            k: v for k, v in task.items() if k not in {"id", "lead_ids", "evidence_ids"}
        },
        "sources": list(context.get("sources", [])),
        "omitted_source_ids": [],
    }
    if "guide" in context:
        compact["guide"] = context["guide"]
    instructions = (
        "Correct the structured reply for this task using the original source passages below. "
        "Investigation history and navigation have been omitted; they are not source evidence. "
        "Some unreferenced passages may also be omitted and listed by ID. Do not invent evidence "
        "for omitted passages. Preserve factual content and use only supported citations. "
        "A source citation contains evidence_id and quote, not display-only page fields.\n"
    )
    while True:
        candidate = correction_prompt(
            instructions
            + json.dumps(compact, ensure_ascii=False, separators=(",", ":")),
            text,
            error,
        )
        if fits(candidate):
            return candidate
        removable = next(
            (
                i
                for i in reversed(range(len(compact["sources"])))
                if compact["sources"][i]["id"] not in required
            ),
            None,
        )
        if removable is None:
            raise ModelError(
                "Procedure correction cannot fit all cited sources and its unchanged reply; original receipts are retained."
            )
        compact["omitted_source_ids"].append(compact["sources"].pop(removable)["id"])
