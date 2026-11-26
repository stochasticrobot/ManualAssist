"""Turn saved analysis results into downloadable reports and data files.

Readers can keep an HTML report, inspect structured JSON, or use fact tables in a
spreadsheet. This file writes those formats and preserves recorded limitations. It
does not ask an AI to create new advice or certify existing advice as correct."""

import csv
import json
import os
from jinja2 import Environment, FileSystemLoader, select_autoescape
from workbench.config import FRONTEND
from workbench.job_storage import job_files_and_audit_log as storage


def write_csv(path, facts, category):
    """Export one fact category with source references and spreadsheet-safe cells.

    Args:
        path: Destination CSV path inside the job directory.
        facts: Source-anchored fact dictionaries.
        category: Category to include, such as part or maintenance.
    Returns:
        None; writes a header and matching rows, escaping formula-leading text.
    """
    with path.open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(
            ["name", "value", "applies_to", "physical_pdf_page", "evidence_id", "quote"]
        )
        for fact in facts:
            if fact["category"] != category:
                continue
            cells = [
                str(fact[k])
                for k in ("name", "value", "applies_to", "page", "evidence_id", "quote")
            ]
            writer.writerow(
                [
                    "'" + cell if cell.startswith(("=", "+", "-", "@")) else cell
                    for cell in cells
                ]
            )


def render_reports(job_id, profile, path):
    """Render standalone HTML using frontend-owned templates and escaped data.

    Args:
        job_id: Existing job ID used in source-document links.
        profile: Accepted facts and decision aids, plus review limitations.
        path: Private output directory for report.html and quick-start.html.
    Returns:
        None; renders HTML without executing source text. The quick card is a disclosed
        selection of up to four safety and four startup facts, not exhaustive advice.
    """
    environment = Environment(
        loader=FileSystemLoader(FRONTEND / "report-templates"),
        autoescape=select_autoescape(["html"]),
    )
    facts = profile["facts"]
    quick = [f for f in facts if f["category"] in ("safety", "quick_start")]
    selected = [f for f in quick if f["category"] == "safety"][:4] + [
        f for f in quick if f["category"] == "quick_start"
    ][:4]
    source_url = (
        os.environ.get("PUBLIC_URL", "http://127.0.0.1:8786").rstrip("/")
        + f"/api/jobs/{job_id}/source"
    )
    for name in ("report.html", "quick-start.html"):
        content = environment.get_template(name).render(
            profile=profile,
            source_url=source_url,
            selected=selected,
            quick_total=len(quick),
        )
        (path / name).write_text(content)


def publish(job_id, profile):
    """Write source-linked JSON, CSV and report assets from accepted extraction.

    Args:
        job_id: Existing job with parsed document.json.
        profile: Extraction/review results; product_profile is added to this mapping.
    Returns:
        None; writes inspectable outputs, including troubleshooting.json and faq.json.
        Old profiles remain readable and yield empty decision-aid lists, not invented aids.
    """
    path = storage.job_dir(job_id)
    document = json.loads((path / "document.json").read_text())
    categories = {
        "identity": "product",
        "models_covered": "model",
        "key_specs": "specification",
        "power_requirements": "power",
        "environmental_ratings_and_limits": "environment",
    }
    profile["product_profile"] = {
        name: [f for f in profile["facts"] if f["category"] == category]
        for name, category in categories.items()
    }
    storage.save(path / "profile.json", profile)
    storage.save(path / "tables.json", document["tables"])
    for key in ("troubleshooting", "troubleshooting_checks", "faq", "procedure_guides"):
        storage.save(path / f"{key}.json", profile.get(key, []))
    write_csv(path / "parts.csv", profile["facts"], "part")
    write_csv(path / "maintenance.csv", profile["facts"], "maintenance")
    render_reports(job_id, profile, path)
