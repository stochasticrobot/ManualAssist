"""Prepare focused comparisons between a guide's instructions and the manual passages
behind them.

Checking a whole guide in one question can hide a missing warning or condition.
This file identifies smaller pieces to compare, retaining their surrounding
instructions and original source references. It prepares the review questions; it
does not ask an AI for a verdict or decide the guide is correct."""

import re

from workbench.procedure_guides.compare_source_and_guide_behavior import (
    cited_locations,
    instruction_fields,
    reader_guide,
)


def matching_label(text):
    """Normalize presentation differences, not the meaning of a task label.

    Args:
        text: Original symptom or table-row title.
    Returns:
        Case-insensitive words with punctuation/spacing removed. No synonyms,
        keyword subsets or product-specific mappings are used to infer relevance.
    """
    return " ".join(re.findall(r"\w+", text.casefold()))


def citing_objects(value, source_id):
    """Find every guide object that directly selects a particular original source.

    Args:
        value: Nested original guide, including its immutable citations.
        source_id: Original record identity retained by code.
    Returns:
        All directly citing dictionaries; descendants are visited independently so
        a warning cannot disappear merely because its parent has a symptom label.
    """
    found = []
    if isinstance(value, dict):
        if any(c["evidence_id"] == source_id for c in value.get("citations", [])):
            found.append(value)
        for key, child in value.items():
            if key != "citations":
                found.extend(citing_objects(child, source_id))
    elif isinstance(value, list):
        for child in value:
            found.extend(citing_objects(child, source_id))
    return found


def table_rows(text):
    """Recognize complete Markdown table rows while preserving exact source spans.

    Args:
        text: Original parser table text, never a model-generated replacement.
    Returns:
        Labeled data-row spans, or an empty list when structure is ambiguous. Blank
        first-cell continuation rows attach to their predecessor. Unrecognized
        text forces broader coverage rather than silently dropping instructions.
    """
    lines = text.splitlines(keepends=True)
    if len(lines) < 3 or not re.fullmatch(r"[\s|:\-]+", lines[1]):
        return []
    if not lines[0].lstrip().startswith("|"):
        return []
    rows = []
    offset = len(lines[0]) + len(lines[1])
    for line in lines[2:]:
        if not line.strip():
            if rows:
                rows[-1]["end"] += len(line)
                rows[-1]["text"] += line
            offset += len(line)
            continue
        if not line.lstrip().startswith("|") or line.count("|") < 3:
            return []
        label = line.split("|")[1].strip()
        if not label:
            if not rows:
                return []
            rows[-1]["end"] += len(line)
            rows[-1]["text"] += line
        else:
            rows.append(
                {
                    "label": label,
                    "start": offset,
                    "end": offset + len(line),
                    "text": line,
                }
            )
        offset += len(line)
    return rows


def reader_field_contexts(guide):
    """Locate each reader field together with its enclosing task and conditions.

    Args:
        guide: Complete citation-free guide. Its instructions are claims under
            review, never additional manufacturer evidence.
    Returns:
        Mapping from reader paths to their complete enclosing step, independent
        check, schedule or diagnostic tree and shared preparations/applicability.
        Gap paths are identified separately so they are not mistaken for actions.
        Does not modify the guide or request model judgments.
    """
    contexts = {}
    gaps = set()
    for key in (
        "steps",
        "independent_checks",
        "prerequisites",
        "schedule",
        "troubleshooting",
    ):
        value = guide.get(key)
        if value is None:
            continue
        parts = list(enumerate(value)) if isinstance(value, list) else [(None, value)]
        for index, part in parts:
            path = f"guide.{key}"
            if index is not None:
                path += f"[{part.get('id', index)}]"
            context = {
                "applies_to": guide.get("applies_to", ""),
                "prerequisites": guide.get("prerequisites", []),
                "part": part,
            }
            if key == "steps":
                required = set(part.get("after_step_ids", []))
                # Declared earlier steps establish reader order, not source support.
                context["earlier_steps"] = [
                    s for s in guide.get("steps", []) if s.get("id") in required
                ]
            for field, _ in instruction_fields(part, path):
                contexts[field] = context
            if key == "troubleshooting":
                gaps.update(
                    f"{path}.nodes[{node.get('id', n)}].text"
                    for n, node in enumerate(part.get("nodes", []))
                    if node.get("kind") == "unresolved"
                )
    return contexts, gaps


