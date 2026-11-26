# Manual Analysis

Extract useful information from manual text and check its supporting passages.

These files produce facts, FAQs, troubleshooting aids and uncertainty findings
while preserving references to the original instructions.

## Files

| File | What it does |
| --- | --- |
| [check_source_quotations.py](check_source_quotations.py) | Check that a claimed quotation really occurs in the supplied manual text. |
| [discover_and_review_uncertainties.py](discover_and_review_uncertainties.py) | Look for unclear or conflicting instructions and check whether the manual resolves them. |
| [estimate_fact_extraction_work.py](estimate_fact_extraction_work.py) | Estimate the work needed to extract facts before starting the analysis. |
| [extract_manual_facts.py](extract_manual_facts.py) | Extract facts from the manual and keep the original passages behind them. |
| [generate_faq_and_troubleshooting.py](generate_faq_and_troubleshooting.py) | Create reader questions and troubleshooting guidance from the manual's text. |
| [group_related_uncertainty_proposals.py](group_related_uncertainty_proposals.py) | Combine repeated questions about the same passages before investigating them. |
| [group_sources_for_fact_extraction.py](group_sources_for_fact_extraction.py) | Divide manual text into portions small enough to receive detailed fact lists. |
| [group_sources_for_uncertainty_review.py](group_sources_for_uncertainty_review.py) | Divide extracted manual text into manageable portions for checking unclear instructions. |
| [review_uncertainties_with_targeted_sources.py](review_uncertainties_with_targeted_sources.py) | Investigate whether a reported problem is answered elsewhere in the manual. |
| [select_uncertainty_review_sources.py](select_uncertainty_review_sources.py) | Find manual passages that may answer a reported ambiguity or contradiction. |
| [validate_extracted_facts.py](validate_extracted_facts.py) | Keep proposed facts only when their quoted evidence matches the supplied manual. |
| [validate_faq_and_troubleshooting.py](validate_faq_and_troubleshooting.py) | Check that generated answers and troubleshooting paths have usable supporting evidence. |
