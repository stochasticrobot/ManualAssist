"""Check that suitable original PDF pictures can be prepared, saved and served to the
browser. Temporary files and simulated image assessments test placement and reuse
without altering real jobs or contacting a model."""
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient
from workbench.job_storage import job_files_and_audit_log as storage
from workbench.result_illustrations import prepare_source_illustrations as images
from workbench.result_illustrations.assess_static_illustration import VisualAssessment
from workbench.http_endpoints.reference_illustration_routes import router
from fastapi import FastAPI


def record(sid,label,box,text='',page=1):
    """Make a geometry-bearing source record for column-isolation tests.

    Args:
        sid: Unique ID; label: parser item kind; box: left/bottom/right/top tuple.
        text: Original text; page: physical page number.
    Returns:
        Source dictionary with BOTTOMLEFT provenance.
    """
    return dict(id=sid,label=label,text=text,page=page,provenance=[{'bbox':dict(zip(['l','b','r','t'],box))|{'coord_origin':'BOTTOMLEFT'}}])


def document():
    """Provide adjacent overview columns and a precision-dependent source section.

    Args:
        None.
    Returns:
        Parsed fixture whose incorrect section strings must not drive placement.
    """
    return {'items':[record('h1','section_header',(10,180,100,190),'Front View'),record('f1','picture',(10,110,100,170)),record('t1','text',(10,90,100,100),'Front cover'),record('h2','section_header',(200,180,290,190),'Interior View'),record('f2','picture',(200,110,290,170)),record('t2','text',(200,90,290,100),'Rack'),record('h3','section_header',(10,60,100,70),'Rotate screw'),record('f3','picture',(10,10,100,50))]}


def test_placement_uses_column_geometry_not_page_or_section_strings():
    """Reject wrong-column and action-region associations through the real selector.

    Args:
        None.
    Returns:
        None; asserts exact region ownership rather than matching a whole page.
    """
    result=images.source_candidates(document())
    assert [r['id'] for r in result]==['f1','f2']
    assert result[0]['source_ids']==['f1','h1','t1']
    assert result[1]['source_ids']==['f2','h2','t2']


def test_prepare_cache_exclusions_and_http_delivery(tmp_path,monkeypatch):
    """Exercise production preparation, source mapping, cache and served asset checks.

    Args:
        tmp_path: Isolated job root; monkeypatch: scoped storage and crop substitution.
    Returns:
        None; asserts no repeated calls, excluded/tampered images cannot be served,
        and changed source data hides stale assets. Never starts production lifespan.
    """
    monkeypatch.setattr(storage,'JOBS',tmp_path)
    job=storage.create('fixture.pdf',b'%PDF-fixture');jid=job['id'];path=storage.job_dir(jid);doc=document();storage.save(path/'document.json',doc)
    monkeypatch.setattr(images,'crop_figure',lambda p,c:b'PNG-'+c['id'].encode())
    calls=[]
    class Run:
        service=SimpleNamespace(identity=lambda role:{'provider':'fixture','model':'vision-test'})
        def call(self,role,prompt,schema,images,cap,correct):
            """Return controlled visual observations through the normal preparation boundary.

            Args:
                role: Configured application model role.
                prompt: Visual observation task.
                schema: Response validator.
                images: Original crop bytes.
                cap: Output token bound.
                correct: Whether correction is enabled.
            Returns:
                Static approval for f1 and a motion exclusion for f2; records calls.
            """
            calls.append(role)
            return VisualAssessment(evidence='fixture',static_overview='yes',depicts_action='no',motion_arrows='yes' if images[0].data.endswith(b'f2') else 'no',measurements_or_wiring='no',recognizable_without_labels='yes')
    first=images.prepare(jid,doc,Run());assert len(calls)==2 and set(calls)=={'image_captioning'}
    images.prepare(jid,doc,Run());assert len(calls)==2
    manifest=images.public_manifest(jid,doc);assert [r['id'] for r in manifest['images']]==['f1']
    app=FastAPI();app.include_router(router)
    with TestClient(app) as client:
        assert client.get(f'/api/jobs/{jid}/illustrations/f1.png').content==b'PNG-f1'
        assert client.get(f'/api/jobs/{jid}/illustrations/f2.png').status_code==404
        (path/'illustrations/f1.png').write_bytes(b'tampered')
        assert client.get(f'/api/jobs/{jid}/illustrations/f1.png').status_code==404
    assert not images.public_manifest(jid,{'items':[]})['images']
