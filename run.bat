@echo off
REM One-command start on Windows
cd /d %~dp0
if not exist .venv python -m venv .venv
call .venv\Scripts\activate
pip install -q -r requirements.txt
set NUKKAD_RESET=1
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
