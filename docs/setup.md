# Installation and configuration

The application has been exercised on Linux with Python 3.12 and CPU-only PyTorch.
Run these commands from the cloned repository:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install torch==2.15.0+cpu torchvision==0.29.2+cpu --index-url https://download.pytorch.org/whl/cpu
python -m pip install -r requirements.txt
cp .env.example .env
```

For an existing checkout, keep your current `.env` rather than copying over it.
Edit `.env` to supply your Bedrock API key, AWS region and permitted model IDs.
Then start the local server:

```bash
./run.sh
```

Open **http://127.0.0.1:8786/**. Keep the server bound to localhost unless you add
appropriate access controls. Node.js is not required to run the application.
OCR, layout and embedding models may download on first use. Uploading a usable
manual starts its first bounded analysis and can incur model-provider charges.

[requirements.txt](../requirements.txt) pins direct runtime dependencies to the tested
application environment and installs the local Python package. PyTorch is installed
separately above to select CPU wheels. The repository's `frontend/` directory must
remain beside `backend/`; this is a full-checkout application, not a backend-only wheel.

### Run the offline tests

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

The distributed tests use temporary storage and controlled model responses, with
live Bedrock connections blocked. Private experiment snapshots and tests that depend
on them are not included. See [test documentation](../backend/tests/README.md).

### What stays local

Uploaded PDFs, extracted text, search collections, generated reports and model-call
records are written under ignored `data/`. Credentials belong in ignored `.env`.
Neither is part of this repository. Source passages sent for AI analysis are processed
by the configured model provider; local storage does not make those requests offline.


## Continuous integration

GitHub Actions installs the CPU dependencies, runs the offline tests, checks Python
syntax and serious error rules with Ruff, and rebuilds the fictional demo. No API
keys or saved manuals are required. Linting is deliberately limited to error checks,
not a claim that the whole repository meets a new style or static-type standard.
