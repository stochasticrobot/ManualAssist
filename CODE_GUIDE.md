# Code reading guide

Start with the sequence that runs after a manual has been read, then follow one
procedure investigation from its initial evidence to its final review.

| Read in order | Responsibility |
| --- | --- |
| [Analysis workflow](backend/src/workbench/agentic_workflow/run_manual_analysis.py) | Run extraction, generated aids, guide investigations, publication and uncertainty checks. |
| [Procedure discovery](backend/src/workbench/procedure_guides/generate_manual_procedure_guides.py) | Find practical tasks and organize them into separate investigations. |
| [Procedure planner](backend/src/workbench/procedure_guides/planner.py) | Choose searches and reads, write a guide and respond to review corrections. |
| [Source inspection](backend/src/workbench/procedure_guides/inspect_procedure_sources.py) | Return original manual text requested by a planner. |
| [Guide review](backend/src/workbench/procedure_guides/reviewer.py) | Check relevant requirements, coverage, source support and evidence gaps. |
| [Review recovery](backend/src/workbench/procedure_guides/repair_unresolved_manual_guides.py) | Recheck blocked guides while preserving accepted results. |
| [Model requests](backend/src/workbench/agentic_workflow/execution.py) | Record requests, replies, failures and usage; enforce work limits. |
| [Source references](backend/src/workbench/model_access/code_owned_source_evidence.py) | Attach original quotations and page references to passages selected by a model. |
| [Browser navigation](frontend/src/application-navigation.js) | Connect user actions, page navigation and progress updates. |

## Boundaries

- Python controls the processing sequence; models choose bounded actions within
  procedure investigations. Model output is not executed as code.
- Browser files display saved results and send explicit requests. They do not hold
  provider credentials or perform the server's PDF extraction.
- Source quotations and structural checks are separate from model judgments about
  meaning. Passing them does not certify safety or completeness.
- Saved manuals and model-call records live under ignored `data/`, outside the
  published source. Local-only historical experiment records are not required to run.

Package READMEs describe the files in each area. See [backend](backend/README.md),
[frontend](frontend/README.md) and [tests](backend/tests/README.md).
