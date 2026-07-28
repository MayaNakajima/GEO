@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
:: ============================================================
:: テストデータ / 過去データの初期化（全削除）
:: 株式会社オンワードコーポレートデザイン
::
:: data\results, data\logs, data\reports 内の生成物と
:: data\dashboard.html を削除します（config や .env は残ります）。
:: 一部だけ消したい場合は data_clean_select.bat を使ってください。
:: ============================================================

set "MONITORING_DIR=%~dp0"
if "%MONITORING_DIR:~-1%"=="\" set "MONITORING_DIR=%MONITORING_DIR:~0,-1%"
cd /d "%MONITORING_DIR%"

set "PY="
for %%P in (
  "C:\work\anaconda_install\python.exe"
  "%USERPROFILE%\anaconda3\python.exe"
  "%USERPROFILE%\Anaconda3\python.exe"
  "%USERPROFILE%\miniconda3\python.exe"
  "%LOCALAPPDATA%\anaconda3\python.exe"
  "%ProgramData%\Anaconda3\python.exe"
  "C:\ProgramData\Anaconda3\python.exe"
  "C:\Anaconda3\python.exe"
) do (
  if not defined PY if exist "%%~P" set "PY=%%~P"
)
if not defined PY ( where python >nul 2>&1 && set "PY=python" )

if not defined PY (
  echo Python(Anaconda) が見つかりませんでした。Anaconda Prompt で次を実行してください:
  echo    cd /d "%MONITORING_DIR%"
  echo    python src\reset_data.py
  pause & exit /b 1
)

"!PY!" src\reset_data.py
echo.
pause
endlocal
