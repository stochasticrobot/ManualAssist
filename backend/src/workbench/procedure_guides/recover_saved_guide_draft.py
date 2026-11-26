"""Prepare an already saved guide for another review without changing its
instructions.

Saved results include display details such as page annotations that are not part
of the AI's original draft. This helper removes those additions and checks that
the remaining draft has the required fields, so recovery can use the ordinary
guide-writing process rather than invent a replacement."""

from workbench.procedure_guides.procedure_reply_models import ProcedureDraft


def saved_draft(result):
    """Remove display annotations without altering saved instructions or quotations.

    Args:
        result: Saved guide already validated against its original evidence.
    Returns:
        Strict draft suitable for the ordinary planner review path. Application
        metadata is omitted; malformed draft fields still raise validation errors.
        The supplied result is never mutated.
    """

    def remove_pages(value):
        """Copy nested draft content without application-added page annotations.

        Args:
            value: Draft dictionary, list or scalar.
        Returns:
            Independent nested value retaining all content except page fields.
        """
        if isinstance(value, dict):
            return {k: remove_pages(v) for k, v in value.items() if k != "page"}
        if isinstance(value, list):
            return [remove_pages(v) for v in value]
        return value

    return ProcedureDraft.model_validate(
        remove_pages({k: result[k] for k in ProcedureDraft.model_fields if k in result})
    )
