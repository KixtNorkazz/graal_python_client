@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul && (set "PY=py -3") || (set "PY=python")
if "%~1"=="" (
  %PY% start.py
  if errorlevel 1 pause
  goto :eof
)
set "ACC=%~1"
if "%GRAAL_PASSWORD%"=="" for /f "usebackq delims=" %%p in (`powershell -NoProfile -Command "$s = Read-Host 'Password' -AsSecureString; [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($s))"`) do set "GRAAL_PASSWORD=%%p"
%PY% start.py --account "%ACC%" %2 %3 %4 %5 %6 %7 %8 %9
endlocal
