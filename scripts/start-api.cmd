@echo off
set ROOT=%~dp0..
cd /d "%ROOT%"
if "%PYTHON_EXE%"=="" set PYTHON_EXE=python
set PYTHONPATH=%ROOT%\src
"%PYTHON_EXE%" -m uvicorn harbor_agent.app:app --host 127.0.0.1 --port 8000
