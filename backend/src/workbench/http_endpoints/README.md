# Http Endpoints

Connect browser actions to saved manuals and the work the server can perform.

These files receive uploads, questions and explicit analysis requests, and serve
progress, original pages and downloadable results.

## Files

| File | What it does |
| --- | --- |
| [background_worker_and_question_lock.py](background_worker_and_question_lock.py) | Keep long-running analysis from occupying the browser's request handler. |
| [procedure_guide_routes.py](procedure_guide_routes.py) | Let a reader build missing guides or repair unresolved reviews for a saved manual. |
| [questions_and_review_routes.py](questions_and_review_routes.py) | Receive a reader's manual question or saved note about an unresolved issue. |
| [read_backend_review_version.py](read_backend_review_version.py) | Report which guide-review code the running server actually loaded. |
| [read_saved_model_request.py](read_saved_model_request.py) | Show the actual saved instructions and source text for a selected AI request. |
| [reference_illustration_routes.py](reference_illustration_routes.py) | Serve original manual illustrations and accept explicit requests to prepare them. |
| [serve_application.py](serve_application.py) | Create the local web application and serve its browser pages and files. |
| [serve_pdf_and_exports.py](serve_pdf_and_exports.py) | Let readers open the original PDF and download the results produced from it. |
| [upload_and_analysis_routes.py](upload_and_analysis_routes.py) | Receive uploaded manuals and requests to start or continue their analysis. |
| [validate_job_identifier.py](validate_job_identifier.py) | Check that a requested manual has a valid identifier before opening its files. |
