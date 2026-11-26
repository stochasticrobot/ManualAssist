"""Check that an AI request interrupted by a server restart remains counted exactly
once. Missing replies must leave usage unknown instead of inventing a successful
answer or zero cost."""

from workbench.agentic_workflow.mark_interrupted_model_requests import mark_interrupted_model_requests
from workbench.job_storage import job_files_and_audit_log as storage


def test_restart_counts_unmatched_attempt_once():
    """Record unknown usage once and preserve the interrupted request bytes.

    Args:
        None; storage is isolated by the automatic test fixture.
    Returns:
        None; verifies idempotent accounting, unchanged receipt and cleared activity.
    """
    job=storage.create('interrupted.pdf',b'fixture')['id']
    path=storage.job_dir(job)/'call-001-request.json'
    storage.save(path,{'prompt':'Saved request'})
    before=path.read_bytes()
    storage.update(job,calls=1,active_model_calls=[1])
    storage.event(job,'model_start',call=1,role='text')
    assert mark_interrupted_model_requests(job)==1
    assert mark_interrupted_model_requests(job)==0
    assert storage.state(job)['calls']==1
    assert storage.state(job)['unknown_usage_calls']==1
    assert storage.state(job)['active_model_calls']==[]
    assert path.read_bytes()==before
