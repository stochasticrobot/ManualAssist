"""Store manual passages in a local search collection and find text relevant to
questions.

Each manual has its own searchable text and original page references. Searches
combine similarity matching with exact wording or identifiers so short model names
and error codes are not easily missed. This file retrieves evidence; it does not
write the AI's answer."""

import json
import re

from workbench.job_storage import job_files_and_audit_log as storage
from workbench.document_search.join_continuing_source_fragments import (
    prepare_source_chunks,
    source_groups,
)


def collection(job_id: str):
    """Open a job-isolated persistent Chroma collection using local embeddings.

    Args:
        job_id: Existing job identifier, used to prevent cross-document retrieval.
    Returns:
        Chroma collection; its ONNX MiniLM embedding model downloads on first use.
        No external paid embedding service is configured.
    """
    import chromadb
    from chromadb.config import Settings

    storage.job_dir(job_id)
    client = chromadb.PersistentClient(
        path=str(storage.DATA / "chroma"), settings=Settings(anonymized_telemetry=False)
    )
    return client.get_or_create_collection(
        "manual_" + job_id, metadata={"hnsw:space": "cosine"}
    )


def build(job_id: str, document: dict) -> list[dict]:
    """Index layout-supported passages without mixing document collections.

    Args:
        job_id: Parsed job identifier.
        document: Normalized layout items with source IDs, sections and pages.
    Returns:
        Chunk manifest; writes chunk JSON and vectors in batches with audit events.
        Supported fragments share windows and original source references. Long groups
        split into 1200-character windows with 150-character overlap. Obsolete
        vectors are removed only after all replacement writes succeed.
    """
    chunks = prepare_source_chunks(document)
    if not chunks:
        raise ValueError("No searchable text extracted")
    target = collection(job_id)
    for start in range(0, len(chunks), 64):
        batch = chunks[start : start + 64]
        storage.event(
            job_id, "tool_start", tool="write_vectors", start=start, count=len(batch)
        )
        target.upsert(
            ids=[c["id"] for c in batch],
            documents=[c["text"] for c in batch],
            metadatas=[
                {
                    k: json.dumps(v) if isinstance(v, list) else v
                    for k, v in c.items()
                    if k not in ("id", "text")
                }
                for c in batch
            ],
        )
        storage.event(
            job_id,
            "tool_result",
            tool="write_vectors",
            written=min(start + 64, len(chunks)),
            total=len(chunks),
            persisted_count=target.count(),
        )
    obsolete = sorted(set(target.get(include=[])["ids"]) - {c["id"] for c in chunks})
    if obsolete:
        target.delete(ids=obsolete)
    storage.save(storage.job_dir(job_id) / "chunks.json", chunks)
    return chunks


def retrieve(job_id: str, query: str) -> list[dict]:
    """Combine exact identifier hits and vector matches, then expand to source items.

    Args:
        job_id: Indexed job identifier.
        query: User question; never interpreted as code or a database expression.
    Returns:
        Up to eight source groups (at most 64 original items), identifiers first.
        Literal phrases of at least three words also take priority over similarity.
        Supported continuations accompany either fragment, including legacy indexes.
        Performs local embedding and read-only retrieval; logs retrieval evidence IDs.
    """
    doc = json.loads((storage.job_dir(job_id) / "document.json").read_text())
    identifiers = re.findall(r"\b[A-Za-z0-9]+(?:-[A-Za-z0-9]+)+\b", query)
    exact = [
        i["id"]
        for i in doc["items"]
        if any(k.lower() in i["text"].lower() for k in identifiers)
    ]
    phrases = [
        i["id"]
        for i in doc["items"]
        if len(query.split()) >= 3 and query.strip().casefold() in i["text"].casefold()
    ]
    target = collection(job_id)
    result = (
        target.query(query_texts=[query], n_results=min(12, target.count()))
        if target.count()
        else {"metadatas": [[]]}
    )
    ids = list(
        dict.fromkeys(
            exact + phrases + [m["evidence_id"] for m in result["metadatas"][0]]
        )
    )[:8]
    groups = {item["id"]: group for group in source_groups(doc) for item in group}
    ids = list(dict.fromkeys(item["id"] for hit in ids for item in groups.get(hit, [])))
    items = {i["id"]: i for i in doc["items"]}
    storage.event(
        job_id,
        "tool_result",
        tool="retrieve",
        query=query,
        evidence_ids=ids,
        exact_identifier_hits=len(exact),
        exact_phrase_hits=len(phrases),
    )
    return [items[i] for i in ids]
