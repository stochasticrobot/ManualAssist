"""Extract facts from the manual and keep the original passages behind them.

The application needs structured specifications, warnings and operating details
for its reference pages and later guides. This file sends manageable portions of
text for extraction, checks the returned evidence and saves completed work so a
paused analysis can continue without starting over."""

import json
from workbench.job_storage import job_files_and_audit_log as storage
from workbench.data_models.analysis_and_question_models import FactExtraction
from workbench.model_prompts.analysis_task_prompts import facts_prompt
from workbench.agentic_workflow.run_source_group_tasks import run_stage
from workbench.manual_analysis.group_sources_for_fact_extraction import (
    build_fact_batches,
    saved_grouping_version,
)
from workbench.manual_analysis.validate_extracted_facts import accept, EMPTY


def source_batches(path, document, allowance=6000):
    """Read the saved fact-source groups or plan new ones for a parsed document.

    Args:
        path: Private job directory containing optional stage plans.
        document: Parsed manual whose original IDs and text must stay unchanged.
        allowance: Fact output allowance used before a task plan has been saved.
    Returns:
        Ordered source groups and plan version 3. Saved subdivisions are used for
        accurate progress; this read-only helper makes no model calls.
    """
    plan = path / "facts-stage.json"
    batches = (
        [task["batch"] for task in json.loads(plan.read_text())["tasks"]]
        if plan.exists()
        else build_fact_batches(document["items"], allowance)
    )
    return batches, 3


def extract(job_id, document, run):
    """Run fact-only requests, saving accepted results after each completed group.

    Args:
        job_id: Job receiving fact progress and rejected proposals.
        document: Complete parsed manual.
        run: Authorized model-call owner; continuations replay exact completed answers.
    Returns:
        Accepted facts and rejected proposals. Results are saved in facts-checkpoint.json;
        the task runner verifies exact saved responses in facts-stage.json on Resume.
    """
    path = storage.job_dir(job_id)
    base = {k: ([] if isinstance(v, list) else v) for k, v in EMPTY.items()}
    cap = run.service.output_allowance("text", 0.75)
    planning_version = saved_grouping_version(path / "facts-stage.json")
    batches = build_fact_batches(document["items"], cap, planning_version)
    result = {}

    def save_progress(results, total):
        """Rebuild accepted fact lists from revalidated answers and save observed counts.

        Args:
            results: Completed source/FactExtraction response pairs in source order.
            total: Current number of new groups, including any output-limit subdivisions.
        Returns:
            None; updates the local result and derived facts checkpoint. It does not
            alter original receipts or treat an incomplete response as an accepted fact.
        """
        result.clear()
        result.update(
            {k: list(v) if isinstance(v, list) else v for k, v in base.items()}
        )
        for batch, response in results:
            accepted = accept(response, batch)
            for key, values in accepted.items():
                result[key].extend(values)
        result.update(
            batches_processed=len(results),
            batches_total=total,
            batch_version=3,
        )
        storage.save(path / "facts-checkpoint.json", result)

    run_stage(
        job_id,
        "facts",
        "Extract facts",
        batches,
        facts_prompt,
        FactExtraction,
        run,
        0.75,
        save_progress,
        planning_version=planning_version,
    )
    if not result:
        save_progress([], 0)
    storage.save(path / "rejected.json", result["rejected"])
    return result
