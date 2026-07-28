# 生成AI出現モニタリング システム仕様書（総合版）
## 株式会社オンワードコーポレートデザイン

作成日：2026年7月9日
更新日：2026年7月27日（**v7：質問セット選択（Set1/Set2/両方）・特異度ティア・CSV列追加**）
前版：2026年7月16日（v6：GUI実行コンソール・柔軟な実行スケジュール・3層レポート）

---

## 0. v7 での主な変更点（2026-07-27）

- **質問セットを選べるようになりました。** 従来の78問（**Set 1**）に加え、当社が出現しやすい設問を診断する新セット **Set 2（60問）** を追加。GUI／CLIで **Set1 / Set2 / 両方** を選択して実行できます。
- **Set 2 は「特異度グラデーション」設計**（D1指名／D2業種特化・実績／D3高特異度・非指名／D4一般需要）。5ドメイン（C1ユニフォーム・C3メディカル・C4インサイトセールス・C5コーポレート・**C7 ABM横断・コトデザイン**）× 各12問。
- **結果CSVに2列を追加**：`question_set`（set1/set2）・`specificity_tier`（D1〜D4／set1は空欄）。**既存列の順序・内容は不変**（末尾に追加）なので、Set 1の実行結果は従来と同一。
- **検出設定の不整合を修正**：`detection_keywords.json` の `domain_urls` でC1にuniform、C2にschool、C4にsolution等が正しく対応するよう修正。
- **分析・ダッシュボードが特異度ティア／質問セットに対応**：集計に `set_rates`・`tier_rates`（Tier1）、`set_stats`・`tier_stats`（Tier2）、`tier_series`・`set_series`（Tier3）を追加。HTMLダッシュボードに「特異度ティア別 出現率（D1→D4・崖の可視化）」「質問セット別 出現率」チャートと、**崖の位置を自動指摘する示唆**を追加。
- 設問ファイル：Set 1＝`config/questions.json`（無改変）、Set 2＝`config/questions_set2.json`（新規）。
- 詳細設計：`AI_Citation_Monitoring_QuestionSet2_設計_v1.md`、設問全文：`設問一覧_Set1_Set2_確認用.md`。

---

## 0-1. v6 での主な変更点

- **GUI（ブラウザ画面）から実行できるようになりました。** `monitoring_gui.bat` をダブルクリックするとローカルWebサーバが起動し、ブラウザで「実行コンソール」が開きます。
- **観測LLMを画面で選択可能**（複数選択・単一選択どちらも可）。
- **手動実行 / 自動実行（定期）を選択可能。** 開始タイミング（すぐ／●分後）、繰り返し（1回のみ／●分おきに〇回）、自動実行の頻度（●日おき・毎週・隔週・毎月・第◆曜日・第□営業日・月初/月末営業日 など）を柔軟に設定できます。
- **レポートを3層に刷新**（1回ごと／1タイミングごと＝ブレ分析／複数タイミング＝時系列トレンド・示唆）。HTMLダッシュボード・JSON・rowデータCSVエクスポートに対応。
- **現在の稼働モデルは Claude のみ**（Claude Sonnet 5）。他LLMはキー設定後に有効化予定。

> 従来のコマンドライン実行（`monitoring_run.bat` / `python src/runner.py`）も引き続き利用できます。

---

## 1. システムの目的

生成AI（ChatGPT・Gemini・Claude・Perplexity）が業務課題を問われた際に、**オンワードコーポレートデザインが回答に出現するか**を定量的・継続的に計測する。

| 戦略目標 | 内容 |
|---|---|
| GEO（生成AI最適化） | AIに推薦される企業としての認知向上 |
| ABM最適化 | 事業横断のLTV向上に向けたターゲット出現状況の把握 |
| コト提供シフトの評価 | 「顧客ブランド支援」の文脈で出現できているかの検証 |

---

## 2. 観測対象サイト

