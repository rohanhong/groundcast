@echo off
rem Installs groundcast on Windows: double-click this file, or run it from a
rem terminal with options for `groundcast setup` (for example: install.cmd --yes).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\install.ps1" %*
set status=%errorlevel%
rem A double-clicked window closes at once; keep it open to show the result.
echo %cmdcmdline% | find /i "%~0" >nul && pause
exit /b %status%
