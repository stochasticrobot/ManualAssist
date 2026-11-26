"""Attach real manual quotations and page references to the passages an AI selects.

The AI receives numbered passage choices instead of being asked to reproduce
reference details. The application maps each choice back to the original text,
which prevents invented or altered quotations from becoming evidence. Selecting a
real passage still does not prove that it supports the generated statement."""

import copy
import json

from jsonschema import Draft202012Validator

VERSION = "code-owned-evidence-v1"
EVIDENCE_RULE = (
    "Use the numbered passages as evidence. Select passage numbers where the response asks for evidence. "
    "The application attaches original source text and references; do not reproduce source quotations or invent references. "
    "Preserve conditions and model applicability from the supplied context.\n"
)


class EvidencePrompt(str):
    """Carry private source bindings beside a model-visible task string."""

    def __new__(cls, text, sources):
        """Freeze original records without exposing their identities in the prompt.

        Args:
            cls: String subclass being constructed.
            text: Task-specific model-visible text.
            sources: Original records, including separate windows of repeated IDs.
        Returns:
            String-compatible prompt with a deep-copied private evidence registry.
        """
        obj = super().__new__(cls, text)
        obj.sources = copy.deepcopy(sources)
        return obj

    def continued(self, text):
        """Preserve evidence ownership across a bounded response correction.

        Args:
            self: Original bound request.
            text: Complete corrected-request instructions and original raw reply.
        Returns:
            New prompt with unchanged evidence bindings; no model request is sent.
        """
        return EvidencePrompt(text, self.sources)


def evidence_task(instructions, payload, sources):
    """Build a small task with numbered evidence and private persistent references.

    Args:
        instructions: Task-specific plain English; should not ask for source IDs/quotes.
        payload: Relevant task data, excluding unrelated run history.
        sources: Original records actually available to this request, not an entire
            archive. Repeated-ID windows remain distinct, never concatenated.
    Returns:
        Bound prompt. Metadata and embedded citation quotations are kept out of
        model inputs. Unknown historical references become an explicit unavailable
        count, not permission to cite unseen evidence.
    """
    sources = copy.deepcopy(sources)
    by_id = {}
    for number, source in enumerate(sources, 1):
        by_id.setdefault(source["id"], []).append(number)

    def clean(value):
        """Remove bookkeeping recursively while retaining actual task language.

        Args:
            value: One nested task object, list or scalar.
        Returns:
            Model-visible data; existing references become local passage choices.
        """
        if isinstance(value, list):
            return [clean(v) for v in value]
        if not isinstance(value, dict):
            return value
        if "id" in value and "text" in value and value["id"] in by_id:
            return {"passages": by_id[value["id"]], "text": value["text"]}
        result = {}
        for key, item in value.items():
            if key == "navigation":
                # Task navigation is not a generated citation. Retain only known
                # heading/page fields so the planner can choose a physical page.
                result[key] = {
                    "pages": item.get("pages"),
                    "headings": [
                        {"title": h["title"], "page": h["page"]}
                        for h in item.get("headings", [])
                    ],
                    "headings_total": item.get("headings_total", 0),
                }
                continue
            if key in {
                "quote",
                "page",
                "bbox",
                "source_offset",
                "label",
                "omitted_source_ids",
                "headings",
                "headings_total",
                "lead_ids",
                "supporting_lead_ids",
            }:
                continue
            if key == "evidence_id":
                choices = by_id.get(item, [])
                if value.get("quote") and (
                    len(choices) > 1 or "review_passage" in value
                ):
                    choices = [
                        n for n in choices if value["quote"] in sources[n - 1]["text"]
                    ]
                if not item:
                    result["passage"] = 0
                elif len(choices) == 1:
                    result["passage"] = choices[0]
                else:
                    result["unavailable_evidence"] = True
                    if choices:
                        result["candidate_passages"] = choices
            elif key in {
                "evidence_ids",
                "returned_ids",
                "new_evidence_ids",
                "omitted_ids",
                "inspected_source_ids",
            }:
                output_key = (
                    "passages"
                    if key == "evidence_ids"
                    else key.removesuffix("_ids") + "_passages"
                )
                result[output_key] = sorted({n for i in item for n in by_id.get(i, [])})
                missing = sum(i not in by_id for i in item)
                if missing:
                    result["unavailable_evidence_count"] = missing
            else:
                result[key] = clean(item)
        return result

    passages = [
        {
            "passage": i,
            "text": s["text"],
            **({"section_context": s["section"]} if s.get("section") else {}),
        }
        for i, s in enumerate(sources, 1)
    ]
    return EvidencePrompt(
        instructions
        + "\n"
        + EVIDENCE_RULE
        + json.dumps(
            {"task": clean(payload), "passages": passages}, ensure_ascii=False
        ),
        sources,
    )


