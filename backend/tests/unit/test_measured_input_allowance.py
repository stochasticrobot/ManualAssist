"""Check that AI-work limits use reported input usage after a request finishes and
estimates while it is still running. Controlled replies cover missing usage,
failures and reused answers without provider charges."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace

import pytest
from workbench.agentic_workflow import send_and_record_model_requests as calls
from workbench.job_storage import job_files_and_audit_log as storage
from workbench.model_access.model_requests_and_responses import Result


def make_run(monkeypatch, usage):
    """Create an isolated production Run with predictable provider responses.

    Args:
        monkeypatch: Replaces input estimation and the slice ceiling for this test.
        usage: Sequence of measured input values, None values, or exceptions.
    Returns:
        Run that dispatches through the normal accounting and receipt path, offline.
    """
    monkeypatch.setattr(calls, 'estimate_input', lambda request: 10)
    monkeypatch.setattr(calls, 'MAX_INPUT_TOKENS', 20)
    values = iter(usage)

    def generate(role, request):
        """Return one controlled provider outcome without making network calls.

        Args:
            role: Application role, unused by this fixture.
            request: Production request retained by the normal receipt path.
        Returns:
            Neutral result with controlled input usage, or raises the supplied error.
        """
        value = next(values)
        if isinstance(value, Exception):
            raise value
        return Result('ok', 'fixture', 'fixture', 'complete', value, 1)

    job = storage.create('budget.pdf', b'fixture')['id']
    return calls.Run(job, service=SimpleNamespace(
        identity=lambda role: {'provider': 'fixture', 'model': 'fixture'},
        generate=generate,
    ))


def test_reported_usage_replaces_estimates_and_replay_is_free(monkeypatch):
    """Refund conservative reservations and do not charge compatible saved replies.

    Args:
        monkeypatch: Installs the isolated allowance and provider fixture.
    Returns:
        None; three estimated-ten requests fit using actual usage of three each,
        and a resumed replay neither charges nor modifies cumulative usage.
    """
    run = make_run(monkeypatch, [3, 3, 3])
    for prompt in ['a', 'b', 'c']:
        run.call('text', prompt)
    assert run.reported_input == 9
    assert run.input_reservations == {}
    assert storage.state(run.job_id)['input_tokens'] == 9
    resumed = calls.Run(run.job_id, service=run.service, replay=True)
    assert resumed.call('text', 'a') == 'ok'
    assert resumed.count == resumed.reported_input == 0
    assert storage.state(run.job_id)['input_tokens'] == 9


@pytest.mark.parametrize('usage,reported,fallback', [(None, 0, 10), (0, 0, 0), (25, 25, 0)])
def test_unknown_zero_and_underestimated_usage(monkeypatch, usage, reported, fallback):
    """Keep unknown estimates, accept reported zero and stop after actual overshoot.

    Args:
        monkeypatch: Installs an isolated provider and allowance.
        usage: Provider input usage for the completed request.
        reported: Expected measured input charge.
        fallback: Expected retained estimate for unknown input usage.
    Returns:
        None; accurate accounting survives all three provider outcomes.
    """
    run = make_run(monkeypatch, [usage])
    run.call('text', 'a')
    assert run.reported_input == reported
    assert run.unknown_input_estimate == fallback
    assert run.input_reservations == {}
    if usage == 25:
        with pytest.raises(calls.BudgetPause):
            run.call('text', 'b')
        assert run.count == 1


def test_failure_retains_unknown_charge(monkeypatch):
    """A transport failure must not refund potentially consumed provider input.

    Args:
        monkeypatch: Installs a failing isolated provider.
    Returns:
        None; failure consumes one attempt and an unknown-usage estimate.
    """
    run = make_run(monkeypatch, [RuntimeError('offline failure')])
    with pytest.raises(RuntimeError):
        run.call('text', 'a')
    assert run.unknown_input_estimate == 10
    assert run.input_reservations == {}
    assert run.count == 1


def test_inflight_reservation_blocks_then_releases_capacity(monkeypatch):
    """Prevent concurrent overspending while returning capacity after measurement.

    Args:
        monkeypatch: Installs the isolated allowance and provider.
    Returns:
        None; pending input is visible and blocks excess dispatch until settled.
    """
    run = make_run(monkeypatch, [2, 2])
    entered, release = Event(), Event()
    original = run.service.generate

    def blocked(role, request):
        """Hold one provider reply while another request checks the budget.

        Args:
            role: Requested role forwarded unchanged.
            request: Production request forwarded unchanged.
        Returns:
            Fixture result after release; fails after a bounded wait on deadlock.
        """
        entered.set()
        assert release.wait(3)
        return original(role, request)

    run.service.generate = blocked
    run.reported_input = 5
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(run.call, 'text', 'a')
        try:
            assert entered.wait(3)
            assert storage.state(run.job_id)['input_allowance']['reserved'] == 10
            with pytest.raises(calls.BudgetPause):
                run.call('text', 'b')
        finally:
            release.set()
        assert future.result() == 'ok'
    run.call('text', 'b')
    assert run.reported_input == 9
    assert run.count == 2