| サイト | URL |
|---|---|
| コーポレート | onward-cd.co.jp |
| ユニフォーム | uniform.onward-cd.co.jp |
| スクール | school.onward-cd.co.jp |
| メディカル（病院） | medical.onward-cd.co.jp |
| インサイトセールス | solution.onward-cd.co.jp |
| メディカルEC（別計測） | onward-raffiria.shop |

---

## 3. 質問分類フレームワーク（3軸・78問）

- **軸A：質問タイプ** A1業者推薦／A2課題解決／A3比較選定／A4トレンド／A5事例実績／A6企業情報／A7 ABM横断
- **軸B：ステークホルダー** 総務購買・経営者・販促・ABM窓口・学校・病院（院長/看護部長/購買）・クリニック・個人・投資家・就活 等
- **軸C：事業ドメイン** C1ユニフォーム(12) / C2スクール(10) / C3メディカル病院(12) / C3-ECメディカルEC(8) / C4インサイトセールス(10) / C5コーポレート(8) / C6空間ビジネス(10) / C7 ABM横断(8)　＝**合計78問**

質問は `config/questions.json` をテキストエディタで編集するだけで変更可能（コード変更不要）。

### 3-1. 質問セット2（Set 2・60問）★v7

Set 1が「出したいのに出ない」理想ターゲット質問なのに対し、Set 2は「当社が出現しやすい／出現の閾値を測る」診断用セット。**特異度グラデーション**（D1指名→D2業種特化・実績→D3高特異度・非指名→D4一般需要）を軸に、5ドメイン（C1/C3/C4/C5＋**C7 ABM横断・コトデザイン**）× 各12問（D1:2・D2:4・D3:4・D4:2）。
`config/questions_set2.json` で管理。各質問は `question_set`（"set2"）と `specificity_tier`（D1〜D4）を持つ。実行時にSet1/Set2/両方を選択可能（§6・§11）。

---

## 4. 使用LLMモデル（実行時に選択可能）

| モデル | モデルID | API提供元 | 現在の状態 |
|---|---|---|---|
| **Claude Sonnet 5** | `claude-sonnet-5` | Anthropic | **稼働中（キー設定済）** |
| GPT-4o | `gpt-4o` | OpenAI | 今後対応（キー未設定・無効） |
| Gemini 1.5 Pro | `gemini-1.5-pro` | Google | 今後対応（キー未設定・無効） |
| Perplexity Sonar Pro | `sonar-pro` | Perplexity | 今後対応（キー未設定・無効） |
| Grok 3 | `grok-3` | xAI | 参考（任意） |

- 実行時に観測するモデルをGUIで選択します（複数可）。既定でチェックされるのは `config/models.json` で `enabled:true` のモデル（現在は Claude のみ）。
- 他モデルを有効化するには、`.env` に各APIキーを設定し、`config/models.json` の該当モデルを `"enabled": true` にします。
- コスト目安（1回=78問、1USD=161円）：Claude単体で約98円/回。全4モデルで約310円/回。

---

## 5. 出現判定ロジック

以下のいずれかが回答中に含まれれば「出現あり」と判定する。

- **① 社名**：`オンワードコーポレートデザイン` / `Onward Corporate Design`
- **② ブランド名**：`Raffiria` / `ラフィーリア` / `オンワードCD`
- **③ ドメイン別URL**：質問ドメイン（C1〜C7）に対応するURLを検出（C6はコーポレートサイトのみ）

検出キーワード・URLは `config/detection_keywords.json` で管理。

---

## 6. 実行方法（GUI 実行コンソール）★v6

`monitoring_gui.bat` をダブルクリック → ローカルWebサーバ起動 → ブラウザで実行コンソールが開く。

画面で設定できる項目：

1. **観測するLLM**：チェックボックスで選択（全選択／全解除ボタンあり）。
2. **実行モード**：手動実行／自動実行（定期）。
3. **開始タイミング**：すぐ実行／●分後に実行。
4. **繰り返し（1タイミング内）**：1回のみ／●分おきに〇回。
5. **実行頻度（自動実行時）**：下表のルールから選択（次回予定日時のプレビュー表示付き）。
6. **オプション**：**質問セット（Set1／Set2／両方）★v7**、ドライラン（API呼び出しなし）、事業ドメイン絞り込み。

