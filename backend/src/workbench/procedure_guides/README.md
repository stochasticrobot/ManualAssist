# Procedure Guides

Build practical installation, maintenance and troubleshooting guides from manual
passages.

An AI can inspect more text while investigating a task; the application checks
proposed guides and keeps unresolved questions visible instead of inventing steps.

## Files

| File | What it does |
| --- | --- |
| [build_saved_manual_guides.py](build_saved_manual_guides.py) | Build procedure guides for a manual whose earlier analysis is already saved. |
| [check_stalled_review_objections.py](check_stalled_review_objections.py) | Check whether a review complaint really requires changing the reader's guide. |
| [compare_source_and_guide_behavior.py](compare_source_and_guide_behavior.py) | Separate what a guide tells the reader to do from the quotations used to support it. |
| [consolidate_source_linked_tasks.py](consolidate_source_linked_tasks.py) | Turn overlapping task discoveries into an organized set of guides to investigate. |
| [generate_manual_procedure_guides.py](generate_manual_procedure_guides.py) | Find the manual's installation, maintenance and troubleshooting tasks and build their guides. |
| [inspect_procedure_sources.py](inspect_procedure_sources.py) | Let a guide-writing AI look up missing instructions in the original manual. |
| [legacy_cited_gap_schemas.py](legacy_cited_gap_schemas.py) | Read older saved troubleshooting replies using the citation rules they originally followed. |
| [planner.py](planner.py) | Investigate one practical task and turn the manual's scattered instructions into a guide. |
| [prepare_batched_guide_review.py](prepare_batched_guide_review.py) | Prepare focused comparisons between a guide's instructions and the manual passages behind them. |
| [procedure_reply_models.py](procedure_reply_models.py) | Define what an AI must return while discovering, investigating and writing a guide. |
| [recover_saved_guide_draft.py](recover_saved_guide_draft.py) | Prepare an already saved guide for another review without changing its instructions. |
| [repair_unresolved_manual_guides.py](repair_unresolved_manual_guides.py) | Try to finish the reviews that are keeping saved guides from reaching completed output. |
| [retain_failed_procedure_result.py](retain_failed_procedure_result.py) | Keep a useful saved draft when an AI repeatedly returns an unusable guide reply. |
| [retain_governing_heading_sources.py](retain_governing_heading_sources.py) | Keep the section headings that explain which instructions a manual passage belongs to. |
| [review_actions_with_code_owned_evidence.py](review_actions_with_code_owned_evidence.py) | Break source text into reviewable statements and retain an earlier grouped guide checker. |
| [reviewer.py](reviewer.py) | Review whether a generated guide follows the manual without adding or losing instructions. |
| [summarize_guide_investigations.py](summarize_guide_investigations.py) | Show how far installation, maintenance and troubleshooting guide investigations have progressed. |
| [validate_procedure_steps.py](validate_procedure_steps.py) | Reject broken guide structures and citations that do not match the supplied manual. |
| [verify_reported_behavior_defects.py](verify_reported_behavior_defects.py) | Retain an earlier check of whether a claimed guide defect is supported by the text. |

## Planner and reviewer reading order

1. [planner.py](planner.py) owns the investigation loop, saved work and request dispatch.
2. [planner_state.py](planner_state.py) describes progress and independently testable transitions.
3. [reviewer.py](reviewer.py) routes checks and decides whether unresolved findings remain.
4. [review_jobs.py](review_jobs.py) defines each question and allowed reply.
5. [review_batches.py](review_batches.py) splits requests without dropping source text.
6. [review_audit.py](review_audit.py) records answers and proposed corrections.

The four shortened module names replace the previous long import paths; update
external imports when upgrading. Function names and saved JSON remain unchanged.
