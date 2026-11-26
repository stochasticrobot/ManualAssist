#!/usr/bin/env bash
# Start the manual assistant on this computer using the project’s Python
# environment. The server listens only on the local machine so opening the app does
# not expose it to the network. This script does not analyse a manual or execute the
# credential file.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
exec .venv/bin/python -m uvicorn workbench.app:app --host 127.0.0.1 --port 8786
