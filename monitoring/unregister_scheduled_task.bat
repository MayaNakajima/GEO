@echo off
chcp 65001 >nul
:: ============================================================
:: AI Monitoring - remove the auto-run Task (double-click me)
:: Onward Corporate Design / GEO monitoring
:: (ASCII-only launcher; Japanese messages come from the .ps1)
:: ============================================================
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\unregister_scheduled_task.ps1" %*
echo.
pause
