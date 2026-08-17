<#
────────────────────────────────────────────────────────────
 AI出現モニタリング  Windows タスクスケジューラ登録スクリプト
 株式会社オンワードコーポレートデザイン
────────────────────────────────────────────────────────────
 run_scheduled.bat を「毎日 指定時刻」に起動するタスクを登録する。
 実際にどの日を実行するかは config/schedule.json の頻度ルールで
 run_scheduled.py が判定する（デイリーゲート方式）。

 これにより GUI（黒いウィンドウ）を閉じていても実行される。
 さらに -WakeToRun によりスリープ／休止状態からは自動復帰して実行する
 （※完全にシャットダウン＝電源OFFの状態からは起動できない）。

 使い方（PowerShell）:
   # 既定（毎日 09:00 起動 / ログオン中のみ実行 / タスク名 GEO_AI_Monitoring）
   powershell -ExecutionPolicy Bypass -File tools\register_scheduled_task.ps1

   # 起動時刻を指定
   powershell -ExecutionPolicy Bypass -File tools\register_scheduled_task.ps1 -Time "07:30"

   # ログオフ中でも実行（S4U。通常は管理者権限が必要）
   powershell -ExecutionPolicy Bypass -File tools\register_scheduled_task.ps1 -WhetherLoggedOnOrNot

 ※ 時刻を省略した場合は config/schedule.json の rule.time を使う（無ければ 09:00）。
────────────────────────────────────────────────────────────
#>
param(
    [string]$Time = "",
    [string]$TaskName = "GEO_AI_Monitoring",
    [switch]$WhetherLoggedOnOrNot
)

$ErrorActionPreference = "Stop"

# ---- パス解決（このスクリプトは monitoring\tools\ にある想定） ----
$MonitoringDir = Split-Path -Parent $PSScriptRoot
$Bat = Join-Path $MonitoringDir "run_scheduled.bat"
$ConfPath = Join-Path $MonitoringDir "config\schedule.json"

if (-not (Test-Path $Bat)) {
    Write-Host "[エラー] run_scheduled.bat が見つかりません: $Bat" -ForegroundColor Red
    exit 1
}

if (-not (Test-Path $ConfPath)) {
    Write-Host "[注意] config\schedule.json がまだありません。" -ForegroundColor Yellow
    Write-Host "  タスクは登録できますが、実行日を決める設定が無いため実行されません。" -ForegroundColor Yellow
    Write-Host "  先にGUI（monitoring_gui.bat）の「OS自動実行として保存」で作成するか、" -ForegroundColor Yellow
    Write-Host "  config\schedule.json.example をコピーして config\schedule.json を作成してください。" -ForegroundColor Yellow
    Write-Host ""
}

# ---- 起動時刻の決定（未指定なら schedule.json の rule.time → 既定 09:00） ----
if ([string]::IsNullOrWhiteSpace($Time)) {
    if (Test-Path $ConfPath) {
        try {
            $conf = Get-Content $ConfPath -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($conf.rule -and $conf.rule.time) { $Time = $conf.rule.time }
        } catch { }
    }
    if ([string]::IsNullOrWhiteSpace($Time)) { $Time = "09:00" }
}

# 時刻の妥当性チェック（HH:mm）
if ($Time -notmatch '^([01]?\d|2[0-3]):[0-5]\d$') {
    Write-Host "[エラー] 時刻の形式が不正です（HH:mm で指定してください）: $Time" -ForegroundColor Red
    exit 1
}

Write-Host "============================================================"
Write-Host " タスクスケジューラ登録"
Write-Host "   タスク名   : $TaskName"
Write-Host "   起動       : 毎日 $Time"
Write-Host "   実行スク   : $Bat"
Write-Host "   作業フォルダ: $MonitoringDir"
Write-Host "============================================================"

# ---- OS電源設定：スリープ解除タイマーを有効化 ----
# -WakeToRun は電源プランの「スリープ解除タイマーの許可」が有効でないと機能しない。
# 企業PCやバッテリ駆動では既定で無効なことが多く、これが「スリープ中に実行され
# ない」主因になる。現在の電源プランに対して AC/DC 両方で有効化しておく（best-effort）。
try {
    $SUB_SLEEP = "238C9FA8-0AAD-41ED-83F4-97BE242C8F20"
    $RTCWAKE   = "BD3B718A-0680-4D9D-8AB2-E1D2B4AC806D"   # Allow wake timers
    & powercfg /SETACVALUEINDEX SCHEME_CURRENT $SUB_SLEEP $RTCWAKE 1 | Out-Null
    & powercfg /SETDCVALUEINDEX SCHEME_CURRENT $SUB_SLEEP $RTCWAKE 1 | Out-Null
    & powercfg /SETACTIVE SCHEME_CURRENT | Out-Null
    Write-Host "   電源設定   : スリープ解除タイマーを有効化しました（AC/DC）"
} catch {
    Write-Host "[注意] スリープ解除タイマーの有効化に失敗しました（権限や環境による）。" -ForegroundColor Yellow
    Write-Host "  スリープ中の自動起動が効かない場合は、コントロールパネルの電源オプションで" -ForegroundColor Yellow
    Write-Host "  『スリープ解除タイマーの許可』を『有効』にしてください。" -ForegroundColor Yellow
}

