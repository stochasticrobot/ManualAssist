"""Send a task to the configured AI and keep a record of what was asked and returned.

Every request needs consistent limits, error handling and usage accounting. This
file saves requests and replies, reuses compatible saved answers, and records
failed attempts as well as successes. It does not decide whether the manual's
instructions are correct."""

import copy
import hashlib
import json
from dataclasses import asdict
from threading import RLock

from pydantic import BaseModel, ValidationError
from typing import Literal
from collections.abc import Sequence
from workbench.model_access.model_requests_and_responses import Image

from workbench.agentic_workflow.model_call_allowances import (
    MAX_CALLS,
    MAX_INPUT_TOKENS,
    MAX_REQUEST_INPUT,
    MAX_VISION_CALLS,
    BudgetPause,
    estimate_input,
)
from workbench.agentic_workflow.reuse_saved_model_responses import (
    SUCCESS_STOPS,
    find_response,
    request_record,
)
from workbench.agentic_workflow.validate_and_correct_model_json import (
    ModelJSONError,
    bounded_correction_prompt,
    parse_response,
    validation_message,
)
from workbench.job_storage import job_files_and_audit_log as storage
from workbench.model_access.code_owned_source_evidence import (
    EvidencePrompt,
    requires_source_binding,
    source_response_schema,
)
from workbench.model_access.configure_model_providers import configured_service
from workbench.model_access.model_requests_and_responses import (
    InvalidModelResponseError,
    ModelError,
    OutputLimitError,
    Request,
)
from workbench.model_prompts.shared_model_instructions import SYSTEM


