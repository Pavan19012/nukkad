#!/usr/bin/env bash
# One-command start: creates a virtualenv, installs deps, starts the server with fresh demo data.
set -e
cd "$(dirname "$0")"
[ -d .venv ] || python3 -m venv .venv
source .venv/bin/activate
pip install -q -r requirements.txt
NUKKAD_RESET=1 uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
