# Model Access

Connect AI-assisted tasks to the configured text or image provider.

Shared request and reply handling lets the application change providers without
rewriting the manual-analysis steps.

## Files

| File | What it does |
| --- | --- |
| [code_owned_source_evidence.py](code_owned_source_evidence.py) | Attach real manual quotations and page references to the passages an AI selects. |
| [configure_model_providers.py](configure_model_providers.py) | Create the text and image AI connections selected in the application's settings. |
| [model_requests_and_responses.py](model_requests_and_responses.py) | Give the application one consistent way to ask different AI providers for help. |
| [parse_model_json.py](parse_model_json.py) | Read an AI's structured reply without guessing what a broken answer meant. |

## Areas

- [providers ](providers/README.md)
