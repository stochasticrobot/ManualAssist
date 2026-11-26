"""Check difficult boundaries between a relevant instruction, surrounding context and
a bare section label. Controlled comparisons test how evidence is prepared and
retained; they do not measure a live reviewer’s judgment."""

from workbench.procedure_guides.compare_source_and_guide_behavior import (
    GuideBehaviorComparison,
    assess_behavior_reply,
    prepare_behavior_packets,
)


def packet():
    """Build a source-pool fixture with a heading, a focus action and supporting action.

    Args:
        None.
    Returns:
        A packet whose later sentence is supported outside its omission-check scope.
    """
    return {
        "guide": {
            "steps": [
                {
                    "id": "s",
                    "instruction": "Reset the network. Add the device in the app.",
                }
            ]
        },
        "reader_context": {},
        "focus_paths": ["guide.steps[s]"],
        "comparison_source_ids": ["heading", "reset"],
        "sources": [
            {"id": "heading", "text": "Network setup", "label": "section_header"},
            {"id": "reset", "text": "Reset the network.", "label": "text"},
            {"id": "app", "text": "Add the device in the app.", "label": "text"},
        ],
    }


def row(source_id, quote, draft, status):
    """Build an explicit fixture judgment with real quotation fields.

    Args:
        source_id: Source record being assessed.
        quote: Exact source phrase.
        draft: Exact reader wording or empty for absence/context.
        status: Intended fixture classification, not a live model prediction.
    Returns:
        One schema-valid comparison row for evidence-boundary tests.
    """
    return {
        "source_id": source_id,
        "source_quote": quote,
        "draft_quote": draft,
        "comparison": "Fixture comparison of the supplied behavior.",
        "status": status,
    }


def test_heading_accounted_without_requiring_its_words_in_guide():
    """Ensure a non-action heading can be accounted for without becoming a defect.

    Args:
        None.
    Returns:
        None; the same judgment must still include coverage of the actual reset action.
    """
    p = packet()
    rows = [
        row("reset", "Reset the network.", "Reset the network.", "preserved"),
    ]
    assert not assess_behavior_reply(
        GuideBehaviorComparison(
            source_actions=rows,
            unsupported_draft_actions=[],
            non_action_sources=[
                {"source_id": "heading", "explanation": "Topic label only"}
            ],
        ),
        p,
    )
    assert assess_behavior_reply(
        GuideBehaviorComparison(
            source_actions=[],
            unsupported_draft_actions=[],
            non_action_sources=[
                {"source_id": "heading", "explanation": "Topic label only"}
            ],
        ),
        p,
    )


def test_heading_with_actual_instruction_is_not_discarded():
    """Keep concrete instructions in headings eligible for missing-action defects.

    Args:
        None.
    Returns:
        None; proves headings are not removed by the packet builder or validator.
        Live tests separately check whether the model classifies this heading correctly.
    """
    p = packet()
    p["sources"][0]["text"] = "Disconnect power before removing the cover."
    rows = [
        row("heading", p["sources"][0]["text"], "", "missing"),
        row("reset", "Reset the network.", "Reset the network.", "preserved"),
    ]
    defects = assess_behavior_reply(
        GuideBehaviorComparison(source_actions=rows, unsupported_draft_actions=[]), p
    )
    assert len(defects) == 1 and defects[0].issue.startswith("missing:")


def test_all_sources_eligible_and_context_does_not_create_extra_obligations():
    """Keep support eligibility independent of which records need omission checks.

    Args:
        None.
    Returns:
        None; a support row outside scope is valid, while absence of another
        non-focus instruction does not impose a new requirement on this packet.
    """
    p = packet()
    p["comparison_source_ids"] = ["reset"]
    rows = [
        row("reset", "Reset the network.", "Reset the network.", "preserved"),
        row(
            "app",
            "Add the device in the app.",
            "Add the device in the app.",
            "preserved",
        ),
    ]
    assert not assess_behavior_reply(
        GuideBehaviorComparison(source_actions=rows, unsupported_draft_actions=[]), p
    )
    p["sources"].append(
        {"id": "other", "text": "Store the robot in its box.", "label": "text"}
    )
    rows.append(row("other", "Store the robot in its box.", "", "missing"))
    assert not assess_behavior_reply(
        GuideBehaviorComparison(source_actions=rows, unsupported_draft_actions=[]), p
    )


def test_exact_missing_claim_cannot_ignore_later_sentence_or_hide_body_as_heading():
    """Reject absent-action claims contradicted by actual reader text and invalid skips.

    Args:
        None.
    Returns:
        None; invalid comparison evidence remains incomplete instead of becoming
        a guide-edit request or silently accepted review.
    """
    p = packet()
    p["comparison_source_ids"] = ["app"]
    for bad in [
        row("app", "Add the device in the app.", "", "missing"),
    ]:
        defects = assess_behavior_reply(
            GuideBehaviorComparison(source_actions=[bad], unsupported_draft_actions=[]),
            p,
        )
        assert any("review remains incomplete" in d.issue for d in defects)


def test_production_packets_keep_single_evidence_pool_with_separate_scope():
    """Exercise the actual packet builder across its four-record comparison boundary.

    Args:
        None.
    Returns:
        None; every packet retains all five supporting records but has disjoint
        comparison IDs, so the fifth source cannot become second-class evidence.
    """
    sources = [
        {"id": str(i), "text": f"Action {i}.", "label": "text"} for i in range(5)
    ]
    guide = {
        "steps": [
            {
                "id": "s",
                "instruction": " ".join(s["text"] for s in sources),
                "citations": [
                    {"evidence_id": s["id"], "quote": s["text"]} for s in sources
                ],
            }
        ]
    }
    packets = prepare_behavior_packets(guide, sources)
    assert len(packets) == 2
    assert all(
        {s["id"] for s in p["sources"]} == set(map(str, range(5))) for p in packets
    )
    assert [i for p in packets for i in p["comparison_source_ids"]] == list(
        map(str, range(5))
    )
    assert all("context_sources" not in p for p in packets)


def test_missing_action_may_quote_the_present_part_of_an_incomplete_instruction():
    """Distinguish a valid nearby quote from proof that an omitted action is present.

    Args:
        None.
    Returns:
        None; a valid quote becomes a behavioral claim for confirmation, while an
        invented quote remains an integrity failure. Neither is silently approved.
    """
    p = packet()
    p["comparison_source_ids"] = ["reset"]
    p["sources"][1]["text"] = "Reset the network and close the cover."
    for quote, incomplete in [("Reset the network.", False), ("Invented words", True)]:
        reply = GuideBehaviorComparison(
            source_actions=[row("reset", "close the cover.", quote, "missing")],
            unsupported_draft_actions=[],
        )
        defects = assess_behavior_reply(reply, p)
        assert (
            bool(any("review remains incomplete" in d.issue for d in defects))
            == incomplete
        )
        assert defects
