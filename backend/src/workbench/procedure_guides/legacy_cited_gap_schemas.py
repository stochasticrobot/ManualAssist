"""Read older saved troubleshooting replies using the citation rules they originally
followed.

Earlier answers required citations even for steps that said information was
missing. Keeping their original required fields allows those completed answers to
be checked without rewriting history. New replies use the current rules; changed
manual text does not qualify for reuse of an old answer."""

from pydantic import Field, create_model
from workbench.data_models.analysis_and_question_models import (
    Citation,
    DiagnosticNode,
    TroubleshootingTree,
    TroubleshootingGeneration,
)


LegacyNode = create_model(
    "DiagnosticNode",
    __base__=DiagnosticNode,
    __doc__=DiagnosticNode.__doc__,
    citations=(list[Citation], Field(min_length=1)),
)
LegacyTree = create_model(
    "TroubleshootingTree",
    __base__=TroubleshootingTree,
    __doc__=TroubleshootingTree.__doc__,
    nodes=(list[LegacyNode], Field(min_length=1)),
)
LegacyTroubleshootingGeneration = create_model(
    "TroubleshootingGeneration",
    __base__=TroubleshootingGeneration,
    __doc__=TroubleshootingGeneration.__doc__,
    troubleshooting=(list[LegacyTree], ...),
)
