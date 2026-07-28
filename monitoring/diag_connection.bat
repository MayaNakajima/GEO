@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
:: ============================================================
:: 接続診断（本番のConnection error原因を切り分け）
:: 株式会社オンワードコーポレートデザイン
::
:: Anaconda の python.exe を最優先で直接使います
:: （ダブルクリック時に Microsoft Store のダミーpythonへ化けるのを回避）
:: ============================================================

set "MONITORING_DIR=%~dp0"
if "%MONITORING_DIR:~-1%"=="\" set "MONITORING_DIR=%MONITORING_DIR:~0,-1%"
cd /d "%MONITORING_DIR%"

echo ============================================================
echo   接続診断を開始します
echo ============================================================
echo.

:: ---- Anaconda の python.exe を直接探す（最優先） ----
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

:: ---- 見つからなければ PATH 上の python を試す ----
if not defined PY (
  where python >nul 2>&1 && set "PY=python"
)

if not defined PY (
  echo [エラー] Python(Anaconda) が見つかりませんでした。
  echo.
  echo スタートメニューから「Anaconda Prompt」を開き、次を実行してください:
  echo    cd /d "%MONITORING_DIR%"
  echo    python src\diag_connection.py
  echo.
  pause
  exit /b 1
)

echo 使用する Python: !PY!
echo.
"!PY!" src\diag_connection.py

echo.
echo ------------------------------------------------------------
echo 上の [2] プロキシ環境変数 と [4] の「原因」行 を控えて共有してください。
echo （成功なら「接続・認証ともにOK」と表示されます）
echo ------------------------------------------------------------
pause
endlocal
