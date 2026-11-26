"""Explain which parts of a manual analysis are waiting, running or finished.

The browser needs a useful progress display even after a pause or restart. These
helpers read saved work and the current status to produce that display, without
calling an AI or treating a started task as completed."""

PHASES = [
    (
        "inspect",
        "Inspect the document",
        "Identify its purpose and inspect selected pages, tables or images.",
    ),
    (
        "extract",
        "A. Extract facts",
        "Extract specifications, warnings, instructions, parts and maintenance facts with source quotations.",
    ),
    (
        "faq",
        "C1. Generate FAQ",
        "Create cited questions and answers using the facts and original passages.",
    ),
    (
        "troubleshooting",
        "C2. Extract troubleshooting checks",
        "Preserve independent documented checks; investigate connected paths in the guide stage.",
    ),
    ("procedures", "D. Plan installation, maintenance and troubleshooting",
     "Investigate related passages, assemble procedures and review their source support."),
    (
        "publish",
        "Create reports and exports",
        "Write the profile, decision trees, FAQ, summary and CSV files.",
    ),
    (
        "index",
        "Build the searchable knowledge base",
        "Write source chunks for cited question answering.",
    ),
    (
        "validate",
        "E. Identify and check uncertainties",
        "Check cited context, search relevant passages, then examine remaining sources when needed.",
    ),

]


def phase_status(path, result, completed, total):
    """Assign stage statuses from artifacts and the current worker stage.

    Args:
        path: Existing job directory, read only.
        result: API detail data including state and optional artifacts.
        completed: Completed extraction batches observed in the checkpoint.
        total: Actual extraction batch count.
    Returns:
        Stage dictionaries and active stage ID. Failed/paused work is not complete
        merely because some earlier artifacts exist.
    """
    state = result["state"]
    profile = result.get("profile") or {}
    flags = [
        bool(result.get("decisions")) or completed > 0 or bool(profile),
        total > 0 and completed == total,
        (path / "faq-complete.json").exists(),
        ((path / "troubleshooting_checks-complete.json").exists() or (path / "troubleshooting-complete.json").exists()),
        (path / "procedure-guides-complete.json").exists(),
        (path / "report.html").exists(),
        bool(result.get("chunks")),
        "finding_review" in profile or (path / "findings-complete.json").exists(),
    ]
    stage = state.get("stage", "")
    active = (
        "procedures"
        if "procedure" in stage.lower()
        else "extract"
        if "Extract" in stage
        else "validate"
        if "Validate findings" in stage
        or "Identify ambiguities" in stage
        or (state.get("task_progress") or {}).get("task") == "uncertainty_review"
        and stage.startswith("Check ")
        else "faq"
        if "Generate FAQ" in stage
        else "troubleshooting"
        if "Generate troubleshooting" in stage
        else "publish"
        if "Publish" in stage
        else "index"
        if "vector" in stage
        else "inspect"
    )
    if active == "inspect" and not result.get("decisions"):
        active = "extract"
    stopped = state["status"] in ("failed", "interrupted", "paused")
    if stopped:
        active = next(
            (key for flag, (key, _, _) in zip(flags, PHASES)
             if not flag and (key != "inspect" or result.get("decisions"))), "index"
        )
    phases = []
    for flag, (key, title, description) in zip(flags, PHASES):
        # Historical runs retain their inspection row; new runs never advertise it.
        if key == "inspect" and not result.get("decisions"):
            continue
        status = "complete" if flag else "pending"
        if not flag and key == active:
            if state["status"] == "analyzing":
                status = "running"
            elif stopped:
                status = "paused" if state["status"] == "paused" else "blocked"
        phases.append(
            {"id": key, "title": title, "description": description, "status": status}
        )
    return phases, active


def current_message(state, active, progress, profile, chunks):
    """Explain what is happening at the active stage using observed counts.

    Args:
        state: Saved job status, stage and optional operation detail.
        active: Current phase ID from phase_status.
        progress: Observed completed/total batches and accepted/rejected facts.
        profile: Optional saved extraction profile.
        chunks: Saved searchable chunks, or an empty list.
    Returns:
        Plain title and message. Historical character-limit failures explicitly say
        that restriction has been removed and require a deliberate Resume action.
    """
    status = state["status"]
    if status == "analyzing":
        titles = {key: title for key, title, _ in PHASES}
        messages = {
            "inspect": "The agent is selecting source pages, tables or images to inspect before extraction.",
            "extract": state.get("message")
            or f"Reading extraction batch {min(progress['completed_batches'] + 1, progress['total_batches'])} of {progress['total_batches']}. {progress['accepted_facts']} facts have matching source quotes.",
            "validate": state.get("message")
            or "Checking reported gaps across all source batches.",
            "faq": state.get("message") or "Generating source-cited FAQ entries.",
            "troubleshooting": state.get("message")
            or "Extracting independent source-supported checks.",
            "procedures": state.get("message") or "Investigating source-linked procedures.",
            "publish": "Writing the generated reports and data files.",
            "index": "Embedding and saving source text for question answering.",
        }
        return {"title": titles[active], "message": messages[active]}
    if status in ("failed", "interrupted", "paused"):
        message = (
            state.get("message")
            or "Processing stopped; completed source artifacts remain available."
        )
        if "100,000" in message or "100000" in message:
            message = "The previous run stopped at the old document-size limit. That limit has been removed. Resume will continue with bounded requests and saved progress."
        return {
            "title": "Analysis paused" if status == "paused" else "Analysis stopped",
            "message": message,
        }
    if status in ("ready", "partial"):
        return {
            "title": "Analysis complete"
            if status == "ready"
            else "Analysis partially complete",
            "message": f"{len((profile or {}).get('facts', []))} facts saved; {len(chunks)} searchable chunks written.",
        }
    return {
        "title": "Run agent analysis",
        "message": "Extract source-linked facts and decision aids, investigate procedures, check findings, and build a searchable knowledge base.",
    }
