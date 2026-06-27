@echo off
set ROOT=%~dp0..
cd /d "%ROOT%\web"
set NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000
if not exist node_modules (
  call npm.cmd install
)
call npm.cmd run dev
