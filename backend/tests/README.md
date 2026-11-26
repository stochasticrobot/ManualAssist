# Offline application tests

Run from the repository root after installing `requirements-dev.txt`:

```bash
python -m pytest -q
```

Tests use temporary job storage and controlled model responses. Real Bedrock client
creation is blocked by the automatic test setup. These checks cover processing,
limits, continuation, citations, guide review, recovery, exports and browser-request
handling. They demonstrate application behaviour, not live model judgment quality.

Private experiment snapshots, saved model conversations and tests that require
those historical files are deliberately not distributed. The included tests run
without uploaded manuals, credentials or those omitted experiment directories.
