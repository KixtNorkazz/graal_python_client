@echo off
cd /d "%~dp0"
where py >nul 2>nul && (set "PY=py -3") || (set "PY=python")
%PY% -X faulthandler tools\debug_client.py %*
pause
