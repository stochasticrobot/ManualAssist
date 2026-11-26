"""Reject broken guide structures and citations that do not match the supplied
manual.

A reader must not be sent to a nonexistent step or shown an invented quotation.
These checks verify referenced steps, branch destinations, prerequisites and
source text before saving a guide. They cannot establish that an AI's
interpretation is correct or that following the guide is safe."""

from workbench.manual_analysis.validate_faq_and_troubleshooting import check_tree, cite


def validate_procedure_steps(draft, kind, evidence):
    """Validate a complete proposed guide and attach actual source page numbers.

    Args:
        draft: Structured procedure proposed by the planner.
        kind: Installation, maintenance or troubleshooting, fixed by discovery.
        evidence: Original source records actually supplied to this planner, by ID.
    Returns:
        A copied, page-linked guide. Raises ValueError for unsupported quotes,
        duplicate/out-of-order steps, missing procedures or inappropriate intervals.
        Ordered steps may coexist with independent cited checks; neither is discarded.
        Quote matching does not establish that the explanation follows from the quote.
    """
    value = draft.model_dump()
    seen = set()
    for step in value["steps"]:
        if step["id"] in seen or not set(step["after_step_ids"]) <= seen:
            raise ValueError(
                "Step IDs must be unique and dependencies must refer to earlier steps."
            )
        seen.add(step["id"])
    if (
        value["outcome"] in {"partial", "insufficient_evidence"}
        and not value["unanswered_questions"]
    ):
        raise ValueError(
            "Partial or insufficient evidence outcomes must describe their gaps."
        )
    no_instructions = (
        not value["steps"]
        and not value["independent_checks"]
        and value["troubleshooting"] is None
    )
    if value["outcome"] in {"partial", "insufficient_evidence"} and no_instructions:
        if value["schedule"] is not None:
            raise ValueError("A guide without instructions cannot declare a schedule.")
        return cite(value, evidence)
    if kind == "troubleshooting":
        if value["steps"]:
            raise ValueError(
                "Troubleshooting uses independent_checks or a supported path, not an implied ordered sequence."
            )
        if value["troubleshooting"] is None and not value["independent_checks"]:
            raise ValueError(
                "A troubleshooting procedure needs documented checks or a supported path."
            )
        if value["troubleshooting"] is not None:
            check_tree(value["troubleshooting"])
    elif value["troubleshooting"] is not None:
        raise ValueError("Installation and maintenance cannot contain a diagnostic tree.")
    elif not value["steps"] and not value["independent_checks"]:
        raise ValueError("Installation and maintenance need documented steps or checks.")
    if kind != "maintenance" and value["schedule"] is not None:
        raise ValueError(
            "Only maintenance procedures may declare a recurring schedule."
        )
    return cite(value, evidence)


def validate_saved_procedure(result, evidence):
    """Recheck a saved guide's structure and quotations before publishing it on Resume.

    Args:
        result: Previously completed guide, including page-qualified quotations.
        evidence: Original passages retained in that procedure's saved investigation.
    Returns:
        None when its published fields still pass validation. Raises ValueError for
        changed pages or unsupported quotations. Unfinished records contain no guide.
        This is an integrity check, not a new model judgment of semantic correctness.
    """
    from workbench.procedure_guides.procedure_reply_models import ProcedureDraft

    if result["status"] == "unfinished":
        return

    def remove_pages(value):
        """Remove display-only page annotations to revalidate the model's original fields.

        Args:
            value: Saved nested guide dictionaries, lists or scalar values.
        Returns:
            Copied value without page fields; original saved data is not changed.
        """
        if isinstance(value, list):
            return [remove_pages(item) for item in value]
        if isinstance(value, dict):
            return {
                key: remove_pages(item) for key, item in value.items() if key != "page"
            }
        return value

    fields = {key: result[key] for key in ProcedureDraft.model_fields if key in result}
    draft = ProcedureDraft.model_validate(remove_pages(fields))
    if validate_procedure_steps(draft, result["kind"], evidence) != {
        **draft.model_dump(),
        **fields,
    }:
        raise ValueError("Saved procedure pages differ from the original sources.")
