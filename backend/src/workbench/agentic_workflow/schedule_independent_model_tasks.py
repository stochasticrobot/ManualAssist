"""Run independent pieces of analysis at the same time without starting them all at
once.

A new task starts only when a working slot becomes free, and each outcome is
handed back for saving. A failure can prevent further tasks from starting while
requests already sent are allowed to finish. Stopping local work cannot cancel
charges for requests a model provider has already received."""

from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait


def completed_tasks(tasks, execute, workers, can_start=None, recoverable_error=None):
    """Refill free worker slots while yielding every completed task to its coordinator.

    Args:
        tasks: Iterable of independent work items, or a zero-argument supplier
            returning one currently available item or None. A supplier is rechecked
            after completions so output-limited tasks can add smaller children.
        execute: Callable receiving one item; must not edit shared stage plans.
        workers: Maximum simultaneously submitted tasks.
        can_start: Optional zero-argument check that closes further admission after
            the caller records a failure; already-started work still drains.
        recoverable_error: Optional exception class whose failures can be handled by
            the caller without closing admission, such as a split-worthy long reply.
    Returns:
        Iterator of (item, result, error) in completion order. A whole completed set
        is examined for failures before refilling, preventing successes from hiding
        a simultaneous failure. Exceptions are returned for persistence and must be
        raised by the caller after draining. No more than workers tasks are queued.
    """
    supplier = tasks if callable(tasks) else None
    iterator = None if supplier else iter(tasks)
    stopped = False
    exhausted = False
    with ThreadPoolExecutor(max_workers=workers) as pool:
        pending = {}
        while True:
            while not stopped and not exhausted and len(pending) < workers:
                if can_start is not None and not can_start():
                    stopped = True
                    break
                try:
                    item = supplier() if supplier else next(iterator)
                    if supplier and item is None:
                        break
                except StopIteration:
                    exhausted = True
                    break
                pending[pool.submit(execute, item)] = item
            if not pending:
                break
            finished, _ = wait(pending, return_when=FIRST_COMPLETED)
            outcomes = []
            for future in finished:
                item = pending.pop(future)
                try:
                    result = future.result()
                except Exception as error:  # noqa: BLE001 - caller receives and re-raises it
                    outcomes.append((item, None, error))
                    if recoverable_error is None or not isinstance(
                        error, recoverable_error
                    ):
                        stopped = True
                else:
                    outcomes.append((item, result, None))
            yield from outcomes
