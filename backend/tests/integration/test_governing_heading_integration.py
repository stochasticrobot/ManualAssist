"""Check that section headings needed to understand a manual passage reach guide
review with their original references. Controlled replies also test rejection of
altered evidence and reuse of unchanged saved work."""
import copy
import json
import pytest
from workbench.procedure_guides.retain_governing_heading_sources import bind_heading_sources, retain_heading_sources
from workbench.procedure_guides.prepare_batched_guide_review import prepare_comparisons
from workbench.procedure_guides.review_actions_with_code_owned_evidence import compare_source_and_guide_behavior, text_units
from workbench.agentic_workflow.send_and_record_model_requests import Run
from workbench.model_access.model_requests_and_responses import Capabilities, ModelService, Result
from workbench.job_storage import job_files_and_audit_log as storage


def document_case():
    """Provide repeated heading labels with distinct original identities.

    Args:
        None.
    Returns:
        Full document, selected body source and guide missing its prerequisite.
    """
    items=[
        {'id':'h1','text':'Disconnect power before opening the cover.','label':'section_header','section':['Disconnect power before opening the cover.'],'page':1},
        {'id':'b1','text':'Open the cover.','label':'text','section':['Disconnect power before opening the cover.'],'page':1},
        {'id':'h2','text':'Disconnect power before opening the cover.','label':'section_header','section':['Disconnect power before opening the cover.'],'page':2},
        {'id':'b2','text':'Open the cover.','label':'text','section':['Disconnect power before opening the cover.'],'page':2}]
    guide={'steps':[{'id':'open','instruction':'Open the cover.','citations':[{'evidence_id':'b2','quote':'Open the cover.'}]}]}
    return {'items':items},[items[-1]],guide


class HeadingReviewModel:
    """Deterministic wire control; semantic quality is tested separately live."""
    provider='fixture'
    model='heading-integration'
    capabilities=Capabilities(max_output_tokens=8000)

    def __init__(self):
        """Initialize dispatch observations.

        Args:
            None.
        Returns:
            None; stores actual provider-bound requests.
        """
        self.requests=[]

    def generate(self, request):
        """Reject the explicit missing heading and accept the existing body action.

        Args:
            request: Actual production wire request.
        Returns:
            Fixture review judgments with measured dummy usage and strict labels.
        """
        self.requests.append(request)
        assert {s['id'] for s in request.prompt.sources}=={'h2','b2'}
        task=json.loads(request.prompt.split('\n')[-1])['task']
        rows=[]
        for c in task['comparisons']:
            result='established' if c['kind']=='support' else 'absent' if c['statement_to_check'].startswith('Disconnect') else 'present'
            rows.append({'comparison':c['comparison'],'explanation':'Fixture: missing prerequisite.' if result=='absent' else 'Fixture: supported body.','result':result})
        return Result(json.dumps({'judgments':rows}),self.provider,self.model,'end_turn',10,10)


def test_original_heading_identity_reaches_review_and_replay():
    """Verify sparse retrieval resolves the correct repeated heading without mutation.

    Args:
        None; storage and providers are isolated by test fixtures.
    Returns:
        None; one explicit heading check, proper correction ID and exact saved
        response reuse through the production reviewer entry point.
    """
    document,sources,guide=document_case();before=copy.deepcopy(document)
    job=storage.create('heading.pdf',b'fixture')['id'];model=HeadingReviewModel();service=ModelService({'text':model})
    review,audit=compare_source_and_guide_behavior(guide,sources,Run(job,service=service),document=document)
    assert not review.acceptable
    assert review.corrections[0].evidence_ids==['h2']
    assert len([s for s in audit[0]['scope'] if s['mode']=='explicit_governing_heading'])==1
    again,_=compare_source_and_guide_behavior(guide,sources,Run(job,service=service,replay=True),document=document)
    assert again==review and len(model.requests)==2 and document==before
    resolved=retain_heading_sources(sources,document)
    comparisons,_,_=prepare_comparisons(guide,resolved,text_units)
    assert all('h2' in c['_source_ids'] for c in comparisons)
    assert comparisons[0]['_source_ids'][0]=='b2'


def test_invalid_ancestry_and_source_mutation_fail_closed():
    """Reject false heading ancestry or modified source windows before dispatch.

    Args:
        None.
    Returns:
        None; neither bad source history can be used for review evidence.
    """
    document,sources,_=document_case()
    document['items'][-1]['section']=['Wrong heading']
    with pytest.raises(ValueError,match='ancestry'):
        bind_heading_sources(document['items'])
    document,sources,_=document_case();sources=copy.deepcopy(sources);sources[0]['text']='Invented action.'
    with pytest.raises(ValueError,match='original text'):
        retain_heading_sources(sources,document)


def test_directly_cited_heading_is_reviewed_without_body_passage():
    """Do not discard a directive merely because it was parsed as a heading.

    Args:
        None.
    Returns:
        None; an explicitly cited standalone directive has one coverage comparison
        and a separate support comparison, without an invented missing-body defect.
    """
    source={'id':'h','label':'section_header','text':'Disconnect power.','page':1,'section':['Disconnect power.']}
    guide={'steps':[{'id':'off','instruction':'Disconnect power.','citations':[{'evidence_id':'h','quote':'Disconnect power.'}]}]}
    sources=retain_heading_sources([source],{'items':[source]})
    comparisons,scope,problems=prepare_comparisons(guide,sources,text_units)
    assert not problems
    assert len([c for c in comparisons if c['kind']=='coverage'])==1
    assert comparisons[0]['_source_ids']==['h']
