"""Check that uncertain or action-like manual pictures are not approved as simple
reference illustrations. Prepared image assessments test the selection rules, not
the accuracy of an image model."""
import pytest
from workbench.result_illustrations.assess_static_illustration import VisualAssessment,decide


def assess(**changes):
    """Build an explicit static control for one-factor rejection tests.

    Args:
        changes: Observation fields to replace in the otherwise eligible control.
    Returns:
        Validated observations with the requested changes.
    """
    return VisualAssessment(**({'evidence':'Static overview','static_overview':'yes','depicts_action':'no','motion_arrows':'no','measurements_or_wiring':'no','recognizable_without_labels':'yes'}|changes))


@pytest.mark.parametrize('field',['static_overview','depicts_action','motion_arrows','measurements_or_wiring','recognizable_without_labels'])
def test_uncertain_observations_never_pass(field):
    """Reject each unknown visual property rather than treating it as absent.

    Args:
        field: Observation property whose answer is uncertain.
    Returns:
        None; asserts the image is excluded.
    """
    assert not decide(assess(**{field:'unclear'}),use='general_overview',source_role='overview',source_verified=True,precision_required=False)['eligible']


@pytest.mark.parametrize('override',[{'use':'instruction'},{'source_role':'action'},{'source_role':'unknown'},{'source_verified':False},{'precision_required':True}])
def test_code_gates_override_positive_model(override):
    """Prevent a positive model judgment from overriding use and provenance limits.

    Args:
        override: One invalid code-owned context field.
    Returns:
        None; asserts exclusion even with a positive visual assessment.
    """
    kwargs=dict(use='general_overview',source_role='overview',source_verified=True,precision_required=False)|override
    assert not decide(assess(),**kwargs)['eligible']


def test_static_control_and_missing_assessment():
    """Verify bounded useful acceptance and fail-closed missing model output.

    Args:
        None.
    Returns:
        None; checks general-overview-only approval and missing-reply rejection.
    """
    kwargs=dict(use='general_overview',source_role='overview',source_verified=True,precision_required=False)
    assert decide(assess(),**kwargs)['allowed_use']=='general_overview'
    assert not decide(None,**kwargs)['eligible']
