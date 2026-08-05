@echo off
chcp 65001 >nul
:: ============================================================
:: AI Monitoring - register the auto-run Task (double-click me)
:: Onward Corporate Design / GEO monitoring
::
:: Registers a Windows Scheduled Task that starts run_scheduled.bat
:: every day at a fixed time. The actual run days are decided by
:: config/schedule.json (e.g. only the 1st business day of a month).
::
:: Prepare config/schedule.json first (GUI "Save as OS auto-run"
:: button, or copy config/schedule.json.example).
::
:: Options (run from a command prompt):
::    register_scheduled_task.bat -Time "07:30"
::    register_scheduled_task.bat -WhetherLoggedOnOrNot
:: (ASCII-only launcher on purpose; Japanese messages come from the .ps1)
:: ============================================================
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\register_scheduled_task.ps1" %*
echo.
pause