> **自動実行は「GUI常駐型」です。** この画面（黒いウィンドウ＝サーバ）を起動している間だけ自動実行が有効です。ウィンドウを閉じると自動実行は停止します。PCを起動したままにしておく運用を想定しています。

### 6-1. 実行頻度ルール（自動実行）

| ルール | 説明 | 設定項目 |
|---|---|---|
| ●日おき | N日ごと（毎日=1） | 日数・時刻 |
| 毎週・毎〇曜日 | 指定曜日（複数可）に毎週 | 曜日・時刻 |
| 隔週 | 指定曜日で1週おき | 曜日・時刻 |
| 毎月〇日 | 毎月の指定日（月末に自動丸め） | 日・時刻 |
| 第◆曜日 | 第1〜第5／最終の指定曜日 | 第N・曜日・時刻 |
| 毎月 第□営業日 | その月の第N営業日 | 第N・時刻 |
| 月初 第1営業日 | 各月の最初の営業日 | 時刻 |
| 月末 最終営業日 | 各月の最後の営業日 | 時刻 |

- **「営業日」の定義**：平日（月〜金）かつ日本の祝日でない日。祝日判定は `jpholiday` ライブラリを使用（未インストール時は土日のみ除外に自動フォールバック。GUI上部に現在の判定方式を表示）。

---

## 7. レポート（3層構造）★v6

分析の重点：**①応答の安定性（ブレ）／②時系列トレンド／③施策への示唆**。

### Tier1：1回ごと（per-run）
1回の実行（78問×選択モデル）の結果。全体出現率、モデル別・事業別・質問タイプ別出現率、出現上位事例。
→ `data/reports/report_<run_id>.json`、`data/results/results_<run_id>.csv`

### Tier2：1タイミングごと（per-timing・ブレ分析）
同一タイミングで **M回** 実行した結果をまとめて分析。
- 全体出現率の **平均 ± 標準偏差（SD）**、最小〜最大
- **質問×モデル単位の出現回数（0〜M回）** → 毎回ブレる質問（安定して出現していない質問）を可視化
- **安定性スコア**（毎回同じ結果だったセルの割合％）
- モデル別・事業別の平均±SD
→ `data/reports/timing_<timing_id>.json`
- ※ M=1（1回のみ）ではブレは測定できません。ブレを見るには2回以上の実行が必要です。

### Tier3：複数タイミング（cross-timing・トレンド／比較／示唆）
タイミングをまたいだ推移を分析。
- **全体出現率の時系列**（平均±SDの帯グラフ）、モデル別・事業別の推移
- **前回比／初回比**の差分、事業ドメイン別の変動（movers）
- **施策への示唆（自動生成）**：コンテンツ空白（低出現ドメイン）、あと一歩（ブレている質問＝ページ改善で安定出現を狙える）、低下／改善ドメイン
→ `data/reports/trend.json`

### 出力形式
- **HTMLダッシュボード**：`data/dashboard.html`（グラフ付き・自己完結。GUIの「ダッシュボードを開く」または直接ブラウザで開く）
- **JSON**：上記の各レポートファイル
- **rowデータCSVエクスポート**：GUIから全データ／タイミング単位でCSV出力（回答全文・検出情報を含む、UTF-8 BOM）
- **Teams通知（任意）**：`.env` に `TEAMS_WEBHOOK_URL` を設定した場合、タイミング完了時にAdaptive Cardで自動通知（未設定ならスキップ）

---

## 8. 計測指標

全体出現率／事業別出現率／モデル別出現率／質問タイプ別出現率／言及ポジション／ABMスコア（C7）／空間ビジネス出現率（C6）／ECサイト出現率（C3-EC）／**安定性スコア・SD（ブレ）★v6**／**前回比・初回比（トレンド）★v6**／**特異度ティア別出現率（D1〜D4・崖の可視化）★v7**／**質問セット別出現率（Set1/Set2）★v7**。

