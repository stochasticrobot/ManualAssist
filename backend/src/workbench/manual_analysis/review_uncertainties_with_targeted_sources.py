"""Investigate whether a reported problem is answered elsewhere in the manual.

Checks start with nearby text and relevant search results, then consider portions
not yet checked. The application saves progress and retains the original question
and evidence so a pause or later disagreement does not erase the reason for the
investigation. Unsettled questions remain visible rather than becoming approval."""

import json

from workbench.agentic_workflow.model_call_allowances import (
    MAX_REQUEST_INPUT,
    estimate_input,
)
from workbench.agentic_workflow.schedule_independent_model_tasks import completed_tasks
from workbench.data_models.analysis_and_question_models import (
    TargetedFindingAssessment,
    TargetedFindingsReview,
)
from workbench.job_storage import job_files_and_audit_log as storage
from workbench.manual_analysis.check_source_quotations import (
    anchored,
    source_map,
)
from workbench.manual_analysis.group_sources_for_uncertainty_review import build_batches
from workbench.manual_analysis.select_uncertainty_review_sources import (
    review_source_batches,
    search_parsed_document,
)
from workbench.model_access.code_owned_source_evidence import (
    evidence_task,
    source_response_schema,
)
from workbench.model_access.model_requests_and_responses import (
    InvalidModelResponseError,
    ModelError,
    Request,
)
from workbench.model_prompts.shared_model_instructions import SYSTEM

EFFECTS = {
    "resolved": "answers_question",
    "false_positive": "refutes_proposal",
    "supported_issue": "shows_conflict",
    "needs_more_evidence": "inconclusive",
}


def source_keys(batch):
    """Identify exact supplied source windows so completed coverage is not repeated.

    Args:
        batch: Original source records or bounded windows.
    Returns:
        Hashable ID/offset/text tuples; no metadata is mistaken for source coverage.
    """
    return {(i["id"], i.get("source_offset", 0), i["text"]) for i in batch}


def invalid_decision(assessment, batch, finding):
    """Check explicit decision consistency and all citations without reading keywords.

    Args:
        assessment: Validated structured model assessment.
        batch: Only passages actually supplied in this request.
        finding: Original proposal, used to require its evidence for dismissal.
    Returns:
        A concrete correction reason, or None. Matching quotations does not prove
        semantic entailment; unsupported closing decisions cannot stop the search.
    """
    if EFFECTS[assessment.disposition] != assessment.evidence_effect:
        return "The decision and evidence_effect disagree."
    if assessment.disposition == "needs_more_evidence":
        return None
    if not set(finding["evidence_ids"]) <= {item["id"] for item in batch}:
        return (
            "Original uncertainty evidence is unavailable; closing is not established."
        )
    citations = assessment.citations
    if not citations or not all(
        anchored(c.evidence_id, c.quote, source_map(batch)) for c in citations
    ):
        return "Every closing decision must select its supporting passages."
    if assessment.disposition in ("false_positive", "supported_issue") and not set(
        finding["evidence_ids"]
    ) <= {c.evidence_id for c in citations}:
        return "Dismissal or conflict must select each original passage behind the proposal."
    if (
        assessment.disposition == "supported_issue"
        and len({(c.evidence_id, c.quote) for c in citations}) < 2
    ):
        return "An explicit conflict needs two distinct supporting passages."
    return None


def review_request_fits(prompt):
    """Check the full evidence-bound review using the production input estimate.

    Args:
        prompt: Review or recheck text with its private source registry attached.
    Returns:
        True if instructions, selected passages and the model-visible response
        schema fit the per-request allowance. No provider call or budget charge occurs.
    """
    bound = source_response_schema(TargetedFindingsReview, prompt)
    return (
        estimate_input(Request(prompt, SYSTEM, schema=bound.model_json_schema()))
        <= MAX_REQUEST_INPUT
    )


