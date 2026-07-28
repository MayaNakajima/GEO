@echo off
chcp 65001 >nul
:: ============================================================
:: AI出現モニタリング 実行スクリプト（自動実行・全モデル版）
:: 株式会社オンワードコーポレートデザイン
::
:: 【用途】
:: ・Windowsタスクスケジューラに登録する自動実行用です
:: ・メニューを表示せず、全有効モデル・全質問を実行します
:: ・手動で特定LLMだけ実行したい場合は monitoring_run.bat を使ってください
::
:: 【パス設定不要】
:: このバッチファイルが置かれているフォルダを自動で取得します。
:: ============================================================

:: このバッチファイルが置かれているフォルダを自動取得（末尾の \ を除去）
set MONITORING_DIR=%~dp0
if "%MONITORING_DIR:~-1%"=="\" set MONITORING_DIR=%MONITORING_DIR:~0,-1%

:: Python のパス（通常はそのままでOK）
set PYTHON=python

:: ログファイル（monitoring\data\run_log.txt に保存）
set LOGFILE=%MONITORING_DIR%\data\run_log.txt

echo ============================== >> "%LOGFILE%"
echo 実行開始: %date% %time% >> "%LOGFILE%"
echo ============================== >> "%LOGFILE%"

cd /d "%MONITORING_DIR%"
%PYTHON% src\runner.py --all >> "%LOGFILE%" 2>&1

echo 実行終了: %date% %time% >> "%LOGFILE%"
echo. >> "%LOGFILE%"
