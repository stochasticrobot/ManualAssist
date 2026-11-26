"""Look for unclear or conflicting instructions and check whether the manual resolves
them.

A question raised from one passage may be answered elsewhere. This file collects
those questions, arranges further checks and saves the findings that readers need
to see. It keeps this work separate from extracting ordinary facts."""

import json

from workbench.agentic_workflow.run_source_group_tasks import run_stage
from workbench.data_models.analysis_and_question_models import UncertaintyCandidates
from workbench.job_storage import job_files_and_audit_log as storage
from workbench.manual_analysis.group_related_uncertainty_proposals import (
    group_related_uncertainty_proposals,
)
from workbench.manual_analysis.group_sources_for_uncertainty_review import build_batches
from workbench.manual_analysis.review_uncertainties_with_targeted_sources import (
    reconcile,
)
from workbench.model_prompts.analysis_task_prompts import uncertainty_prompt


def review_uncertainties(job_id, profile, document, run):
    """Discover possible gaps separately from fact extraction and check their coverage.

    Args:
        job_id: Job receiving uncertainty proposals and final review records.
        profile: Task A facts and metadata; earlier batch-local findings are not reused.
        document: Complete parsed manual, read in bounded source groups.
        run: Authorized model-call owner; completed discovery/review calls can replay.
    Returns:
        Profile with checked findings and their original proposals. Unsupported source
        IDs or proposals without a specific source are retained as rejected records,
        not presented as manual defects. A pause leaves stage progress on disk.
    """
    batches = build_batches(document["items"])
    results = run_stage(
        job_id,
        "uncertainties",
        "Identify ambiguities",
        batches,
        uncertainty_prompt,
        UncertaintyCandidates,
        run,
        0.5,
    )
    findings, rejected, proposal_windows = [], [], []
    for batch, response in results:
        ids = {item["id"] for item in batch}
        for finding in response.findings:
            value = finding.model_dump()
            if not finding.evidence_ids or not set(finding.evidence_ids) <= ids:
                rejected.append(value)
            else:
                if value not in findings:
                    findings.append(value)
                    proposal_windows.append([])
                # Keep the exact discovery windows, not the unsplit source with
                # the same ID. Group identity remains the original proposal only.
                windows = proposal_windows[findings.index(value)]
                for item in batch:
                    if item["id"] in finding.evidence_ids and item not in windows:
                        windows.append(item)
    path = storage.job_dir(job_id)
    storage.save(path / "uncertainties-rejected.json", rejected)
    findings = group_related_uncertainty_proposals(job_id, findings, run)
    group_path = path / "uncertainty-groups.json"
    membership = (
        json.loads(group_path.read_text())["groups"]
        if group_path.exists()
        else [[i] for i in range(len(findings))]
    )
    findings = [
        {
            **finding,
            "evidence_windows": [
                window for original in members for window in proposal_windows[original]
            ],
        }
        for finding, members in zip(findings, membership, strict=True)
    ]
    profile = reconcile(job_id, {**profile, "findings": findings}, document, run)
    storage.save(
        path / "findings-complete.json",
        {
            "complete": True,
            "findings": profile["findings"],
            "original_findings": profile["original_findings"],
            "finding_review": profile["finding_review"],
        },
    )
    return profile
