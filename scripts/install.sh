#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m venv .venv
.venv/bin/python -m pip install --index-url https://download.pytorch.org/whl/cpu torch==2.14.1+cpu
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m pip install -e . --no-deps
install -Dm755 .venv/bin/dog-walker "$HOME/.local/bin/dog-walker"
.venv/bin/python -m dog_walker.cli setup-local-judge
.venv/bin/python scripts/install-desktop.py
echo 'Ready. Open Dog Walker from your app launcher. The terminal demo is dog-walker demo.'
