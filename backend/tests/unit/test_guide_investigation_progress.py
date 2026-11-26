"""Check that guide progress counts real completed reviews rather than proposed
finishes or saved but unchecked drafts. Prepared records also cover missing
totals, stopped work and older saved results."""

from workbench.job_storage import job_files_and_audit_log as storage
from workbench.procedure_guides.summarize_guide_investigations import summarize_guide_investigations


def test_independent_categories_and_evidence_finish_counts():
    """Report one finished category while another proposes finish and a third fails.

    Args:
        None; the autouse fixture isolates all persistence.
    Returns:
        None; verifies denominators, evidence-bound facts, proposed versus actual finish,
        and that a failure remains incomplete even if it retained a reviewed draft.
    """
    job = storage.create('progress.pdf', b'fixture')['id']
    path = storage.job_dir(job)
    (path/'procedure-plans-v3').mkdir()
    candidates = [dict(id=i, title=i, kind=k) for i,k in [('install','installation'),('fault','troubleshooting'),('clean','maintenance')]]
    storage.save(path/'procedure-candidates-v2.json', dict(candidates=candidates))
    base = dict(state=dict(status='analyzing'), profile=dict(facts=[dict(evidence_id='install-source'),dict(evidence_id='fault-source')]), audit=[dict(kind='procedure_decision',procedure_id='fault',action='finish',reason='Draft prepared')])
    storage.save(path/'procedure-plans-v3/install.json', dict(evidence={'install-source':{}}, result=dict(status='needs_review', completion='finished_with_gaps', model_reviewed=True)))
    storage.save(path/'procedure-plans-v3/fault.json', dict(evidence={'fault-source':{}}, questions=[dict(question='Cause?',status='partial',answer='Known checks',evidence_ids=['fault-source'])]))
    storage.save(path/'procedure-failure-clean.json', dict(result=dict(status='needs_review', generation_failed=True, model_reviewed=True)))
    groups = {g['kind']:g for g in summarize_guide_investigations(path,base)}
    assert groups['installation']['status']=='finished_with_gaps'
    assert groups['installation']['finished']==groups['installation']['total']==1
    assert groups['installation']['fact_indexes']==[0]
    assert groups['troubleshooting']['finished']==0
    assert groups['troubleshooting']['tasks'][0]['status']=='checking_finish'
    assert groups['troubleshooting']['tasks'][0]['finish_proposed']
    assert groups['troubleshooting']['fact_indexes']==[1]
    assert groups['maintenance']['finished']==0
    assert groups['maintenance']['tasks'][0]['status']=='failed'
    assert groups['maintenance']['status']=='incomplete'


def test_unknown_totals_exhaustion_and_legacy_results_are_not_false_finishes():
    """Avoid completing undiscovered work or promoting an exhausted saved draft.

    Args:
        None; creates isolated optional progress snapshots.
    Returns:
        None; unknown totals stay unknown and historical needs-review guides stay unconfirmed.
    """
    job=storage.create('unknown.pdf',b'fixture')['id'];path=storage.job_dir(job)
    (path/'procedure-plans-v3').mkdir()
    detail=dict(state=dict(status='paused'),profile={},audit=[])
    assert all(g['total'] is None and not g['finished'] for g in summarize_guide_investigations(path,detail))
    storage.save(path/'procedure-candidates-v2.json',dict(candidates=[dict(id='a',kind='installation',title='Install'),dict(id='b',kind='maintenance',title='Clean')]))
    storage.save(path/'procedure-plans-v3/a.json',dict(result=dict(status='needs_review',completion='allowance_exhausted',model_reviewed=True)))
    storage.save(path/'procedure-plans-v3/b.json',dict(result=dict(status='needs_review',model_reviewed=True)))
    groups={g['kind']:g for g in summarize_guide_investigations(path,detail)}
    assert groups['installation']['status']=='incomplete'
    assert groups['maintenance']['tasks'][0]['status']=='saved_needs_review'
    assert groups['troubleshooting']['status']=='no_tasks'
    assert all(not g['finished'] for g in groups.values())