# ---- タスク定義 ----
$action = New-ScheduledTaskAction -Execute $Bat -WorkingDirectory $MonitoringDir

# (1) 毎日 指定時刻の起動トリガー
$triggerDaily = New-ScheduledTaskTrigger -Daily -At ([datetime]$Time)

# (2) スリープ／休止からの復帰イベントで起動するトリガー
#     Windows は復帰時に System ログへ Power-Troubleshooter (EventID 1) を記録する。
#     これを購読することで「実行時刻を逃した後にユーザーがPCを起こした」場合でも
#     タスクが起動し、run_scheduled.py のキャッチアップ判定で未消化の回を実行できる。
#     復帰直後はネットワーク等が不安定なため 1 分遅延させる。
$triggerResume = $null
try {
    $evtClass = Get-CimClass -ClassName MSFT_TaskEventTrigger `
        -Namespace Root/Microsoft/Windows/TaskScheduler -ErrorAction Stop
    $triggerResume = New-CimInstance -CimClass $evtClass -ClientOnly
    $triggerResume.Enabled = $true
    $triggerResume.Subscription =
        '<QueryList><Query Id="0" Path="System"><Select Path="System">' +
        '*[System[Provider[@Name=''Microsoft-Windows-Power-Troubleshooter''] and (EventID=1)]]' +
        '</Select></Query></QueryList>'
    $triggerResume.Delay = "PT1M"
} catch {
    Write-Host "[注意] スリープ復帰トリガーを作成できませんでした。毎日起動のみで登録します。" -ForegroundColor Yellow
}

if ($triggerResume) {
    $triggers = @($triggerDaily, $triggerResume)
    Write-Host "   起動条件   : 毎日 $Time ＋ スリープ復帰時（未実行分を自動キャッチアップ）"
} else {
    $triggers = @($triggerDaily)
    Write-Host "   起動条件   : 毎日 $Time"
}

# WakeToRun     … スリープ／休止からは自動復帰して実行
# StartWhenAvailable … 起動時刻を逃した場合（スリープ中など）は復帰後すぐ実行
# バッテリ関連 … ノートPCでバッテリ駆動でも実行を止めない
# MultipleInstances IgnoreNew … 前回実行が長引いても二重起動しない
# RestartCount/Interval … 復帰直後の一時的失敗（ネット未接続など）を数回リトライ
$settings = New-ScheduledTaskSettingsSet `
    -WakeToRun `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 5) `
    -ExecutionTimeLimit (New-TimeSpan -Hours 3)

# ---- 実行アカウント ----
if ($WhetherLoggedOnOrNot) {
    # ログオフ中でも実行（S4U：パスワード保存不要だが通常は管理者権限が必要）
    $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType S4U -RunLevel Limited
    Write-Host "   実行条件   : ログオフ中でも実行（S4U）"
} else {
    # ログオン中のみ実行（パスワード不要・最も確実）
    $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
    Write-Host "   実行条件   : ログオン中のみ実行"
}

# ---- 登録 ----
try {
    Register-ScheduledTask -TaskName $TaskName `
        -Action $action -Trigger $triggers -Settings $settings -Principal $principal `
        -Description "生成AI出現モニタリング（GEO定点観測）の定期自動実行。実行日は config/schedule.json の頻度ルールで判定。" `
        -Force | Out-Null
} catch {
    Write-Host ""
    Write-Host "[エラー] タスク登録に失敗しました: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "  → PowerShell を『管理者として実行』してから再度お試しください。" -ForegroundColor Yellow
    if ($WhetherLoggedOnOrNot) {
        Write-Host "  （-WhetherLoggedOnOrNot（S4U）は管理者権限が必要な場合があります）" -ForegroundColor Yellow
    }
    exit 1
}

Write-Host ""
Write-Host "✓ 登録しました。" -ForegroundColor Green

# ---- 次回起動時刻を表示 ----
try {
    $info = Get-ScheduledTaskInfo -TaskName $TaskName
    Write-Host "   次回起動予定 : $($info.NextRunTime)"
} catch { }

Write-Host ""
Write-Host "確認・操作:"
Write-Host "   状態確認   : Get-ScheduledTaskInfo -TaskName $TaskName"
Write-Host "   今すぐテスト: Start-ScheduledTask -TaskName $TaskName"
Write-Host "   解除       : tools\unregister_scheduled_task.bat（または unregister_scheduled_task.ps1）"
Write-Host ""
Write-Host "※ 実行する曜日／営業日などの頻度は config/schedule.json で決まります。"
Write-Host "   GUI の『OS自動実行として保存』か、schedule.json.example を編集して作成してください。"
