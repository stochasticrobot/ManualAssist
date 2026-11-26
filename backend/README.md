# Backend

Python reads the PDF, coordinates AI work, saves progress and serves the local web
application. Start with the [code guide](../CODE_GUIDE.md), then the
[analysis workflow](src/workbench/agentic_workflow/run_manual_analysis.py).

- [PDF reading](src/workbench/pdf_processing/README.md): text, tables, page images and navigation.
- [Manual analysis](src/workbench/manual_analysis/README.md): facts, FAQs and uncertainty checks.
- [Guide investigations](src/workbench/procedure_guides/README.md): discovery, source reading, drafting and review.
- [AI connections](src/workbench/model_access/README.md): provider selection and request/reply handling.
- [Search](src/workbench/document_search/README.md): local passage retrieval and cited answers.
- [Browser requests](src/workbench/http_endpoints/README.md): uploads, work controls and result delivery.
- [Tests](tests/README.md): standalone checks without paid model calls.
