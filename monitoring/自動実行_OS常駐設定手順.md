# 自動実行（OS常駐）設定手順 — アプリを閉じても実行する

株式会社オンワードコーポレートデザイン ／ GEO定点観測ツール

このドキュメントは、**GUI（黒いウィンドウ）を閉じても自動実行が続く**ように、
Windows タスクスケジューラへ登録する手順を説明します。

---

## 0. これで何ができるか（と、できないこと）

| やりたいこと | 可否 | 説明 |
|---|---|---|
| **アプリ（GUI画面）を閉じても実行** | ✅ できる | Windowsタスクスケジューラが裏で実行します。 |
| **PCがスリープ中、予定時刻に自動復帰して実行** | ✅ できる（条件あり） | `-WakeToRun` ＋「スリープ解除タイマーの許可」を有効化して復帰します。※後述のとおり**軽い（S3）スリープが対象**。休止(S4)や電源設定次第で復帰しないことがあります。 |
| **予定時刻に復帰しなかった → 後で手動でPCを起こしたとき実行** | ✅ できる | スリープ復帰イベントでタスクが起動し、**取り残した回を自動キャッチアップ**して実行します（本改修の要点）。 |
| **PCが完全に電源OFF（シャットダウン）でも実行** | ❌ できない | 電源が切れているとどんな仕組みでも動きません。 |

> **重要**：電源を落とす運用で確実に実行したい場合は、PCを **「スリープ」** にして
> **電源アダプタを接続したまま** にしてください（シャットダウンはしない）。
> それも難しい場合は、クラウド実行（GitHub Actions 等）への移行が必要です（別途相談）。

> **スリープからの自動復帰について**：`-WakeToRun` は Windows の電源設定
> 「スリープ解除タイマーの許可」が**有効**でないと機能しません。企業PCやバッテリ駆動では
> 既定で無効なことが多いのが「スリープ中に実行されない」主因でした。
> `register_scheduled_task.bat` は登録時にこの設定を自動で有効化します（AC/DC 両方、best-effort）。
> それでも復帰しない環境（休止＝S4、電源プランの制約など）に備え、**復帰時キャッチアップ**
> も用意しています → 予定時刻に起きられなくても、次にPCを起こした時点で取り残した回を実行します。

> **実行するPC**：この自動実行は **設定（タスク登録）した本人のPC** で動きます
> （各自が自分のキー＝`.env`・自分の `config/schedule.json` で実行）。
> そのPCが起動している時間帯に実行時刻を合わせてください。結果は各PCの `data/` に保存されます。
> 全員分を1か所に集約したい場合は「実行は1台に集約・他は閲覧のみ」の構成も検討可（引き継ぎ指示書 §7）。

---

## 1. 仕組み（デイリーゲート＋キャッチアップ方式）

既存GUIの豊富な頻度設定（●日おき／毎週／隔週／毎月〇日／第◆曜日／第N営業日／
月初・月末営業日、**日本の祝日除外**）をそのまま活かすため、次の2段構えにしています。

1. **タスクスケジューラは「毎日 決まった時刻」＋「スリープ復帰時」に起動**するだけ。
2. 起動された `run_scheduled.py` が `config/schedule.json` の頻度ルールを読み、
   **「直近の“実行すべきだった予定時刻”が、まだ実行されていないか」を判定**します。
   未実行の回があれば本番実行し、実行した予定時刻を `data/last_run.json` に記録します。
   既に実行済みなら何もせず終了します。

これにより「第1営業日だけ」「隔週月曜だけ」といった細かい頻度も、
タスクは毎日起動しつつ実際の実行日はツール側で正しく制御されます。

### なぜ「今日が対象日か」判定をやめたか（重要な修正）

