#!/bin/bash
# Start the local app. The first launch creates .venv and installs dependencies.
# Double-click "Image Utilities.app" to open it without Terminal.
set -euo pipefail
cd "$(dirname "$0")"
if [[ ! -x .venv/bin/python ]]; then
  uv venv --python 3.12 .venv
  uv pip install --python .venv/bin/python -r requirements.txt
fi
exec .venv/bin/python -m app "$@"
