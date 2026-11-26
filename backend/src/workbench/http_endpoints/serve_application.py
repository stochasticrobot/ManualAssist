"""Create the local web application and serve its browser pages and files.

This file connects the available browser requests, applies local-access checks,
and handles server startup and shutdown. It makes the interface reachable; the
actual manual reading, analysis and page content are handled separately."""

from contextlib import asynccontextmanager
from fastapi import FastAPI, Request as HTTPRequest
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from workbench.config import FRONTEND
from workbench.agentic_workflow.mark_interrupted_model_requests import mark_interrupted_model_requests
from workbench.job_storage import job_files_and_audit_log as storage
from workbench.http_endpoints import (
    reference_illustration_routes as illustrations,
    upload_and_analysis_routes as jobs,
    procedure_guide_routes as procedure_guides,
    questions_and_review_routes as questions,
    serve_pdf_and_exports as assets,
    read_saved_model_request as model_requests,
    read_backend_review_version as runtime,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Mark interrupted work honestly on startup; never automatically repeat paid calls.

    Args:
        app: FastAPI application instance.
    Returns:
        Async lifecycle context; updates only unfinished persisted job states.
    """
    for state in storage.list_jobs():
        mark_interrupted_model_requests(state["id"])
        if state.get("illustration_status") == "preparing":
            storage.update(state["id"], illustration_status="incomplete")
        if state["status"] in ("queued", "parsing", "analyzing"):
            storage.update(
                state["id"],
                status="interrupted",
                stage="Interrupted by restart",
                message="Saved artifacts remain available; no automatic paid retry occurred.",
            )
    yield


app = FastAPI(title="Manual Workbench", lifespan=lifespan)
app.mount(
    "/static/src", StaticFiles(directory=FRONTEND / "src"), name="frontend-source"
)
app.include_router(jobs.router)
app.include_router(illustrations.router)
app.include_router(procedure_guides.router)
app.include_router(questions.router)
app.include_router(assets.router)
app.include_router(model_requests.router)
app.include_router(runtime.router)


@app.middleware("http")
async def local_guard(request: HTTPRequest, call_next):
    """Reject cross-origin mutations and set safe response defaults for the local demo.

    Args:
        request: Incoming browser/API request.
        call_next: ASGI next-handler callable.
    Returns:
        Response with no-sniff headers, or 403 for a foreign mutation origin.
        This is not internet authentication; server binds to loopback only.
    """
    origin = request.headers.get("origin")
    if (
        request.method not in ("GET", "HEAD", "OPTIONS")
        and origin
        and origin != str(request.base_url).rstrip("/")
    ):
        return Response("Cross-origin mutations are not allowed", status_code=403)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    return response


@app.get("/")
def home():
    """Serve the static application shell without paid work.

    Args:
        None.
    Returns:
        HTML application document.
    """
    return FileResponse(FRONTEND / "index.html")


@app.get("/static/style.css")
def stylesheet():
    """Serve browser styling without exposing frontend tests or development packages.

    Args:
        None.
    Returns:
        The frontend-owned CSS file; report templates and node_modules stay private.
    """
    return FileResponse(FRONTEND / "style.css", media_type="text/css")
