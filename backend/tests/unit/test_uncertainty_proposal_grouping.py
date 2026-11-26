"""Check that combining similar uncertainty questions preserves every original
wording and any investigation already started. A smaller number of questions must
not mean silently losing a concern."""
from fixture_source_choices import local_evidence_reply, fixture_payload

import json
from workbench.agentic_workflow.execution import Run
from workbench.job_storage import job_files_and_audit_log as storage
from workbench.manual_analysis.group_related_uncertainty_proposals import group_related_uncertainty_proposals
from workbench.model_access.model_requests_and_responses import Capabilities, ModelService, Result


def test_grouping_retains_all_wordings_and_does_not_change_started_reviews():
    """Group equivalent wording while preserving a distinct question and old indices.

    Args:
        None; persistence is isolated and actual model transport is a fixture.
    Returns:
        None; verifies original membership, combined instructions, no replay charge,
        and refusal to regroup questions after evidence-review requests have started.
    """
    class GroupModel:
        """Return one explicit partition without judging whether a concern is resolved."""
        provider = 'fixture'
        model = 'grouping'
        capabilities = Capabilities(max_output_tokens=8000)
        calls = 0

        @local_evidence_reply
        def generate(self, request):
            """Return a partition of exactly the requested fixture indices.

            Args:
                request: Production grouping prompt, retained in ordinary call receipts.
            Returns:
                Two groups covering all three original proposals, without omissions.
            """
            self.calls += 1
            return Result(json.dumps({'groups':[[0,1],[2]]}),self.provider,self.model,'complete',100,20)

    model = GroupModel()
    job = storage.create('groups.pdf', b'fixture')['id']
    findings = [{'issue':issue,'evidence_ids':['source'],'severity':'review'} for issue in
                ['What is the drain hose height?', 'Which drain hose height is required?', 'What voltage is required?']]
    service = ModelService({'text':model})
    result = group_related_uncertainty_proposals(job,findings,Run(job,service=service))
    assert len(result) == 2
    assert all(f['issue'] in result[0]['issue'] for f in findings[:2])
    saved = json.loads((storage.job_dir(job)/'uncertainty-groups.json').read_text())
    assert saved['original_proposals'] == findings
    assert group_related_uncertainty_proposals(job,findings,Run(job,service=service,replay=True)) == result
    assert model.calls == 1
    older = storage.create('started.pdf', b'fixture')['id']
    storage.save(storage.job_dir(older)/'finding-review-progress.json', {'checks':{}})
    assert group_related_uncertainty_proposals(older,findings,Run(older,service=service)) == findings
    assert model.calls == 1
