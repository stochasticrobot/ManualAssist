"""Decide whether a manual image is suitable as a general reference illustration.

An overview picture can help readers recognize parts, while arrows or action
sequences can imply instructions that have not been checked. These rules evaluate
the image assessment and reject uncertain or unsuitable pictures. An included
illustration is not proof of a procedure or a safety judgment."""
from typing import Literal
from pydantic import BaseModel, ConfigDict


class VisualAssessment(BaseModel):
    """Record coarse visible characteristics, without interpreting fine directions."""
    model_config = ConfigDict(extra='forbid', strict=True)
    evidence: str
    static_overview: Literal['yes', 'no', 'unclear']
    depicts_action: Literal['yes', 'no', 'unclear']
    motion_arrows: Literal['yes', 'no', 'unclear']
    measurements_or_wiring: Literal['yes', 'no', 'unclear']
    recognizable_without_labels: Literal['yes', 'no', 'unclear']


PROMPT = '''Assess whether this illustration can serve ONLY as a broad static visual overview, without explaining any action or identifying a numbered part. Describe visible evidence first. Do not identify rotation direction or read tiny text. Report whether it is a static overview, depicts an action (including a hand manipulating a part), contains motion arrows, contains measurements or wiring information, and is recognizable at a broad level without reading labels. Ordinary leader lines connecting labels to stationary parts are not motion arrows. Use unclear when you cannot establish an answer. Do not call an image safe; report only these observations. Return one JSON answer object with these six top-level fields: evidence, static_overview, depicts_action, motion_arrows, measurements_or_wiring, recognizable_without_labels. The supplied schema describes your answer; do not return the schema itself or a properties wrapper.'''


def decide(assessment, *, use, source_role, source_verified, precision_required):
    """Admit only bounded static-overview use with verified original-source assets.

    Args:
        assessment: Validated visual observations, or None after an invalid reply.
        use: Requested presentation use; only general_overview is eligible.
        source_role: Code-owned context classification; only overview is eligible.
        source_verified: Whether original image bytes and source mapping were checked.
        precision_required: Whether intended use needs labels, direction or other detail.
    Returns:
        Eligibility and rejection reasons. Missing, uncertain or unsupported evidence
        excludes the image. Eligibility never authorizes it as an instruction or
        verifies component identity. No model calls or file changes occur here.
    """
    reasons = []
    if use != 'general_overview': reasons.append('Only broad overview use is supported')
    if source_role != 'overview': reasons.append('Source context is not a confirmed overview')
    if not source_verified: reasons.append('Original source mapping is unverified')
    if precision_required: reasons.append('Intended use requires fine detail')
    if assessment is None:
        reasons.append('No valid visual assessment')
    else:
        required = {'static_overview':'yes','depicts_action':'no','motion_arrows':'no','measurements_or_wiring':'no','recognizable_without_labels':'yes'}
        reasons.extend('Visual check failed or uncertain: '+key for key,value in required.items() if getattr(assessment,key)!=value)
    return {'eligible':not reasons,'reasons':reasons,'allowed_use':'general_overview' if not reasons else None}