旧方式は「起動された日が対象曜日／対象日か」を `date.today()` で判定していました。
ところがスリープで起動時刻を逃すと、Windows の取り残し実行（StartWhenAvailable）は
**日付が変わってから**発火します。例：**月曜13:00にスリープ→火曜に起動**されると、
`date.today()` は火曜なので「対象日ではない」と誤判定し、**タスク履歴上は成功(0)なのに
データが作られない**事故が起きていました（=「実行されたことになっているのにデータが無い」）。

新方式は日付ではなく**「予定時刻ベースの未実行チェック」**にしたため、
起動日がずれても取り残した回を確実に実行し、かつ二重実行も起こしません。

- **キャッチアップ猶予**：`schedule.json` の `catch_up_days`（既定 **7日**）。
  取り残した回がこれより古い場合のみスキップします（0以下で無制限）。
  週次より長い頻度（毎月など）で長期間PCを止める運用では、この値を大きめにしてください。

---

## 2. 事前準備

- `python src\diag_connection.py` で接続がOKになっていること
  （SSL対応 `truststore` 導入済み。引き継ぎ指示書 §3 参照）。
- `config\schedule.json` が用意されていること（次の 3. で作成）。

---

## 3. 手順

### 3-1. スケジュール設定ファイル `config/schedule.json` を作る

**方法A（推奨）：GUIから保存**

1. `monitoring_gui.bat` を起動。
2. 「観測するLLM」「実行モード＝自動実行」「実行頻度」「時刻」「質問セット」等を設定。
3. 画面下部の **「💾 この設定をOS自動実行として保存」** を押す。
   → `config/schedule.json` が生成され、次回予定と登録手順が表示されます。

**方法B：ひな形をコピーして編集**

`config/schedule.json.example` を `config/schedule.json` にコピーして編集します。

```json
{
  "enabled": true,
  "anchor": "2026-08-05",
  "rule": { "kind": "first_business_day", "time": "09:00" },
  "plan": {
    "models": ["claude-sonnet-5"],
    "question_set": "set1",
    "domain": null,
    "repeat": { "type": "once" },
    "mode": "auto"
  },
  "dry_run": false
}
```

- `rule.kind`：`every_n_days` / `weekly` / `biweekly` / `monthly_day` /
  `nth_weekday` / `nth_business_day` / `first_business_day` / `last_business_day`
- `rule.time`：実行時刻（タスクの起動時刻と揃えます。3-2で自動的に揃います）。
- `plan.repeat`：`{"type":"once"}`（1回）または
  `{"type":"interval","interval_minutes":10,"count":3}`（10分おきに3回＝ブレ測定）。

### 3-2. 判定を事前確認（任意・おすすめ）

実行はせず「今日は対象日か」「次回はいつか」だけ確認できます。

```bash
run_scheduled.bat --check
```

### 3-3. Windows タスクとして登録

`monitoring` フォルダの **`register_scheduled_task.bat` をダブルクリック**します。

- 既定：**毎日 09:00 起動**（`schedule.json` の `rule.time` に自動追従）／
  タスク名 `GEO_AI_Monitoring` ／ **ログオン中のみ実行**。
- 起動時刻を変えたい場合（コマンドプロンプトから）:

  ```bash
  register_scheduled_task.bat -Time "07:30"
  ```

- **ログオフ中でも実行**したい場合（※管理者権限が必要な場合あり）:

  ```bash
  register_scheduled_task.bat -WhetherLoggedOnOrNot
  ```

登録が成功すると「次回起動予定」が表示されます。

### 3-4. すぐに動作テスト

登録後、実際に1回動かして確認します（対象日でなくても強制実行）。

```bash
run_scheduled.bat --force --dry-run
```

- `--force`：対象日判定を無視して実行。
- `--dry-run`：API課金なしで動作だけ確認。
- 本番で1回試すなら `--dry-run` を外す：`run_scheduled.bat --force`

タスク経由のテストは PowerShell から:

```powershell
Start-ScheduledTask -TaskName GEO_AI_Monitoring
Get-ScheduledTaskInfo -TaskName GEO_AI_Monitoring   # LastRunTime / LastTaskResult / NextRunTime
```

