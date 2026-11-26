"""Check that useful fact categories are not rejected merely because their names are
unfamiliar. Categories must still contain text, and accepted facts must retain
their evidence when exported."""

import json
import pytest
from pydantic import ValidationError
from workbench.data_models.analysis_and_question_models import Fact, FactExtraction
from workbench.manual_analysis.validate_extracted_facts import accept
from workbench.job_storage import job_files_and_audit_log as storage
from workbench.result_exports.write_reports_and_data_exports import publish


@pytest.mark.parametrize(
    "category",
    [
        "installation",
        "operating",
        "troubleshooting",
        "maintenance",
        "validation",
        "inspection",
        "disassembly",
        "reassembly",
        "quality assurance",
        "compliance",
        "integrity verification",
        "calibration",
        "a previously unseen procedure",
    ],
)
def test_categories_survive_validation_and_exports(category):
    """Preserve both requested categories and novel labels without a whitelist.

    Args:
        category: Descriptive label, including labels absent from schema examples.
    Returns:
        None; verifies unchanged category in accepted facts, saved JSON and HTML.
        A mismatched quotation is still rejected independently of the category.
    """
    fact = {
        "category": category,
        "name": "Instruction",
        "value": "Disconnect power.",
        "applies_to": "all",
        "evidence_id": "e1",
        "quote": "Disconnect power.",
    }
    batch = [{"id": "e1", "label": "text", "page": 1, "text": "Disconnect power."}]
    response = FactExtraction.model_validate({"facts": [fact]})
    accepted = accept(response, batch)
    assert accepted["facts"][0]["category"] == category
    job = storage.create("categories.pdf", b"%PDF-fixture")["id"]
    path = storage.job_dir(job)
    storage.save(path / "document.json", {"tables": []})
    profile = {
        "facts": accepted["facts"],
        "findings": [],
        "faq": [],
        "troubleshooting": [],
    }
    publish(job, profile)
    assert (
        json.loads((path / "profile.json").read_text())["facts"][0]["category"]
        == category
    )
    assert category in (path / "report.html").read_text()
    response.facts[0].quote = "A quotation the source does not contain."
    assert not accept(response, batch)["facts"]


def test_category_still_requires_a_nonempty_string():
    """Reject malformed category data without restricting descriptive vocabulary.

    Args:
        None.
    Returns:
        None; verifies type/empty-value checks while permitting arbitrary real labels.
    """
    for category in (None, 17, [], "", "   "):
        with pytest.raises(ValidationError):
            Fact.model_validate(
                {
                    "category": category,
                    "name": "x",
                    "value": "x",
                    "applies_to": "x",
                    "evidence_id": "e1",
                    "quote": "x",
                }
            )
