"""Write the instructions used when asking AI to extract facts, find uncertainties or
make aids.

Each request explains one task and includes the relevant manual passages. Keeping
these instructions separate makes it possible to review what the model is being
asked to do without reading the code that sends the request. Building the text
here does not contact a provider."""

from workbench.manual_analysis.check_source_quotations import (
    anchored,
    source_map,
)
from workbench.model_access.code_owned_source_evidence import evidence_task

FACTS = (
    "Extract documented facts and procedures from this source, including installation, "
    "operation, troubleshooting, maintenance, validation, inspection, disassembly, "
    "reassembly, quality assurance, compliance and integrity verification where present. "
    "These examples do not restrict what can be extracted. Preserve units, conditions "
    "and the models each fact applies to. Give each fact a short name, its value, "
    "applicability and supporting passage selection. Do not split one instruction "
    "into redundant facts or infer that it applies to all models unless the source says "
    "so. Extract facts only; do not generate findings, FAQs or troubleshooting trees.\n"
)
UNCERTAINTIES = (
    "Identify specific ambiguities, contradictions or incomplete instructions in this "
    "source. Select supporting passages for every proposal. A category absent from these pages "
    "is not evidence of missing information: do not complain that a safety section "
    "lacks specifications, model numbers, error codes or quick-start instructions. "
    "Report a possible missing detail only when a particular source instruction "
    "requires it; the next step will check other parts of the manual. Empty findings "
    "are appropriate when nothing concrete is ambiguous.\n"
)
FAQ = (
    "Create useful questions and answers from these accepted facts and original "
    "source passages. Preserve applicability, conditions and safety warnings. Cite "
    "each answer by selecting its supporting passages. Do not invent information "
    "or restate the same answer several ways. Generate FAQ entries only; use an "
    "empty list if the source does not support a useful question.\n"
)
LEGACY_TREES = (
    "Create troubleshooting decision trees from these accepted facts and original "
    "passages, organized by the symptom or error described. Include applicable "
    "models, prerequisites and safety warnings. Cite every node and branch condition. "
    "Only create a branch when the manual supports that condition and next step. "
    "Use a stop node when the manufacturer says to stop use or contact service, "
    "and an unresolved node when it does not provide the next step. Never invent "
    "a repair or a yes/no branch. Generate trees only, or an empty list when no "
    "troubleshooting procedure is supported.\n"
)


TREES = LEGACY_TREES.replace(
    "Cite every node and branch condition.",
    "Select supporting passages for every check, action, stop instruction and branch condition. "
    "An unresolved node marks an evidence gap, not an instruction, and may have an empty citations list. "
    "It must have no branches. Describe the specific unanswered question or say 'No next step established "
    "from the passages examined'; do not claim that the entire manual lacks information. "
    "Never invent an uncited branch merely to connect to an unresolved node.",
)


CHECKS = (
    "Extract independent troubleshooting checks or remedies from the supplied original passages. "
    "For each, retain the symptom, applicability, conditions, warnings and instruction, with supporting passage selections. "
    "Keep separate checks separate. Do not invent an order, an otherwise branch, a negative condition, "
    "or a remedy for an outcome the source does not discuss. A list of possible causes is not a decision tree. "
    "Preserve a documented condition and its action together in one instruction. "
    "Do not claim completeness from this source group. Return troubleshooting_checks only; "
    "an empty list is appropriate when no troubleshooting instruction is supported.\n"
)


def facts_prompt(batch):
    """Ask only for facts, keeping instructions separate from the source evidence.

    Args:
        batch: Small group of original source items or text windows.
    Returns:
        Task A prompt with original text and local passage choices; page/ID
        bindings remain private to application code.
    """
    return evidence_task(FACTS, {}, batch)


def uncertainty_prompt(batch):
    """Ask for concrete uncertainties without treating a local omission as a defect.

    Args:
        batch: Original passages to inspect for ambiguous instructions.
    Returns:
        Task B discovery prompt; document-wide checking happens in a separate step.
    """
    return evidence_task(UNCERTAINTIES, {}, batch)


def aids_prompt(instructions, batch, facts):
    """Give one decision-aid task the original passages and matching accepted facts.

    Args:
        instructions: Either FAQ or troubleshooting instructions, never both.
        batch: Original evidence for this request.
        facts: Accepted facts from Task A; only matching quoted passages are included.
    Returns:
        Prompt with matching facts and evidence. It does not treat the extracted facts
        as a replacement for the manual or include unreviewed image descriptions.
    """
    sources = source_map(batch)
    matching = [f for f in facts if anchored(f["evidence_id"], f["quote"], sources)]
    return evidence_task(instructions, {"accepted_facts": matching}, batch)
