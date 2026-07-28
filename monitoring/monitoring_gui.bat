@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
:: ============================================================
:: AI出現モニタリング GUI 起動スクリプト
:: 株式会社オンワードコーポレートデザイン
::
:: ダブルクリックでローカルWebサーバを起動し、ブラウザで設定画面を開きます。
:: Anaconda の python.exe を最優先で直接使います
:: （ダブルクリック時に Microsoft Store のダミーpythonへ化けるのを回避）
:: 自動実行はこの黒いウィンドウを開いている間だけ有効です。
:: ============================================================

set "MONITORING_DIR=%~dp0"
if "%MONITORING_DIR:~-1%"=="\" set "MONITORING_DIR=%MONITORING_DIR:~0,-1%"
cd /d "%MONITORING_DIR%"

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
if not defined PY ( where python >nul 2>&1 && set "PY=python" )

if not defined PY (
  echo.
  echo [エラー] Python(Anaconda) が見つかりませんでした。
  echo スタートメニューから「Anaconda Prompt」を開き、次を実行してください:
  echo    cd /d "%MONITORING_DIR%"
  echo    python src\webapp.py
  echo.
  echo 表示された http://127.0.0.1:8765/ をブラウザで開くと画面が出ます。
  pause
  exit /b 1
)

echo 使用する Python: !PY!
echo GUI を起動しています...（ブラウザが自動で開きます）
echo 開かない場合は、下に表示される http://127.0.0.1:8765/ をブラウザに貼り付けてください。
echo.

"!PY!" src\webapp.py

echo.
echo ------------------------------------------------------------
echo GUIサーバを終了しました。
echo 「ModuleNotFoundError」等が出た場合は、Anaconda Prompt で
echo    cd /d "%MONITORING_DIR%"
echo    pip install -r requirements.txt
echo を実行してから、もう一度このファイルを実行してください。
echo ------------------------------------------------------------
pause
endlocal
