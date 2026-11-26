"""Apply one analysis task to successive portions of the manual and save each result.

Sending a manual in smaller portions leaves room for detailed answers. If an AI
reply is cut short, the affected portion is split and tried as smaller requests;
the incomplete answer is kept in the history, not accepted as finished content.
Saved results allow later continuation without repeating completed work."""

import hashlib
import json

from pydantic import ValidationError

from workbench.agentic_workflow.restore_source_group_plan import load_plan
from workbench.agentic_workflow.reuse_saved_model_responses import (
    find_response,
    request_record,
)
from workbench.agentic_workflow.schedule_independent_model_tasks import completed_tasks
from workbench.agentic_workflow.validate_and_correct_model_json import (
    ModelJSONError,
    correction_prompt,
    parse_response,
    validation_message,
)
from workbench.job_storage import job_files_and_audit_log as storage
from workbench.model_access.code_owned_source_evidence import (
    VERSION,
    source_response_schema,
)
from workbench.model_access.model_requests_and_responses import (
    InvalidModelResponseError,
    ModelError,
    OutputLimitError,
    Request,
)
from workbench.model_prompts.shared_model_instructions import SYSTEM


def digest(value):
    """Identify saved task inputs so changed work cannot reuse an unrelated checkpoint.

    Args:
        value: JSON-compatible source, prompt or task description.
    Returns:
        SHA-256 of sorted JSON, stable across dictionary insertion orders.
    """
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def split_batch(batch):
    """Divide a source batch after output truncation without discarding its text.

    Args:
        batch: Nonempty source records from the failed task.
    Returns:
        Two smaller batches, preserving IDs/pages. A single long record uses a small
        overlap; an already tiny record raises ModelError rather than retry forever.
    """
    if len(batch) > 1:
        middle = len(batch) // 2
        return [batch[:middle], batch[middle:]]
    item = batch[0]
    if len(item["text"]) <= 160:
        raise ModelError(
            "Even a small source passage exceeded the model output allowance; manual review is needed"
        )
    middle = len(item["text"]) // 2
    overlap = min(40, middle // 4)
    offset = item.get("source_offset", 0)
    return [
        [{**item, "text": item["text"][: middle + overlap]}],
        [
            {
                **item,
                "text": item["text"][middle - overlap :],
                "source_offset": offset + middle - overlap,
            }
        ],
    ]


def restored_response(job_id, record, schema, task):
    """Recheck a completed task against its original request and provider response.

    Args:
        job_id: Job containing private request/response files.
        record: Exact current request fields, including provider/model and allowance.
        schema: Response class to validate again.
        task: Completed task entry containing its previously saved response.
    Returns:
        Revalidated response. Missing or altered receipts raise ModelError before any
        paid request; changed task results are not silently accepted or regenerated.
    """
    saved = find_response(job_id, record)
    if saved is None:
        raise ModelError("A completed task no longer matches its saved model response")
    try:
        response = parse_response(schema, saved["text"])
    except (ValidationError, ModelJSONError) as error:
        corrected_record = {
            **record,
            "prompt": correction_prompt(record["prompt"], saved["text"], error),
        }
        corrected = find_response(job_id, corrected_record)
        if corrected is None:
            raise ModelError(
                "A completed task has no matching corrected response"
            ) from None
        try:
            response = parse_response(schema, corrected["text"])
        except (ValidationError, ModelJSONError) as second:
            raise ModelError(validation_message(second)) from None
    if response.model_dump() != task["response"]:
        raise ModelError("A saved task result differs from its original response")
    return response


def run_stage(
    job_id,
    name,
    title,
    batches,
    prompt,
    schema,
    run,
    fraction,
    on_progress=None,
    planning_version=None,
    isolate_invalid_replies=False,
):
    """Complete one task type, preserving answers and subdivisions across continuations.

    Args:
        job_id: Existing job receiving stage progress and model receipts.
        name: Internal stage filename, supplied by application code, not a user.
        title: Plain stage label shown while a request is running.
        batches: Initial source batches, including all text this stage is responsible for.
        prompt: Function that builds this task's instructions from one source batch.
        schema: Strict response type for this task only.
        run: Authorized model-call owner; its per-slice spending limits still apply.
        fraction: Fraction of the configured text model's documented output maximum.
        planning_version: Optional source-group policy version recorded for new plans.
            Existing stage plans keep their original policy and request identities.
        isolate_invalid_replies: Record exhausted response corrections as failed groups and
            continue unrelated groups. Provider, budget and program failures still propagate.
        on_progress: Optional callback receiving completed (batch, response) pairs and
            the current total, after checkpoint validation and each new completion.
    Returns:
        Completed (batch, response) pairs. Writes a stage file and progress records.
        Independent groups overlap up to run.concurrency. Results keep source order.
        Truncated batches split at most eight levels, with an audit event. Opt-in invalid
        reply isolation saves failed groups without retrying them on continuation. Other errors
        propagate; a budget pause preserves completed work without automatic renewal.
    """
    path = storage.job_dir(job_id) / f"{name}-stage.json"
    cap = run.service.output_allowance("text", fraction)
    initial = {
        "prompts": [prompt(batch) for batch in batches],
        "evidence_binding_version": VERSION,
        "source_batches": batches,
        "schema": schema.model_json_schema(),
        "system": SYSTEM,
        "identity": run.service.identity("text"),
        "cap": cap,
    }
    fingerprint = digest(initial)
    new_plan = not path.exists()
    saved = load_plan(path, fingerprint, batches, cap, fraction)
    if new_plan and planning_version is not None:
        saved["planning_version"] = planning_version
        storage.save(path, saved)
    storage.event(
        job_id,
        "task_started",
        task=name,
        source_groups=len(saved["tasks"]),
        output_allowance=cap,
        restoring=run.replay,
    )
    workers = getattr(run, "concurrency", 1)

    def request_for(task):
        """Build the unchanged request so concurrent work retains exact replay identity.

        Args:
            task: One saved source group and its subdivision depth.
        Returns:
            Neutral request with the existing prompt, schema and output allowance.
        """
        task_prompt = prompt(task["batch"])
        return Request(
            task_prompt,
            SYSTEM,
            max_tokens=cap,
            schema=source_response_schema(schema, task_prompt).model_json_schema(),
        )

    def execute(task):
        """Send one independent source-group task through normal bounded correction.

        Args:
            task: Pending source group; this worker does not edit the stage file.
        Returns:
            Validated response; errors propagate to the window collector.
        """
        request = request_for(task)
        return run.call("text", request.prompt, schema, cap=cap)

    def publish_progress():
        """Publish all saved completions in source order, including non-prefix results.

        Args:
            None; reads the coordinator-owned stage plan.
        Returns:
            Ordered completed pairs. Updates accepted-result callbacks and counts;
            workers never call callbacks or overwrite the shared stage plan.
        """
        pairs = [
            (task["batch"], schema.model_validate(task["response"]))
            for task in saved["tasks"]
            if task["response"] is not None
        ]
        if on_progress:
            on_progress(pairs, len(saved["tasks"]))
        storage.update(
            job_id,
            task_progress={
                "task": name,
                "completed": len(pairs),
                "failed": sum(bool(task.get("failure")) for task in saved["tasks"]),
                "total": len(saved["tasks"]),
                "output_allowance": cap,
                "pages": [],
                "parallel_limit": workers,
            },
        )
        return pairs

    # Validate every saved completion before dispatch, not just a contiguous prefix.
    for task in saved["tasks"]:
        if task["response"] is not None:
            record = request_record(
                "text", request_for(task), run.service.identity("text")
            )
            restored_response(
                job_id,
                record,
                source_response_schema(schema, request_for(task).prompt),
                task,
            )
    results = publish_progress()
    submitted = {}

    def next_pending_source_group():
        """Supply unsent groups and newly split children as worker slots become free.

        Args:
            None; reads the coordinator-owned plan between completed outcomes.
        Returns:
            Next pending task, or None when no unsent group is currently available.
            Retains admitted objects so their identities cannot be recycled.
            Split parents disappear from the plan; children retain original text.
        """
        task = next(
            (
                t
                for t in saved["tasks"]
                if t["response"] is None
                and not t.get("failure")
                and id(t) not in submitted
            ),
            None,
        )
        if task is not None:
            submitted[id(task)] = task
        return task

    storage.update(
        job_id,
        stage=title,
        message=f"{title}: up to {workers} requests at once; new groups start as slots become free.",
    )
    errors = []
    for task, response, error in completed_tasks(
        next_pending_source_group,
        execute,
        workers,
        can_start=lambda: run.dispatch_error is None,
        recoverable_error=(OutputLimitError, InvalidModelResponseError)
        if isolate_invalid_replies
        else OutputLimitError,
    ):
        if isinstance(error, OutputLimitError):
            if task["depth"] >= 8:
                errors.append(
                    ModelError(
                        "Source subdivision limit reached; remaining work needs review"
                    )
                )
                run.stop_dispatch(errors[-1])
            else:
                try:
                    children = split_batch(task["batch"])
                except ModelError as split_error:
                    errors.append(split_error)
                    run.stop_dispatch(split_error)
                    continue
                index = next(
                    i for i, candidate in enumerate(saved["tasks"]) if candidate is task
                )
                saved["tasks"][index : index + 1] = [
                    {"batch": child, "depth": task["depth"] + 1, "response": None}
                    for child in children
                ]
                storage.event(
                    job_id,
                    "task_split",
                    task=name,
                    source_ids=[i["id"] for i in task["batch"]],
                    reason="Output limit reached; incomplete response rejected",
                    child_count=2,
                )
        elif isolate_invalid_replies and isinstance(error, InvalidModelResponseError):
            task["failure"] = str(error)
            storage.event(
                job_id,
                "source_group_rejected",
                task=name,
                source_ids=[item["id"] for item in task["batch"]],
                reason=str(error),
            )
        elif error is not None:
            errors.append(error)
            run.stop_dispatch(error)
        else:
            task["response"] = response.model_dump()
        storage.save(path, saved)
        results = publish_progress()
    if errors:
        # All already-started tasks have settled and successful replies are saved.
        # Prefer an actual failure over a budget pause when both happened.
        from workbench.agentic_workflow.model_call_allowances import BudgetPause

        raise next(
            (error for error in errors if not isinstance(error, BudgetPause)),
            errors[0],
        )
    saved["complete"] = True
    storage.save(path, saved)
    storage.event(
        job_id, "task_completed", task=name, groups=len(results), output_allowance=cap
    )
    return results