---

## 9. 出力ファイル

| ファイル | 場所 | 内容 |
|---|---|---|
| results_<run_id>.csv | data/results/ | 1回分の回答全文・検出結果（Excel分析用・UTF-8 BOM）。**★v7で `question_set`・`specificity_tier` の2列を末尾に追加**（既存列は不変） |
| log_<run_id>.jsonl | data/logs/ | 1回分の完全ログ（1行1JSON） |
| report_<run_id>.json | data/reports/ | Tier1（1回ごと）レポート |
| timing_<timing_id>.json | data/reports/ | Tier2（1タイミング・ブレ分析）レポート |
| trend.json | data/reports/ | Tier3（横断トレンド・示唆） |
| index.json | data/reports/ | タイミング一覧（履歴） |
| dashboard.html | data/ | HTMLダッシュボード |
| run_log.txt | data/ | 実行ログ（CLI自動実行時のエラー確認用） |

- `run_id` = `<timing_id>_r<回番号>`（例：`20260716_090000_r1`）、`timing_id` = 実行時点（`YYYYMMDD_HHMMSS`）。

---

## 10. フォルダ構成

```
monitoring/
├── monitoring_gui.bat        ★v6 GUI実行コンソールを起動（推奨）
├── monitoring_run.bat        CLI：対話メニューで手動実行
├── monitoring_run_all.bat    CLI：全有効モデルで自動実行（タスクスケジューラ用）
├── data_reset.bat            ★v6 テスト/過去データの初期化
├── .env                      APIキー等（機密・BOX非格納）※Claude設定済
├── .env.example              記入テンプレート
├── requirements.txt          依存パッケージ
├── config/
│   ├── questions.json            Set1・78問
│   ├── questions_set2.json       ★v7 Set2・60問（特異度D1〜D4）
│   ├── models.json               使用モデル・有効/無効
│   └── detection_keywords.json   検出キーワード・URL（★v7 domain_urls不整合を修正）
├── webapp/                   ★v6 GUI画面
│   ├── index.html
│   ├── style.css
│   └── app.js
├── src/
│   ├── webapp.py             ★v6 Webサーバ・API・ジョブ管理
│   ├── engine.py             ★v6 1タイミング実行の統括・3層レポート生成
│   ├── scheduler.py          ★v6 実行頻度ルール・営業日判定・次回算出
│   ├── analytics.py          ★v6 Tier2/Tier3 集計・ブレ/トレンド/示唆
│   ├── dashboard.py          ★v6 HTMLダッシュボード生成
│   ├── reset_data.py         ★v6 データ初期化
│   ├── runner.py             コアループ（run_pass）・CLIエントリ
│   ├── llm_client.py         LLM API呼び出し
│   ├── detector.py           出現判定
│   ├── logger.py             CSV/JSONL保存
│   └── reporter.py           Tier1レポート・Teams通知
└── data/
    ├── results/  ├── logs/  ├── reports/   （+ dashboard.html）
```

---

## 11. 起動方法・コマンド

### 11-1. GUI（推奨）
`monitoring_gui.bat` をダブルクリック → ブラウザで実行コンソール。手動/自動・モデル・頻度を画面で設定。

### 11-2. コマンドライン（従来通り・自動化/上級者向け）
```bash
python src/runner.py                       # 対話メニューでモデル選択（既定 Set1）
python src/runner.py --all                 # 全有効モデル（既定 Set1）
python src/runner.py --set set2 --all      # ★v7 Set2（60問）を実行
python src/runner.py --set both --all      # ★v7 Set1+Set2（138問）を実行
python src/runner.py --models claude-sonnet-5   # 特定モデル
python src/runner.py --domain C5           # 事業ドメイン絞り
python src/runner.py --dry-run --all       # 動作確認（API呼び出しなし）
```
- `--set` 省略時は `set1`（従来と同一の後方互換動作）。`--set` は `--domain` と併用可（例：`--set set2 --domain C7`）。
- `monitoring_run.bat`（対話メニュー手動）／`monitoring_run_all.bat`（全モデル自動・タスクスケジューラ用）。