class Run:
    """One explicitly authorized work slice; injectable service supports offline tests."""

    def __init__(
        self, job_id, limit=MAX_CALLS, service=None, replay=False, concurrency=6
    ):
        """Bind a job and finite allowance without sending a model request.

        Args:
            job_id: Existing job receiving receipts and usage totals.
            limit: Maximum new attempted calls in this work slice.
            service: Optional neutral ModelService; None uses configured adapters.
            replay: Whether exact saved successful requests may be reused for free.
            concurrency: Maximum independent task workers, from one to six. Each
                worker sends at most one request at a time, including corrections.
        Returns:
            None; initializes per-slice counters, preserving cumulative saved totals.
        """
        if not 1 <= concurrency <= 6:
            raise ValueError("Analysis concurrency must be between one and six")
        self.concurrency = concurrency
        self.reservation_lock = RLock()
        self.job_id = job_id
        self.service = service if service is not None else configured_service()
        self.limit = limit
        self.dispatch_error = None
        self.count = 0
        self.estimated_input = 0
        self.reported_input = 0
        self.unknown_input_estimate = 0
        self.input_reservations = {}
        self.replay = replay
        self.request_locks = {}
        self.completed_requests = {}

    def stop_dispatch(self, error):
        """Prevent sibling tasks from starting more requests after a window fails.

        Args:
            error: Original failure or exhausted allowance to propagate to siblings.
        Returns:
            None; already-dispatched calls may finish and retain their responses.
            A new Run on explicit Resume gets an independent open dispatch gate.
        """
        with self.reservation_lock:
            if self.dispatch_error is None:
                self.dispatch_error = error

    def check_allowance(self, role, estimate):
        """Reject oversized requests or pause spent work before network dispatch.

        Args:
            role: Text or vision role; vision has a lifetime per-document cap.
            estimate: Rough input-token estimate including instructions and schema.
        Returns:
            None when admissible; raises ModelError for request/vision constraints
            or BudgetPause when a new explicit continuation is needed.
        """
        if self.dispatch_error is not None:
            raise self.dispatch_error
        if estimate > MAX_REQUEST_INPUT:
            raise ModelError(
                "A single request exceeds the estimated input allowance; its source must be split further."
            )
        if (
            self.count >= self.limit
            or self.reported_input
            + self.unknown_input_estimate
            + sum(self.input_reservations.values())
            + estimate
            > MAX_INPUT_TOKENS
        ):
            raise BudgetPause(
                "This work allowance is complete. Resume to authorize another bounded continuation; completed responses will be reused."
            )
        if role == "vision":
            attempts = sum(
                e["kind"] == "model_start" and e.get("role") == "vision"
                for e in storage.events(self.job_id)
            )
            if attempts >= MAX_VISION_CALLS:
                raise ModelError(
                    "The document’s two image-request attempts have been used."
                )

    def save_input_allowance(self):
        """Expose this slice's measured usage and outstanding estimates separately.

        Args:
            self: Run holding the reservation lock while changing its accounting.
        Returns:
            None; persists a display snapshot, not a replacement for saved receipts.
        """
        storage.update(
            self.job_id,
            input_allowance={
                "limit": MAX_INPUT_TOKENS,
                "reported": self.reported_input,
                "reserved": sum(self.input_reservations.values()),
                "unknown_estimate": self.unknown_input_estimate,
            },
        )

    def settle_input(self, seq, input_tokens):
        """Replace a pending estimate with provider input usage exactly once.

        Args:
            seq: Cumulative call number with a reservation in this work slice.
            input_tokens: Reported input tokens, including zero; None means unknown.
        Returns:
            None; settles under the dispatch lock and saves the budget snapshot.
            Unknown or failed usage retains its estimate. Duplicate settlement raises
            KeyError instead of charging or refunding a request twice.
        """
        with self.reservation_lock:
            estimate = self.input_reservations.pop(seq)
            if input_tokens is None:
                self.unknown_input_estimate += estimate
            else:
                self.reported_input += input_tokens
            self.save_input_allowance()

    def record_result(self, seq, role, result):
        """Persist the original result before validation can reject its contents.

        Args:
            seq: Cumulative call number reserved for this request.
            role: Requested application role.
            result: Neutral provider result, including possibly unknown usage.
        Returns:
            None; saves response, replaces its reservation with reported input usage,
            adds measured totals and appends an audit event.
        """
        storage.save(
            storage.job_dir(self.job_id) / f"call-{seq:03}-response.json",
            asdict(result),
        )
        self.settle_input(seq, result.input_tokens)
        with storage.LOCK:
            state = storage.state(self.job_id)
            storage.update(
                self.job_id,
                active_model_calls=[
                    c for c in state.get("active_model_calls", []) if c != seq
                ],
                input_tokens=state["input_tokens"] + (result.input_tokens or 0),
                output_tokens=state["output_tokens"] + (result.output_tokens or 0),
                unknown_usage_calls=state["unknown_usage_calls"]
                + int(result.input_tokens is None or result.output_tokens is None),
            )
        storage.event(
            self.job_id,
            "model_result",
            call=seq,
            role=role,
            model=result.model,
            stop_reason=result.stop_reason,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
        )

    def call(
        self,
        role: Literal["text", "vision"],
        prompt: str,
        schema: type[BaseModel] | None = None,
        images: Sequence[Image] = (),
        cap: int = 2048,
        correct: bool = True,
    ) -> BaseModel | str:
        """Deduplicate identical concurrent tasks without changing their meaning.

        Args:
            self: Shared run owner and its per-request locks.
            role: Text or vision provider role.
            prompt: Task text and optional private evidence bindings.
            schema: Internal response type; the bound schema is used for identity.
            images: Original image payloads, hashed in the request identity.
            cap: Maximum output tokens for this request.
            correct: Whether one bounded format correction remains available.
        Returns:
            Independent copy of a validated result. Identical requests in this work
            slice share one dispatch; failed calls are not cached as successful.
            Different bindings, models, images or instructions never share a result.
        """
        bound = source_response_schema(schema, prompt)
        if requires_source_binding(bound):
            raise ModelError(
                "Source-backed model replies require application-owned evidence bindings"
            )
        request = Request(
            prompt,
            SYSTEM,
            tuple(images),
            cap,
            bound.model_json_schema() if bound else None,
        )
        identity = request_record(role, request, self.service.identity(role))
        key = hashlib.sha256(
            json.dumps([identity, correct], sort_keys=True).encode()
        ).hexdigest()
        with self.reservation_lock:
            lock = self.request_locks.setdefault(key, RLock())
        with lock:
            if key in self.completed_requests:
                storage.event(
                    self.job_id, "model_reuse_in_run", role=role, provider_calls=0
                )
                return copy.deepcopy(self.completed_requests[key])
            result = self._send_call(role, prompt, bound, images, cap, correct)
            self.completed_requests[key] = copy.deepcopy(result)
            return result

    def _send_call(self, role, prompt, schema=None, images=(), cap=2048, correct=True):
        """Reuse a saved response or send a measured request with one bounded field correction.

        Args:
            role: Configured text or vision role; no fallback is allowed.
            prompt: Full task and supplied sources, retained privately for replay.
            schema: Internal response class. Bound evidence prompts expose local passage
                choices and attach original source records after wire-format validation.
            images: Neutral image payloads; hashes qualify replay compatibility.
            cap: Maximum output tokens; also part of the replay identity.
            correct: Allow one schema-correction request, charged to the same budget.
        Returns:
            Validated response instance or raw text. Failures propagate after safe
            receipts; failed network attempts count and their usage stays unknown.
        """
        schema = source_response_schema(schema, prompt)
        request = Request(
            prompt,
            SYSTEM,
            tuple(images),
            cap,
            schema.model_json_schema() if schema else None,
        )
        record = request_record(role, request, self.service.identity(role))
        saved = find_response(self.job_id, record) if self.replay else None
        if saved:
            return self.accept_response(
                role, prompt, schema, images, cap, saved["text"], correct
            )
        estimate = estimate_input(request)
        with self.reservation_lock:
            self.check_allowance(role, estimate)
            self.count += 1
            self.estimated_input += estimate
            with storage.LOCK:
                seq = storage.state(self.job_id)["calls"] + 1
                state = storage.state(self.job_id)
                storage.update(
                    self.job_id,
                    calls=seq,
                    active_model_calls=state.get("active_model_calls", []) + [seq],
                )
            self.input_reservations[seq] = estimate
            self.save_input_allowance()
            storage.save(
                storage.job_dir(self.job_id) / f"call-{seq:03}-request.json", record
            )
            storage.event(
                self.job_id,
                "model_start",
                call=seq,
                role=role,
                max_output_tokens=cap,
                estimated_input_tokens=estimate,
                prompt_characters=len(prompt),
                images=len(images),
            )
        try:
            result = self.service.generate(role, request)
        except Exception:
            self.settle_input(seq, None)
            with storage.LOCK:
                state = storage.state(self.job_id)
                storage.update(
                    self.job_id,
                    unknown_usage_calls=state["unknown_usage_calls"] + 1,
                    active_model_calls=[
                        c for c in state.get("active_model_calls", []) if c != seq
                    ],
                )
            storage.event(
                self.job_id, "model_error", call=seq, role=role, usage="unknown"
            )
            raise
        self.record_result(seq, role, result)
        if result.stop_reason in ("max_tokens", "length"):
            raise OutputLimitError(
                "Model reached its output allowance; incomplete response was saved but not accepted"
            )
        if result.stop_reason not in SUCCESS_STOPS:
            raise ModelError(
                f"Model stopped with {result.stop_reason}; response not accepted"
            )
        return self.accept_response(
            role, prompt, schema, images, cap, result.text, correct
        )

    def accept_response(self, role, prompt, schema, images, cap, text, correct):
        """Validate a reply or make at most one separately audited correction request.

        Args:
            role: Original configured model role; no fallback is introduced.
            prompt: Original instructions retained in receipts. Oversized procedure
                corrections omit unrelated history while preserving the reply and cited sources.
            schema: Expected response type, or None for an unstructured reply.
            images: Original image inputs, if any.
            cap: Original maximum output allowance.
            text: Original reply already preserved in its receipt.
            correct: Whether this is the original attempt, eligible for one correction.
        Returns:
            Validated response or raw text. A second invalid answer raises an actionable
            ModelError. Budget exhaustion pauses before correction and resumes through
            saved receipts. No local field rewriting or extra budget is permitted.
        """
        if schema is None:
            return text
        try:
            return parse_response(schema, text)
        except (ValidationError, ModelJSONError) as error:
            message = validation_message(error)
            storage.event(self.job_id, "response_validation_failed", message=message)
            if not correct:
                raise InvalidModelResponseError(
                    message + "; the single correction attempt also failed"
                ) from None
            storage.update(
                self.job_id,
                message="Checking generated output: requesting one correction to its source references or response format.",
            )
            correction = bounded_correction_prompt(
                prompt, text, error, schema.model_json_schema(), SYSTEM, images
            )
            if isinstance(prompt, EvidencePrompt):
                correction = prompt.continued(correction)
            return self.call(
                role,
                correction,
                schema,
                images,
                cap,
                correct=False,
            )