def assess_batch(job_id, pending, batch, phase, run, total, position, count):
    """Request a bounded review and recheck structurally contradictory decisions once.

    Args:
        job_id: Job receiving accurate current-work progress.
        pending: Indexed original findings assigned to this request; private discovery
            windows are already in batch and are not duplicated in model input.
        batch: Original source passages actually checked.
        phase: local, targeted or broader, shown in progress and saved prompts.
        run: Budgeted, receipt-replaying call owner.
        total: Total proposed findings for progress.
        position: Zero-based batch position in this phase.
        count: Total selected batches for this phase, not whole-job completion.
    Returns:
        Assessments and validation failures. A failed correction remains unresolved;
        a malformed recheck retains the first assessments as unverified, without
        coverage credit. Provider/budget errors and omission/duplication still raise.
        Calls and corrections use the normal
        budget and immutable receipts; pauses replay the same requests on Resume.
    """
    pending = {
        i: {k: v for k, v in f.items() if k != "evidence_windows"}
        for i, f in pending.items()
    }
    names = {
        "local": "Check cited passages and neighbours",
        "targeted": "Check targeted search results",
        "broader": "Check remaining manual passages",
    }
    storage.update(
        job_id,
        stage=names[phase],
        message=f"{names[phase]}: {len(pending)} of {total} findings; source group {position + 1} of {count}.",
        task_progress={
            "task": "uncertainty_review",
            "parallel_limit": getattr(run, "concurrency", 1),
            "review_phase": phase,
            "current_findings": [{"index": i, **f} for i, f in pending.items()],
            "completed": position,
            "total": count,
            "pages": sorted({i["page"] for i in batch}),
            "output_allowance": run.service.output_allowance("text", 0.5),
        },
    )
    prompt = evidence_task(
        "Check each proposed uncertainty against the supplied passages. Resolve it when the evidence answers it; "
        "mark false_positive when it misreads the evidence, supported_issue only for an explicit conflict, "
        "otherwise needs_more_evidence. Preserve model applicability and conditions. Select supporting passages "
        "for closing decisions; a conflict needs distinct evidence. Give concrete searches for remaining gaps. "
        "Match evidence_effect to your decision: answers_question, refutes_proposal, shows_conflict or inconclusive. "
        "Return one assessment for each supplied index.",
        {"findings": [{"index": i, **f} for i, f in pending.items()]},
        batch,
    )
    if not review_request_fits(prompt):
        # Do not dispatch an oversized request: dispatch failure stops all workers.
        # Retained anchors and prior answers cannot be silently truncated to fit.
        reason = "Retained evidence exceeds the per-request input allowance; this question remains unverified."
        return [
            TargetedFindingAssessment(
                index=i,
                disposition="needs_more_evidence",
                evidence_effect="inconclusive",
                reason=reason,
                citations=[],
                search_queries=[],
            )
            for i in pending
        ], {i: reason for i in pending}
    reply = run.call(
        "text",
        prompt,
        TargetedFindingsReview,
        cap=run.service.output_allowance("text", 0.5),
    )
    if sorted(a.index for a in reply.assessments) != sorted(pending):
        raise ModelError("Finding review omitted or duplicated a requested assessment")
    failures = {
        a.index: invalid_decision(a, batch, pending[a.index]) for a in reply.assessments
    }
    if any(failures.values()):
        storage.event(
            job_id,
            "review_decision_recheck",
            phase=phase,
            failures={i: reason for i, reason in failures.items() if reason},
        )
        recheck = evidence_task(
            "Recheck the listed decisions against the original passages. Return all assigned assessments with consistent decisions and supporting passage selections.",
            {
                "findings": [{"index": i, **f} for i, f in pending.items()],
                "previous": reply.model_dump(),
                "problems": failures,
            },
            batch,
        )
        if not review_request_fits(recheck):
            return reply.assessments, {
                i: reason
                or "Recheck context exceeds the input allowance; decision remains unverified."
                for i, reason in failures.items()
            }
        try:
            reply = run.call(
                "text",
                recheck,
                TargetedFindingsReview,
                cap=run.service.output_allowance("text", 0.5),
                correct=False,
            )
        except InvalidModelResponseError as error:
            # A malformed recheck cannot validate the disputed initial decision.
            # Keep its failed checks, with no coverage credit or invented citations.
            storage.event(
                job_id,
                "review_recheck_invalid",
                phase=phase,
                message=str(error),
                finding_indices=list(pending),
            )
            failures = {
                index: reason
                or "Recheck returned invalid fields; decision remains unverified."
                for index, reason in failures.items()
            }
            return reply.assessments, failures
        if sorted(a.index for a in reply.assessments) != sorted(pending):
            raise ModelError(
                "Finding recheck omitted or duplicated a requested assessment"
            )
        failures = {
            a.index: invalid_decision(a, batch, pending[a.index])
            for a in reply.assessments
        }
    return reply.assessments, failures


def finding_groups(findings):
    """Share source reads across small groups without creating oversized prompts.

    Args:
        findings: Unresolved proposal dictionaries from extraction.
    Returns:
        Lists of (original index, finding) pairs, at most eight per group and usually
        at most 6,000 serialized bytes. A single larger finding remains intact.
    """
    groups, current = [], []
    for index, finding in enumerate(findings):
        pair = (index, finding)
        if current and (
            len(current) >= 8 or len(json.dumps(current + [pair]).encode()) > 6000
        ):
            groups.append(current)
            current = []
        current.append(pair)
    if current:
        groups.append(current)
    return groups