---

## 12. データの初期化

動作確認（ドライラン等）で作成したデータを本番前に一掃するには `data_reset.bat` をダブルクリック（`data/results`・`data/logs`・`data/reports` の生成物と `dashboard.html` を削除。`config`・`.env`・ソースは残る）。
コマンド：`python src/reset_data.py`（`--yes` で確認省略、`--dry` で対象確認のみ）。

---

## 13. 依存パッケージ

`pip install -r requirements.txt`
- LLM：openai / anthropic / google-generativeai
- HTTP：requests、環境変数：python-dotenv
- **営業日判定：jpholiday（任意。未導入でも動作＝土日のみ除外）**
- **GUI（Webサーバ）は Python 標準ライブラリのみで動作（追加不要）**

---

## 14. BOX格納・運用方式

**採用方式：BOX共有フォルダから直接実行（共有キー方式）**
- 配置先：`%USERPROFILE%\Box\事業推進Div□\DX推進課\生成AI\monitoring`（各自のBoxに同期される共通パス）。
- 実行：各メンバーは初回のみ `pip install -r requirements.txt`、以降 `python run.py`（またはショートカット）。
- APIキー：共有フォルダの `.env` に**専用の共有キー**を1本設定して全員で使用。
- `data/`：共有フォルダに保存＝結果を全員で共有（同時実行は競合し得るため実行タイミングは調整）。

**BOXに載せるもの**：各 `.bat`、`run.py`、`requirements.txt`、`.env`（共有キー）、`.env.example`、
`config/`、`webapp/`、`src/`（.py）、各ドキュメント。
**載せない**：`src/__pycache__/`・`*.pyc`（自動生成）。

**セキュリティ注意**：`.env` の共有キーはフォルダ閲覧者全員が見られる。アクセス権を必要メンバーに限定し、
用途専用キーを使用、露出した旧キーは失効・再発行する。

> 別方式（より安全）：`.env` はBOXに置かず、各メンバーがローカルにコピーして自分のキーで実行する
> 運用も可能。セキュリティを重視する場合はこちらを検討。

---

## 変更履歴
- **v7（2026-07-27）**：質問セット選択（Set1／Set2／両方）を追加。Set 2（60問・特異度D1〜D4・5ドメインC1/C3/C4/C5/C7）を新設（`config/questions_set2.json`）。結果CSVに `question_set`・`specificity_tier` の2列を末尾追加（既存列不変＝Set1は従来同一）。GUI（質問セット選択）・CLI（`--set`）・engine/webappを対応。`detection_keywords.json` の `domain_urls` 不整合を修正。分析・ダッシュボードに特異度ティア／質問セット別の集計・チャートを追加。GUIのドメイン絞り込みを質問セットに連動（`/api/domains`）。
  - **不具合修正**：①中断後に状態が「実行中」で固まり再実行できなかった問題を修正（中断後は必ずidleへ戻り「実行する」で再開可能。`run_pass`にも中断チェックを追加し回の途中でも停止可能、途中結果は破棄）。②「全rowデータCSV」エクスポートで新2列が欠落する問題を修正（全ファイルの列和集合でヘッダ確定）。③CLIで存在しないセット×ドメイン指定時に警告。
- **v6（2026-07-16）**：GUI実行コンソール、観測LLMのGUI選択、手動/自動の柔軟なスケジュール（開始タイミング・繰り返し・頻度ルール・営業日判定）、3層レポート（ブレ／トレンド／示唆）、HTMLダッシュボード・CSVエクスポート、データ初期化ユーティリティを追加。稼働モデルをClaude Sonnet 5に設定。
- v5（2026-07-14）：観測LLMの選択機能（CLI）、バッチを手動用/自動用に分割。
- v4以前：基本仕様（4モデル同時・CLI・月次）。

*詳細設計の初版：AI_Citation_Monitoring_Design_v3.md 参照*
