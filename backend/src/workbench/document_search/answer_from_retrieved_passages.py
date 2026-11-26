"""Answer a reader's question using relevant passages found in the saved manual.

The application searches locally, gives the matching passages to the AI, and keeps
only answers with valid source quotations. It also offers links to related saved
guides. If the retrieved text is insufficient, the answer says so; this is not a
fresh investigation of the entire manual."""

import json

from workbench.agentic_workflow.execution import Run
from workbench.data_models.analysis_and_question_models import Answer
from workbench.document_search import index as knowledge
from workbench.document_search.find_related_result_guides import (
    find_related_result_guides,
)
from workbench.job_storage import job_files_and_audit_log as storage
from workbench.manual_analysis.check_source_quotations import anchored
from workbench.model_access.code_owned_source_evidence import evidence_task


def answer(job_id: str, question: str) -> dict:
    """Retrieve local evidence and generate one bounded, source-anchored answer.

    Args:
        job_id: Indexed job identifier.
        question: User question; treated as a request, never executable tool code.
    Returns:
        Accepted cited claims, related guide links and explicit insufficiency; rejects unmatched quotes.
        Makes at most one paid text call and records retrieval/model receipts.
    """
    items = knowledge.retrieve(job_id, question)
    run = Run(job_id, limit=1)
    response = run.call(
        "text",
        evidence_task(
            "Answer using only the supplied passages. Select supporting passages for each statement. "
            "If the requested information is absent, return no claims and insufficient=true. Do not substitute another model or error code.",
            {"question": question},
            items,
        ),
        Answer,
        cap=1600,
    )
    sources = {i["id"]: i for i in items}
    accepted = [
        {**c.model_dump(), "page": sources[c.evidence_id]["page"]}
        for c in response.claims
        if anchored(c.evidence_id, c.quote, sources)
    ]
    profile_path = storage.job_dir(job_id) / "profile.json"
    profile = json.loads(profile_path.read_text()) if profile_path.exists() else {}
    result = {
        "related_guides": find_related_result_guides(profile, question),
        "claims": accepted,
        "insufficient": response.insufficient
        or len(accepted) != len(response.claims)
        or not accepted,
        "validation": "Source-quote anchors checked; semantic interpretation remains machine-generated.",
    }
    storage.event(job_id, "answer", question=question, result=result)
    return result
