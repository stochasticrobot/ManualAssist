# Agentic Workflow

Run manual analysis in a controlled order and save progress as work finishes.

These files coordinate requests, limits and continuation so a long or interrupted
analysis can retain useful results rather than start over.

## Files

| File | What it does |
| --- | --- |
| [analysis_stage_status.py](analysis_stage_status.py) | Explain which parts of a manual analysis are waiting, running or finished. |
| [build_analysis_progress.py](build_analysis_progress.py) | Collect the saved information needed to show a manual's progress in the browser. |
| [choose_document_inspections.py](choose_document_inspections.py) | Retain the earlier AI-led preview of a manual for historical checks. |
| [current_analysis_preview.py](current_analysis_preview.py) | Show a concrete example of the work the application is currently doing. |
| [estimate_inspection_allowance.py](estimate_inspection_allowance.py) | Calculate a stopping limit for the retired AI-led preview of a manual. |
| [estimate_remaining_fact_tokens.py](estimate_remaining_fact_tokens.py) | Estimate how much manual text is left to send for fact extraction. |
| [mark_interrupted_model_requests.py](mark_interrupted_model_requests.py) | Stop showing old AI requests as active after the application restarts. |
| [model_call_allowances.py](model_call_allowances.py) | Limit how much AI work can start in one authorized analysis or continuation. |
| [process_uploaded_manual.py](process_uploaded_manual.py) | Turn a newly uploaded PDF into saved text, then start its first analysis. |
| [restore_source_group_plan.py](restore_source_group_plan.py) | Check that a saved analysis plan still contains the manual text it should cover. |
| [reuse_saved_model_responses.py](reuse_saved_model_responses.py) | Find an earlier AI reply that can safely replace an identical new request. |
| [run_manual_analysis.py](run_manual_analysis.py) | Run the steps that turn a parsed manual into usable, source-linked results. |
| [run_source_group_tasks.py](run_source_group_tasks.py) | Apply one analysis task to successive portions of the manual and save each result. |
| [schedule_independent_model_tasks.py](schedule_independent_model_tasks.py) | Run independent pieces of analysis at the same time without starting them all at once. |
| [execution.py](execution.py) | Send a task to the configured AI and keep a record of what was asked and returned. |
| [validate_and_correct_model_json.py](validate_and_correct_model_json.py) | Handle AI answers whose required fields are missing, invalid or unreadable. |
