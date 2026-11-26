# Fictional demonstration

This original, three-page software fixture is not a manufacturer's manual and must
not be used to operate a real appliance. No user upload, third-party manual or private
analysis record is bundled.

- [Manual PDF](demo/manual.pdf): printable fictional instructions.
- [Manual text](demo/manual.md): the same authored passages, readable on GitHub.
- [Parsed document](demo/document.json): original passages with source IDs and pages.
- [Generated results](demo/results.json): five procedure guides plus other profile fields.

## What was generated

The real HTTP analysis entry point, planner, citation validators, reviewer and result
assembly ran with simulated model replies from the public test helpers. Replies are
prewritten behavior, not live AI reasoning. PDF extraction, background scheduling and
vector embedding are bypassed. Review acceptance here therefore demonstrates software
flow and output structure, **not the quality or safety of model judgments**.

The PDF is rendered from the same original text; it is not the input to the offline
rebuild. You can upload it separately to try actual extraction and model analysis,
which requires the configured provider and can incur charges.

## Rebuild

After installing development requirements, run from the repository root:

```bash
python examples/build_demo.py
```

The command uses temporary job storage and no API key. It replaces only the four
example files listed above. It never reads saved user jobs or publishes model-request
receipts. Generated IDs and PDF metadata may differ between builds.

The manual passages were authored as part of this project's test fixtures rather than
copied from a third-party publication. Reuse permissions follow the project's eventual
license; no separate license is implied by including these files.