---

## 4. 停止・変更・解除

| やりたいこと | 操作 |
|---|---|
| 一時的に止める（タスクは残す） | GUIの「OS自動実行を無効化」ボタン（`schedule.json` の `enabled:false`）。 |
| 頻度・モデルを変える | GUIで再設定 → 再度「💾 保存」。**起動時刻を変えた場合は 3-3 を再実行**。 |
| タスクごと削除する | `unregister_scheduled_task.bat` をダブルクリック。 |

---

## 5. ログの確認

- 実行ログは **`data/run_log.txt`** に追記されます（対象外でスキップした記録も残ります）。
- 実行結果（CSV/レポート/ダッシュボード）は通常どおり `data/` に保存され、
  `data/dashboard.html` も自動再生成されます。

---

## 6. トラブルシューティング

- **実行された形跡がない**
  - `data/run_log.txt` を確認（「消化済みです」「まだ実行予定がありません」なら仕様どおり）。
  - `Get-ScheduledTaskInfo -TaskName GEO_AI_Monitoring` の `LastTaskResult`（0 が成功）。
  - PCがその時刻に**シャットダウンしていなかったか**（電源OFFでは動きません）。
- **タスク履歴は「成功」なのに `data/results` にデータが無い**
  - 本改修（デイリーゲート＋キャッチアップ）で解消済みです。反映するには
    最新の `src/run_scheduled.py`・`tools/register_scheduled_task.ps1` に更新し、
    **`register_scheduled_task.bat` を再実行してタスクを登録し直して**ください
    （スリープ復帰トリガー／スリープ解除タイマー有効化が入ります）。
  - 現状を確認：`run_scheduled.bat --check`（「未消化 → 今起動すれば実行する／消化済み」を表示）。
- **スリープ中に自動復帰しない**
  - 電源オプションで「**スリープ解除タイマーの許可**」が**有効**か確認
    （`register_scheduled_task.bat` が自動有効化しますが、企業ポリシーで戻る場合あり）。
  - PCが**休止(S4)**や**ハイブリッドスリープ**だと `-WakeToRun` は効きません。この場合でも、
    次に手動でPCを起こせば**復帰トリガー＋キャッチアップ**で取り残した回を実行します。
- **`Python(Anaconda) が見つかりません`**
  - `run_scheduled.bat` は `C:\work\anaconda_install\python.exe` 等を自動探索します。
    別の場所にある場合は Anaconda Prompt から
    `cd /d <monitoringフォルダ>` → `python src\run_scheduled.py --check` で確認。
- **接続エラー（Connection error / SSL）**
  - `pip install -r requirements.txt`（`truststore` 導入）後、
    `python src\diag_connection.py` で成功を確認（引き継ぎ指示書 §3）。
- **登録時に「アクセスが拒否されました」**
  - PowerShell を「管理者として実行」して
    `tools\register_scheduled_task.ps1` を実行。特に `-WhetherLoggedOnOrNot` は要管理者。

---

## 7. 関連ファイル

```
monitoring/
├─ run_scheduled.bat                 ヘッドレス実行ランチャー（タスクから起動）
├─ register_scheduled_task.bat       タスク登録（ダブルクリック）
├─ unregister_scheduled_task.bat     タスク解除（ダブルクリック）
├─ config/schedule.json(.example)    OS常駐スケジュール設定（.jsonは各自ローカル。catch_up_days対応）
├─ data/last_run.json                最後に消化した予定時刻の記録（キャッチアップ判定用・自動生成）
├─ tools/
│   ├─ register_scheduled_task.ps1   タスク登録の本体（PowerShell。毎日＋スリープ復帰トリガー／解除タイマー有効化）
│   └─ unregister_scheduled_task.ps1 タスク解除の本体（PowerShell）
└─ src/run_scheduled.py              予定時刻ベースのキャッチアップ判定＋本番実行のヘッドレス処理
```
