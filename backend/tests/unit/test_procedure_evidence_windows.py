"""Check that a guide planner can see newly requested text without deleting passages
already collected. The tests distinguish text retained on disk from the smaller
selection visible in the next AI request."""

from workbench.procedure_guides.inspect_procedure_sources import (
    select_planning_evidence,
)


def test_new_passages_displace_old_context_without_erasing_evidence():
    """Keep requested passages readable after earlier context fills the allowance.

    Args:
        None; uses oversized combined synthetic passages and the production window limit.
    Returns:
        None; proves a new source enters the prompt while displaced sources remain
        available for future reads. This does not establish model interpretation.
    """
    evidence = {
        str(i): dict(id=str(i), page=i + 1, label="text", text="x" * 12000)
        for i in range(3)
    }
    visible, omitted = select_planning_evidence(evidence, ["2"])
    assert [i["id"] for i in visible] == ["2"]
    assert set(omitted) == {"0", "1"}
    visible, _ = select_planning_evidence(evidence, ["0"])
    assert [i["id"] for i in visible] == ["0"]
    assert len(evidence) == 3


def test_organization_inventory_does_not_repeat_full_quotations():
    """Keep a realistically large inventory below dispatch limits without dropping leads.

    Args:
        None; synthetic leads have long, repeated quotations like manual discoveries.
    Returns:
        None; proves the full-record form exceeds the limit while compact task
        descriptions retain every ID/title/role/source and leave quotations intact.
    """
    import copy
    import json
    from workbench.procedure_guides.consolidate_source_linked_tasks import (
        INSTRUCTIONS,
        organization_prompt,
        organization_input_estimate,
    )
    from workbench.agentic_workflow.model_call_allowances import MAX_REQUEST_INPUT

    leads = [
        dict(
            id=f"lead-{i}",
            kind="installation",
            title=f"Configure component {i}",
            role="procedure",
            evidence_ids=[f"source-{i}"],
            citations=[
                dict(evidence_id=f"source-{i}", quote="Original instruction. " * 50)
            ],
        )
        for i in range(105)
    ]
    original = copy.deepcopy(leads)
    assert (
        organization_input_estimate(INSTRUCTIONS + json.dumps({"leads": leads}))
        > MAX_REQUEST_INPUT
    )
    prompt = organization_prompt(leads)
    assert organization_input_estimate(prompt) < MAX_REQUEST_INPUT // 2
    payload = json.loads(prompt.split("\n")[-1])
    assert len(payload["leads"]) == 105
    for saved, compact in zip(leads, payload["leads"]):
        assert all(compact[k] == saved[k] for k in compact if k != "choice")
        assert prompt.sources[compact["choice"] - 1]["id"] == saved["id"]
    assert leads == original
    # Targeted correction payloads are checked separately against frozen dishwasher cases.