def retain_question_evidence(document, pending, checks, batch):
    """Keep the original question and previously selected evidence together.

    Args:
        document: Immutable original parsed source records.
        pending: Findings assigned to this request, keyed by original index.
        checks: Earlier validated or invalid assessments for each finding.
        batch: New passages under examination, including exact source windows.
    Returns:
        Copied exact discovery windows (or full anchors for older proposals),
        earlier validly selected evidence and new passages,
        deduplicated by identity and exact window. Invalid assessments add nothing.
        Missing original sources cannot approve closing decisions; the decision validator
        keeps them unresolved without stopping unrelated findings.
        A window whose offset/text no longer matches the document raises ModelError.
        Neither the document nor saved assessments are changed.
    """
    import copy

    originals = {item["id"]: item for item in document["items"]}
    retained = []
    for index, finding in pending.items():
        windows = finding.get("evidence_windows", [])
        for sid in finding["evidence_ids"]:
            original = originals.get(sid)
            if original is None:
                continue
            selected = [window for window in windows if window["id"] == sid]
            if selected:
                for window in selected:
                    start = window.get("source_offset", 0)
                    if (
                        original["text"][start : start + len(window["text"])]
                        != window["text"]
                    ):
                        raise ModelError(
                            "Uncertainty discovery window no longer matches its original source."
                        )
                    retained.append(window)
            else:
                # Older proposals lack discovery windows. Preserve their full
                # anchor; assess_batch explicitly refuses it if it cannot fit.
                retained.append(original)
        for row in checks[index]:
            if row.get("validation_error"):
                continue
            for citation in row.get("citations", []):
                original = originals.get(citation["evidence_id"])
                if original is None or citation["quote"] not in original["text"]:
                    continue
                start = original["text"].index(citation["quote"])
                retained.append(
                    {**original, "text": citation["quote"], "source_offset": start}
                )
    unique = {}
    for item in retained + batch:
        key = (item["id"], item.get("source_offset", 0), item["text"])
        unique.setdefault(key, copy.deepcopy(item))
    return list(unique.values())


def review_finding_group(job_id, group, document, full_batches, run, total):
    """Follow dependent review steps for one independent group of findings.

    Args:
        job_id: Existing job receiving receipts and merged review progress.
        group: Indexed proposals sharing bounded source checks, at most eight.
        document: Original parsed sources for local context and lexical search.
        full_batches: Complete source batches for unresolved broader checks.
        run: Shared thread-safe call allowance and exact-response replay owner.
        total: Total proposed findings across all concurrently reviewed groups.
    Returns:
        Per-finding checks and covered source keys. Local, targeted and broader
        steps remain sequential within this group; failures propagate after receipts.
        Progress from separate groups is merged under the storage lock.
    """
    checks = {i: [] for i, _ in group}
    seen = {i: set() for i, _ in group}
    pending = {i: f for i, f in group if not any(row["terminal"] for row in checks[i])}
    queries = {}
    for phase in ("local", "targeted", "broader"):
        if not pending:
            break
        if phase == "targeted":
            for i, finding in pending.items():
                requested = queries.get(i) or [finding["issue"]]
                queries[i] = requested
                matches = search_parsed_document(document, requested)
                storage.event(
                    job_id,
                    "tool_result",
                    tool="search_parsed_document",
                    finding_index=i,
                    queries=requested,
                    evidence_ids=[item["id"] for item in matches],
                    method="literal phrase and word overlap; not semantic search",
                )
        batches = (
            full_batches
            if phase == "broader"
            else review_source_batches(document, list(pending.items()), phase, queries)
        )
        for number, batch in enumerate(batches):
            keys = source_keys(batch)
            # Inspect cited context first; do not repeat sources already checked
            # during this review when progressing to broader coverage.
            assigned = {
                i: f
                for i, f in pending.items()
                if phase == "local" or not keys <= seen[i]
            }
            if not assigned:
                continue
            review_batch = retain_question_evidence(document, assigned, checks, batch)
            assessments, failures = assess_batch(
                job_id,
                assigned,
                review_batch,
                phase,
                run,
                total,
                number,
                len(batches),
            )
            review_batches = {i: review_batch for i in assigned}
            if len(assigned) > 1 and all(
                reason and reason.startswith("Retained evidence exceeds")
                for reason in failures.values()
            ):
                # Retry preparation independently, not the oversized request. An
                # enormous legacy anchor must not prevent a small question's review.
                assessments, failures = [], {}
                for index, finding in assigned.items():
                    packet = retain_question_evidence(
                        document, {index: finding}, checks, batch
                    )
                    rows, errors = assess_batch(
                        job_id,
                        {index: finding},
                        packet,
                        phase,
                        run,
                        total,
                        number,
                        len(batches),
                    )
                    assessments.extend(rows)
                    failures.update(errors)
                    review_batches[index] = packet
            for assessment in assessments:
                i = assessment.index
                valid = not failures[i]
                terminal = valid and assessment.disposition != "needs_more_evidence"
                row = {
                    "phase": phase,
                    "batch": number + 1,
                    **assessment.model_dump(),
                    "validation_error": failures[i],
                    "terminal": terminal,
                    "resolution_anchor_matched": terminal
                    and assessment.disposition in ("resolved", "false_positive"),
                    "source_ids": [item["id"] for item in review_batches[i]],
                }
                checks[i].append(row)
                if valid:
                    seen[i].update(keys)
                if assessment.search_queries:
                    queries[i] = assessment.search_queries
                if terminal:
                    del pending[i]
            with storage.LOCK:
                progress_path = storage.job_dir(job_id) / "finding-review-progress.json"
                progress = json.loads(progress_path.read_text())
                progress["checks"].update({str(i): rows for i, rows in checks.items()})
                progress.update(phase=phase, finding_indices=list(progress["checks"]))
                storage.save(progress_path, progress)
    return checks, seen


