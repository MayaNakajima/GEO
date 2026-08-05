<#
────────────────────────────────────────────────────────────
 AI出現モニタリング  タスクスケジューラ 解除スクリプト
 株式会社オンワードコーポレートデザイン
────────────────────────────────────────────────────────────
 register_scheduled_task.ps1 で登録した自動実行タスクを削除する。

 使い方（PowerShell）:
   powershell -ExecutionPolicy Bypass -File tools\unregister_scheduled_task.ps1
   powershell -ExecutionPolicy Bypass -File tools\unregister_scheduled_task.ps1 -TaskName GEO_AI_Monitoring
────────────────────────────────────────────────────────────
#>
param(
    [string]$TaskName = "GEO_AI_Monitoring"
)

$ErrorActionPreference = "Stop"

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if (-not $task) {
    Write-Host "タスク '$TaskName' は登録されていません（すでに解除済みか、未登録）。" -ForegroundColor Yellow
    exit 0
}

try {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "✓ タスク '$TaskName' を解除しました。" -ForegroundColor Green
} catch {
    Write-Host "[エラー] 解除に失敗しました: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "  → PowerShell を『管理者として実行』してから再度お試しください。" -ForegroundColor Yellow
    exit 1
}
