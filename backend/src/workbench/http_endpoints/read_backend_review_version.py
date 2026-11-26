"""Report which guide-review code the running server actually loaded.

Editing files on disk does not update code already running in memory. This read-
only diagnostic records version information and source fingerprints at startup so
a developer can distinguish an active release from a pending edit. It does not
expose credentials, read manual content or start model work."""

import copy
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter

from workbench.model_access import code_owned_source_evidence as evidence
from workbench.procedure_guides import (
    compare_source_and_guide_behavior as reader_fields,
)
from workbench.procedure_guides import check_stalled_review_objections as objections
from workbench.procedure_guides import planner as planner
from workbench.procedure_guides import prepare_batched_guide_review as preparation
from workbench.procedure_guides import retain_governing_heading_sources as headings
from workbench.procedure_guides import (
    review_actions_with_code_owned_evidence as source_units,
)
from workbench.procedure_guides import (
    reviewer as reviewer,
)

router = APIRouter()


def capture_review_runtime():
    """Record loaded reviewer behavior and source hashes at process initialization.

    Args:
        None; uses already imported modules, never model credentials or saved jobs.
    Returns:
        Snapshot with process identity, reviewer version, prompt/schema hashes and
        file hashes captured now. File hashes attest startup disk content, not a
        future disk read; matching them alone does not prove model judgment quality.
    """
    configuration = reviewer.review_configuration()
    schemas = configuration["schemas"]
    instructions = json.dumps(configuration["instructions"], sort_keys=True)
    return {
        "pid": os.getpid(),
        "loaded_at": datetime.now(UTC).isoformat(),
        "reviewer_version": reviewer.VERSION,
        "scope_verdict_available": "out_of_scope" in json.dumps(schemas["relevance"]),
        "coverage_scope_verdict_available": "out_of_scope"
        in json.dumps(schemas["coverage"]),
        "planner_uses_loaded_reviewer": planner.compare_source_and_guide_behavior
        is reviewer.compare_source_and_guide_behavior,
        "review_jobs": list(configuration["instructions"]),
        "review_configuration_sha256": hashlib.sha256(
            json.dumps(configuration, sort_keys=True).encode()
        ).hexdigest(),
        "instructions_sha256": hashlib.sha256(instructions.encode()).hexdigest(),
        "scope_schema_sha256": hashlib.sha256(
            json.dumps(schemas, sort_keys=True).encode()
        ).hexdigest(),
        "startup_source_sha256": {
            module.__name__: hashlib.sha256(
                Path(module.__file__).read_bytes()
            ).hexdigest()
            for module in (
                reviewer,
                objections,
                preparation,
                planner,
                evidence,
                headings,
                reader_fields,
                source_units,
            )
        },
    }


LOADED_REVIEW_RUNTIME = capture_review_runtime()


@router.get("/api/runtime")
def review_runtime():
    """Return the immutable review-version snapshot for this serving process.

    Args:
        None; this read-only route has no request body or query parameters.
    Returns:
        Independent snapshot copy. Starts no analysis/model calls and does not
        reread changed source files or mutate saved application state.
    """
    return copy.deepcopy(LOADED_REVIEW_RUNTIME)
