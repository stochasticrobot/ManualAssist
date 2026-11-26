"""Rebuild the fictional manual example without credentials or external model calls.

The real HTTP analysis workflow runs against controlled model replies from the
public test helpers. Only the original example manual and final profile are saved;
private jobs, request receipts and runtime settings are never read or copied.
"""

import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [
    str(ROOT / "backend" / "src"),
    str(ROOT / "backend" / "tests"),
    str(ROOT / "backend" / "tests" / "integration"),
]

from fastapi.testclient import TestClient
from pytest import MonkeyPatch
from PIL import Image, ImageDraw
from test_agentic_procedure_guides import ProcedureModel, manual
from test_large_manual_completion_and_resume import InlineWorker
from workbench.agentic_workflow import execution
from workbench.document_search import index
from workbench.http_endpoints import background_worker_and_question_lock as runtime
from workbench.http_endpoints.serve_application import app
from workbench.job_storage import job_files_and_audit_log as storage
from workbench.model_access.model_requests_and_responses import ModelService


def build_demo() -> None:
    """Generate inspectable example outputs with isolated storage and a simulated model.

    Args:
        None; uses the original fictional manual from the bundled test helpers.
    Returns:
        None. Overwrites only examples/demo/manual.md, document.json, manual.pdf and
        results.json. The PDF is rendered from the same authored passages; the demo
        starts with parsed text and does not exercise PDF extraction or embeddings.
        Raises if the actual analysis route does not finish within its allowed slice.
    """
    destination = ROOT / "examples" / "demo"
    destination.mkdir(exist_ok=True)
    document = manual()
    pages = []
    markdown = [
        "# Fictional demonstration appliance",
        "",
        "Original software example, not instructions for any real product.",
        "",
    ]
    for page in range(1, document["pages"] + 1):
        passages = [item["text"] for item in document["items"] if item["page"] == page]
        markdown.extend([f"## Page {page}", "", *passages, ""])
        image = Image.new("RGB", (1240, 1754), "white")
        draw = ImageDraw.Draw(image)
        draw.text(
            (70, 70),
            f"Fictional demonstration appliance - page {page}",
            fill="black",
            font_size=30,
        )
        draw.text(
            (70, 130),
            "Software example only. Not a real product manual.",
            fill="black",
            font_size=24,
        )
        for row, passage in enumerate(passages):
            draw.text((70, 220 + row * 80), passage, fill="black", font_size=24)
        pages.append(image)
    pages[0].save(
        destination / "manual.pdf",
        save_all=True,
        append_images=pages[1:],
        resolution=150,
    )
    (destination / "manual.md").write_text("\n".join(markdown))
    (destination / "document.json").write_text(json.dumps(document, indent=2) + "\n")
    with (
        TemporaryDirectory(prefix="manualassist-demo-") as temporary,
        MonkeyPatch.context() as patch,
    ):
        patch.setattr(storage, "DATA", Path(temporary))
        patch.setattr(storage, "JOBS", Path(temporary) / "jobs")
        model = ProcedureModel()
        patch.setattr(
            execution,
            "configured_service",
            lambda: ModelService({"text": model, "vision": model}),
        )
        patch.setattr(runtime, "WORKER", InlineWorker())
        patch.setattr(index, "build", lambda job, parsed: [])
        with TestClient(app) as client:
            job = storage.create(
                "fictional-demo.pdf", (destination / "manual.pdf").read_bytes()
            )["id"]
            folder = storage.job_dir(job)
            storage.save(folder / "document.json", document)
            storage.update(job, status="parsed")
            response = client.post(f"/api/jobs/{job}/analyze")
            if response.status_code != 200 or storage.state(job)["status"] != "ready":
                raise RuntimeError("The offline demonstration did not complete")
            profile = json.loads((folder / "profile.json").read_text())
            (destination / "results.json").write_text(
                json.dumps(
                    {
                        "demonstration": "Simulated model replies; real analysis and validation workflow. Not live AI output.",
                        "profile": profile,
                    },
                    indent=2,
                )
                + "\n"
            )
    print(
        f"Saved fictional demo with {len(profile['procedure_guides'])} guides to examples/demo/"
    )


if __name__ == "__main__":
    build_demo()
