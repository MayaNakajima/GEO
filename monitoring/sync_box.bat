@echo off
setlocal
chcp 65001 >nul
:: ============================================================
:: Sync with the shared Box folder (config/box_sync.json)
::   - pulls results added in Box, rebuilds the dashboard
::   - pushes code/docs and results to Box
:: The scheduled runner (run_scheduled.bat) already does this after
:: every launch; use this for an immediate sync.
::    sync_box.bat             sync now
::    sync_box.bat --dry-run   show what would be copied
:: ============================================================
cd /d "%~dp0"
set "CONDA_ROOT="
for %%P in (
  "C:\work\anaconda_install"
  "%USERPROFILE%\anaconda3"
  "%USERPROFILE%\Anaconda3"
  "%USERPROFILE%\miniconda3"
  "%USERPROFILE%\Miniconda3"
  "%LOCALAPPDATA%\anaconda3"
  "%ProgramData%\Anaconda3"
  "C:\Anaconda3"
) do (
  if not defined CONDA_ROOT if exist "%%~P\python.exe" set "CONDA_ROOT=%%~P"
)
if defined CONDA_ROOT (
  "%CONDA_ROOT%\python.exe" src\box_sync.py %*
) else (
  python src\box_sync.py %*
)
set "RC=%ERRORLEVEL%"
pause
endlocal & exit /b %RC%