def prepare_comparisons(guide, sources, split_text, required_source_ids=()):
    """Build coherent-guide coverage and support tasks with explicit source scope.

    Args:
        guide: Validated complete guide, not one isolated step.
        sources: Original collected records available for support.
        split_text: Lossless sentence-like splitter for non-table source text.
        required_source_ids: Previously reviewed draft sources that must remain
            eligible for coverage even if a revision removes their citations.
    Returns:
        Comparisons, source-scope audit and source-preparation problems. Each
        comparison retains private source/reader locations. Only exact symptom-row
        matches permit narrower table coverage; ambiguous rows all receive explicit
        task-relevance checks before they can become omission obligations.
        Every directly cited prerequisite/warning remains required coverage. Uncited
        records stay available as context, not extra omission obligations. This is
        review of supplied cited evidence, not proof of full-manual discovery.
        Verified governing headings receive one comparison each; coverage and
        support correction references retain their original heading dependencies.
    """
    cited = set(cited_locations(guide)) | set(required_source_ids)
    available = {s["id"] for s in sources}
    if cited - available:
        raise ValueError("Review is missing cited source passages")
    reader = reader_guide(guide)
    comparisons = []
    scope = []
    problems = []
    ordered = sorted(
        sources, key=lambda s: s.get("document_position", sources.index(s))
    )
    headings = []
    previous_heading = False
    for source in ordered:
        if source.get("label") in {"section_header", "title"}:
            headings = (headings + [source]) if previous_heading else [source]
            previous_heading = True
            continue
        previous_heading = False
        if source["id"] not in cited:
            continue
        context = source.get("section") or [h["text"] for h in headings]
        rows = (
            table_rows(source["text"])
            if source.get("label") in {"table", "document_index"}
            else []
        )
        units = rows or split_text(source["text"])
        mode = "complete_cited_passage"
        if rows:
            owners = citing_objects(guide, source["id"])
            labels = {matching_label(row["label"]) for row in rows}
            requested = {matching_label(obj.get("symptom", "")) for obj in owners}
            if owners and requested and "" not in requested and requested <= labels:
                units = [
                    row for row in rows if matching_label(row["label"]) in requested
                ]
                mode = "exact_symptom_rows"
            else:
                mode = "ambiguous_table_scope_review"
            # PDF extraction can put an actual instruction in the Markdown header.
            # Always review that original line; do not assume it is only a label.
            header = source["text"].splitlines(keepends=True)[0]
            units = [
                *units,
                {"start": 0, "end": len(header), "text": header, "table_header": True},
            ]
        scope.append(
            {
                "source_id": source["id"],
                "mode": mode,
                "required_units": units,
                "available_units": len(rows) + 1 if rows else len(units),
            }
        )
        for unit in units:
            comparisons.append(
                {
                    "kind": "coverage",
                    "statement_to_check": unit["text"],
                    "section_context": context,
                    "scope_check_required": mode == "ambiguous_table_scope_review"
                    or unit.get("table_header", False),
                    "_source_ids": [source["id"]]
                    + [h["id"] for h in headings if h["id"] in cited],
                    "_unit": unit,
                }
            )
    # Each governing heading is an explicit comparison exactly once. A model may
    # classify a descriptive heading as not_instruction, but must check directives.
    by_id = {source["id"]: source for source in sources}
    heading_ids = [
        s["id"]
        for s in sources
        if s["id"] in cited and s.get("label") in {"section_header", "title"}
    ]
    for comparison in comparisons:
        for sid in comparison["_source_ids"]:
            for hid in by_id[sid].get("section_source_ids", []):
                if hid not in heading_ids:
                    heading_ids.append(hid)
    for hid in heading_ids:
        heading = by_id.get(hid)
        if heading is None or heading.get("label") not in {"section_header", "title"}:
            raise ValueError("Missing original governing heading record")
        unit = {"start": 0, "end": len(heading["text"]), "text": heading["text"]}
        comparisons.append(
            {
                "kind": "coverage",
                "statement_to_check": heading["text"],
                "section_context": heading.get("section", [])[:-1],
                "_source_ids": [hid],
                "_unit": unit,
            }
        )
        scope.append(
            {
                "source_id": hid,
                "mode": "explicit_governing_heading",
                "required_units": [unit],
                "available_units": 1,
            }
        )
    fields = instruction_fields(reader)
    contexts, gaps = reader_field_contexts(reader)
    for path, text in fields:
        if not text.strip() or path.rsplit(".", 1)[-1] in {
            "symptom",
            "applies_to",
            "applies_when",
        }:
            continue
        # Review the complete field, including later sentences and pronouns. Its
        # enclosing reader object preserves conditions without becoming evidence.
        context = contexts.get(path, {"applies_to": reader.get("applies_to", "")})
        unit = {"start": 0, "end": len(text), "text": text}
        comparison = {
            "kind": "support",
            "proposed_reader_text": text,
            "reader_context": context,
            "evidence_gap": path in gaps,
            "_unit": unit,
            "_reader_path": path,
            "_source_ids": sorted(cited),
        }
        condition = context.get("part", {}).get("applies_when", "")
        if condition:
            comparison["applies_when"] = condition
        comparisons.append(comparison)
    for index, comparison in enumerate(comparisons, 1):
        original_ids = comparison["_source_ids"]
        dependencies = []
        for sid in original_ids:
            for hid in by_id[sid].get("section_source_ids", []):
                if hid not in by_id or by_id[hid].get("label") not in {
                    "section_header",
                    "title",
                }:
                    raise ValueError("Missing original governing heading record")
                dependencies.append(hid)
        comparison["_source_ids"] = list(dict.fromkeys(original_ids + dependencies))
        comparison["comparison"] = index
    return comparisons, scope, problems
