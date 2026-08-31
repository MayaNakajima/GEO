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
:: IMPORTANT: this launcher ACTIVATES the Anaconda base environment
:: (the same thing the "Anaconda Prompt" shortcut does) before running
:: Python. Activation runs conda's activate.d scripts (e.g. SSL cert
:: setup) and fixes PATH/DLL resolution, so API calls behave exactly
:: like a manual run inside Anaconda Prompt. Calling python.exe directly
:: skipped this and was a source of unreliable runs.
::
:: Manual test:
::    run_scheduled.bat --check              show decision / next dates
::    run_scheduled.bat --force              run now, ignore day gate
::    run_scheduled.bat --force --dry-run    run now, no API calls
:: ============================================================

set "MONITORING_DIR=%~dp0"
if "%MONITORING_DIR:~-1%"=="\" set "MONITORING_DIR=%MONITORING_DIR:~0,-1%"
cd /d "%MONITORING_DIR%"

:: ---- Locate the Anaconda / Miniconda ROOT (folder containing python.exe) ----
:: Same candidate list as monitoring_gui.bat, but we keep the ROOT folder so
:: we can call its Scripts\activate.bat (Anaconda Prompt style activation).
set "CONDA_ROOT="
for %%P in (
  "C:\work\anaconda_install"
  "%USERPROFILE%\anaconda3"
  "%USERPROFILE%\Anaconda3"
  "%USERPROFILE%\miniconda3"
  "%USERPROFILE%\Miniconda3"
  "%LOCALAPPDATA%\anaconda3"
  "%LOCALAPPDATA%\Continuum\anaconda3"
  "%ProgramData%\Anaconda3"
  "C:\ProgramData\Anaconda3"
  "C:\Anaconda3"
) do (
  if not defined CONDA_ROOT if exist "%%~P\python.exe" set "CONDA_ROOT=%%~P"
)

if defined CONDA_ROOT goto :haveconda

:: ---- Fallback: no known Anaconda root found; try a bare "python" on PATH ----
where python >nul 2>&1
if errorlevel 1 goto :nopy
echo [WARN] Anaconda root not found - falling back to "python" on PATH (no conda activation). >&2
>> "%MONITORING_DIR%\data\run_log.txt" echo run_scheduled.bat: WARN Anaconda root not found; used PATH python.
python src\run_scheduled.py %*
set "RC=!ERRORLEVEL!"
endlocal & exit /b %RC%

:haveconda
:: ---- Activate the base environment (Anaconda Prompt behaviour) ----
:: activate.bat sets up PATH and runs etc\conda\activate.d\* (SSL certs, etc.).
call "%CONDA_ROOT%\Scripts\activate.bat" "%CONDA_ROOT%"
if errorlevel 1 (
  echo [WARN] conda activate failed - falling back to direct python.exe. >&2
  >> "%MONITORING_DIR%\data\run_log.txt" echo run_scheduled.bat: WARN conda activate failed; used python.exe directly.
  "%CONDA_ROOT%\python.exe" src\run_scheduled.py %*
  set "RC=!ERRORLEVEL!"
  endlocal & exit /b %RC%
)

:: cd again in case activation changed the directory.
cd /d "%MONITORING_DIR%"
python src\run_scheduled.py %*
set "RC=!ERRORLEVEL!"
endlocal & exit /b %RC%

:nopy
echo [ERROR] Python / Anaconda not found. >&2
>> "%MONITORING_DIR%\data\run_log.txt" echo run_scheduled.bat: Python not found - cannot run.
endlocal & exit /b 1
