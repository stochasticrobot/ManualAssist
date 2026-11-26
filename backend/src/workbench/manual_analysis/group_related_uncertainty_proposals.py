"""Combine repeated questions about the same passages before investigating them.

An AI may describe one ambiguity several ways. Grouping equivalent questions
avoids paying to investigate each wording separately while retaining every
original question. Work already under review keeps its existing saved references."""

import json

from pydantic import Field

from workbench.agentic_workflow.run_source_group_tasks import digest
from workbench.data_models.analysis_and_question_models import Strict
from workbench.job_storage import job_files_and_audit_log as storage
from workbench.model_access.model_requests_and_responses import ModelError


class EquivalentUncertaintyGroups(Strict):
    """Partition supplied indices into equivalent-question groups or singletons."""

    groups: list[list[int]] = Field(min_length=1)


def group_related_uncertainty_proposals(job_id, findings, run):
    """Consolidate equivalent source questions without losing any original wording.

    Args:
        job_id: Manual job receiving the saved grouping and original proposal list.
        findings: Ordered source-backed proposals from discovery.
        run: Shared bounded call owner; grouping requests are ordinary logged calls.
    Returns:
        Review questions with all variants retained. At most one grouping request is
        made per repeated-source bucket. Existing ungrouped reviews retain their
        indices; malformed partitions fail rather than silently dropping a proposal.
    """
    path = storage.job_dir(job_id) / "uncertainty-groups.json"
    identity = digest(findings)
    if path.exists():
        saved = json.loads(path.read_text())
        if saved["input_hash"] != identity:
            raise ModelError("Uncertainty proposals changed after grouping.")
        return saved["questions"]
    if (storage.job_dir(job_id) / "finding-review-progress.json").exists():
        return findings
    buckets = {}
    for index, finding in enumerate(findings):
        buckets.setdefault(tuple(sorted(finding["evidence_ids"])), []).append(index)
    groups = []
    for indices in buckets.values():
        if len(indices) == 1:
            groups.append(indices)
            continue
        reply = run.call(
            "text",
            "Group only equivalent uncertainty questions. The application already grouped proposals by shared source evidence. "
            "Keep different missing details, conditions, quantities or safety questions separate. "
            "Return every supplied index exactly once, including singleton groups. Do not discard "
            "minor questions or resolve any question here.\n"
            + json.dumps(
                [{"index": i, "issue": findings[i]["issue"]} for i in indices]
            ),
            EquivalentUncertaintyGroups,
            cap=2000,
        )
        flat = [i for group in reply.groups for i in group]
        if sorted(flat) != sorted(indices) or any(not group for group in reply.groups):
            raise ModelError("Uncertainty grouping omitted or duplicated a proposal.")
        groups.extend(reply.groups)
    groups.sort(key=min)
    questions = []
    for group in groups:
        originals = [findings[i] for i in sorted(group)]
        if len(group) == 1:
            questions.append(originals[0])
        else:
            severity = max(
                (f["severity"] for f in originals),
                key=lambda s: {"info": 0, "review": 1, "critical": 2}[s],
            )
            questions.append(
                {
                    **originals[0],
                    "severity": severity,
                    "issue": "Check every wording below before closing this question. A resolution must address all versions:\n"
                    + "\n".join("- " + f["issue"] for f in originals),
                }
            )
    storage.save(
        path,
        {
            "input_hash": identity,
            "original_proposals": findings,
            "groups": groups,
            "questions": questions,
        },
    )
    storage.event(
        job_id,
        "uncertainty_grouping",
        original=len(findings),
        review_questions=len(questions),
    )
    return questions