def reconcile(job_id, profile, document, run):
    """Resolve local/searchable questions before broader checks, reusing old evidence.

    Args:
        job_id: Job with saved requests, progress and audit events.
        profile: Original proposed findings and other analysis outputs.
        document: Unchanged parsed sources used by every review phase.
        run: Current authorized work allowance and exact-response replay owner.
    Returns:
        Profile preserving original proposals, per-request checks, actual coverage,
        dismissed/resolved findings and retained concerns. Unresolved proposals are
        never called proven omissions. Current requests replay normally after a pause. No original receipts are changed.
    """
    findings = profile["findings"]
    full_batches = build_batches(document["items"])
    all_checks, all_seen = {}, {}
    groups = finding_groups(findings)
    workers = getattr(run, "concurrency", 1)
    storage.save(
        storage.job_dir(job_id) / "finding-review-progress.json",
        {
            "version": 2,
            "phase": "local",
            "finding_indices": [],
            "total_findings": len(findings),
            "checks": {},
            "total_batches": len(full_batches),
            "parallel_limit": workers,
        },
    )

    def execute(group):
        """Review one independent proposal group while preserving its decision order.

        Args:
            group: Indexed proposals assigned to a single worker.
        Returns:
            Checks and source coverage, or a propagated model/budget failure.
        """
        return review_finding_group(
            job_id, group, document, full_batches, run, len(findings)
        )

    errors = []
    for group, result, error in completed_tasks(
        groups, execute, workers, can_start=lambda: run.dispatch_error is None
    ):
        if error is not None:
            errors.append(error)
            run.stop_dispatch(error)
        else:
            checks, seen = result
            all_checks.update(checks)
            all_seen.update(seen)
    if errors:
        from workbench.agentic_workflow.model_call_allowances import BudgetPause

        raise next(
            (error for error in errors if not isinstance(error, BudgetPause)),
            errors[0],
        )
    review, kept = [], []
    for i, finding in enumerate(findings):
        checked = all_checks[i]
        terminal = next((row for row in checked if row["terminal"]), None)
        disposition = terminal["disposition"] if terminal else "keep"
        covered = sum(source_keys(batch) <= all_seen[i] for batch in full_batches)
        reason = (
            terminal["reason"]
            if terminal
            else f"No source-anchored conclusion accepted; {covered} of {len(full_batches)} complete source batches checked. This remains an unverified proposal, not proof of missing information."
        )
        removed = disposition in ("resolved", "false_positive")
        review.append(
            {
                "index": i,
                "disposition": disposition,
                "reason": reason,
                "resolution_anchor_matched": removed,
                "batches_checked": covered,
                "batches_total": len(full_batches),
                "checks": checked,
            }
        )
        if not removed:
            kept.append({**finding, "review_reason": reason})
    storage.event(
        job_id,
        "finding_validation",
        proposed=len(findings),
        unresolved=len(kept),
        resolved=len(findings) - len(kept),
        false_positives=sum(row["disposition"] == "false_positive" for row in review),
        basis="Nearby context, targeted lexical search, then uncovered sources; quotation matching is not semantic verification",
    )
    return {
        **profile,
        "original_findings": findings,
        "findings": kept,
        "finding_review": review,
    }