def source_response_schema(schema, prompt):
    """Adapt legacy result shapes without asking models to author source references.

    Args:
        schema: Internal application response class, or None for plain text.
        prompt: Possibly bound prompt containing the private evidence registry.
    Returns:
        A validator exposing passage selections to the model and returning the
        original internal result type to existing application consumers. Unknown
        selections, extra fields and malformed data fail before reference attachment.
        Existing plain-text/non-evidence tasks keep their original schema.
    """
    if (
        schema is None
        or not isinstance(prompt, EvidencePrompt)
        or getattr(schema, "source_bound", False)
    ):
        return schema
    original = schema.model_json_schema()
    registry = copy.deepcopy(prompt.sources)

    def transform(node):
        """Replace source identity fields in the model-facing schema only.

        Args:
            node: JSON-schema object or nested value.
        Returns:
            Copy with bounded local selections and no generated source quotation.
        """
        if isinstance(node, list):
            return [transform(n) for n in node]
        if not isinstance(node, dict):
            return node
        out = {k: transform(v) for k, v in node.items()}
        props = out.get("properties", {})
        required = out.get("required", [])
        if "evidence_id" in props:
            optional = props["evidence_id"].get("default") == ""
            props.pop("evidence_id")
            props["passage"] = {
                "type": "integer",
                "minimum": 0 if optional else 1,
                "maximum": len(registry),
            }
            if optional:
                props["passage"]["default"] = 0
            required = [
                "passage" if k == "evidence_id" else k for k in required if k != "quote"
            ]
            props.pop("quote", None)
        if "evidence_ids" in props:
            old = props.pop("evidence_ids")
            props["passages"] = {
                "type": "array",
                "items": {"type": "integer", "minimum": 1, "maximum": len(registry)},
            }
            if "minItems" in old:
                props["passages"]["minItems"] = old["minItems"]
            required = ["passages" if k == "evidence_ids" else k for k in required]
        for old_key, new_key, multiple in [
            ("lead_id", "lead_choice", False),
            ("lead_ids", "lead_choices", True),
            ("supporting_lead_ids", "supporting_lead_choices", True),
        ]:
            if old_key not in props:
                continue
            old = props.pop(old_key)
            choice = {"type": "integer", "minimum": 1, "maximum": len(registry)}
            props[new_key] = {"type": "array", "items": choice} if multiple else choice
            if multiple and "minItems" in old:
                props[new_key]["minItems"] = old["minItems"]
            required = [new_key if key == old_key else key for key in required]
        if "required" in out:
            out["required"] = required
        return out

    wire = transform(original)
    wire["description"] = (
        "Return task content and local passage selections. Source evidence is attached by the application."
    )
    validator = Draft202012Validator(wire)

    def hydrate(value, shape):
        """Attach original source records following the validated internal shape.

        Args:
            value: Schema-validated model JSON containing only bounded choices.
            shape: Corresponding original JSON schema, including references.
        Returns:
            Original internal shape with immutable source IDs and full source text.
            No factual text is repaired; repeated windows retain their selected text.
        """
        if "$ref" in shape:
            shape = original["$defs"][shape["$ref"].rsplit("/", 1)[-1]]
        if "anyOf" in shape:
            if value is None:
                return None
            shape = next(s for s in shape["anyOf"] if s.get("type") != "null")
            return hydrate(value, shape)
        if isinstance(value, list):
            return [hydrate(v, shape.get("items", {})) for v in value]
        if not isinstance(value, dict):
            return value
        props = shape.get("properties", {})
        out = {
            k: hydrate(v, props.get(k, {}))
            for k, v in value.items()
            if k
            not in {
                "passage",
                "passages",
                "lead_choice",
                "lead_choices",
                "supporting_lead_choices",
            }
        }
        if "evidence_id" in props:
            selection = value.get("passage", 0)
            out["evidence_id"] = registry[selection - 1]["id"] if selection else ""
            if "quote" in props:
                out["quote"] = registry[selection - 1]["text"] if selection else ""
        if "evidence_ids" in props:
            out["evidence_ids"] = list(
                dict.fromkeys(registry[n - 1]["id"] for n in value.get("passages", []))
            )
        for old_key, new_key, multiple in [
            ("lead_id", "lead_choice", False),
            ("lead_ids", "lead_choices", True),
            ("supporting_lead_ids", "supporting_lead_choices", True),
        ]:
            if old_key in props:
                out[old_key] = (
                    [registry[n - 1]["id"] for n in value[new_key]]
                    if multiple
                    else registry[value[new_key] - 1]["id"]
                )
        return out

    class BoundResponse:
        """Validate local choices, then deterministically attach original evidence."""

        source_bound = True

        @classmethod
        def model_json_schema(cls):
            """Provide only the model-visible response shape.

            Args:
                cls: Bound response adapter.
            Returns:
                Independent schema copy; callers cannot mutate the retained schema.
            """
            return copy.deepcopy(wire)

        @classmethod
        def model_validate(cls, value):
            """Reject invalid choices before restoring the application result shape.

            Args:
                cls: Bound response adapter.
                value: Raw parsed model JSON, not a trusted application record.
            Returns:
                Original validated application result. Malformed selections raise
                ModelJSONError and use the normal single-correction allowance.
            """
            from workbench.agentic_workflow.validate_and_correct_model_json import (
                ModelJSONError,
            )

            errors = list(validator.iter_errors(value))
            if errors:
                leaves = []
                pending = list(errors)
                while pending:
                    item = pending.pop()
                    if item.context:
                        pending.extend(item.context)
                    else:
                        leaves.append(item)
                error = max(leaves, key=lambda item: len(item.absolute_path))
                location = list(error.absolute_path)
                if error.validator == "required" and isinstance(error.instance, dict):
                    location += [
                        name
                        for name in error.validator_value
                        if name not in error.instance
                    ][:1]
                raise ModelJSONError(
                    "Invalid response fields or passage selection ("
                    + error.validator
                    + ") at "
                    + ".".join(map(str, location))
                )
            return schema.model_validate(hydrate(value, original))

    return BoundResponse


def requires_source_binding(schema):
    """Detect response types that must not ask a model to author source references.

    Args:
        schema: Internal response class or None for a plain-text/vision reply.
    Returns:
        True when a nested schema contains source-reference or quotation fields.
        Model-visible bound schemas have already replaced these fields.
    """
    if schema is None:
        return False

    def contains(value):
        """Inspect field definitions, not prose that merely mentions evidence.

        Args:
            value: JSON-schema object or child.
        Returns:
            Whether a forbidden model-authored source field is declared.
        """
        if isinstance(value, list):
            return any(contains(v) for v in value)
        if not isinstance(value, dict):
            return False
        return bool(
            set(value.get("properties", {}))
            & {
                "evidence_id",
                "evidence_ids",
                "source_id",
                "source_quote",
                "lead_id",
                "lead_ids",
                "supporting_lead_ids",
            }
        ) or any(contains(v) for v in value.values())

    return contains(schema.model_json_schema())
