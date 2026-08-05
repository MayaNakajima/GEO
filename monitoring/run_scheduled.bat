@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
:: ============================================================
:: AI Monitoring - headless scheduled runner (launched by Task Scheduler)
:: Onward Corporate Design / GEO monitoring
::
:: Runs even when the GUI window is closed. run_scheduled.py checks
:: config/schedule.json and only executes on matching days.
:: ASCII-only on purpose - cmd.exe misparses multibyte comments under
:: some codepages. Japanese guidance lives in the .ps1 and .md files.
::
:: Manual test:
::    run_scheduled.bat --check              show decision / next dates
::    run_scheduled.bat --force              run now, ignore day gate
::    run_scheduled.bat --force --dry-run    run now, no API calls
:: ============================================================

set "MONITORING_DIR=%~dp0"
if "%MONITORING_DIR:~-1%"=="\" set "MONITORING_DIR=%MONITORING_DIR:~0,-1%"
cd /d "%MONITORING_DIR%"

:: ---- Locate Anaconda python.exe (same list as monitoring_gui.bat) ----
set "PY="
for %%P in (
  "C:\work\anaconda_install\python.exe"
  "%USERPROFILE%\anaconda3\python.exe"
  "%USERPROFILE%\Anaconda3\python.exe"
  "%USERPROFILE%\miniconda3\python.exe"
  "%USERPROFILE%\Miniconda3\python.exe"
  "%LOCALAPPDATA%\anaconda3\python.exe"
  "%LOCALAPPDATA%\Continuum\anaconda3\python.exe"
  "%ProgramData%\Anaconda3\python.exe"
  "C:\ProgramData\Anaconda3\python.exe"
  "C:\Anaconda3\python.exe"
) do (
  if not defined PY if exist "%%~P" set "PY=%%~P"
)
if not defined PY where python >nul 2>&1 && set "PY=python"

if not defined PY goto :nopy

"!PY!" src\run_scheduled.py %*
set "RC=!ERRORLEVEL!"
endlocal & exit /b %RC%

:nopy
echo [ERROR] Python / Anaconda not found. >&2
>> "%MONITORING_DIR%\data\run_log.txt" echo run_scheduled.bat: Python not found - cannot run.
endlocal & exit /b 1
