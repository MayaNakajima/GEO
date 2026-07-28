# 生成AI出現モニタリング システム仕様まとめ
## 株式会社オンワードコーポレートデザイン

作成日：2026年7月9日
更新日：2026年7月14日（v5：観測LLMの選択機能を追加）

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

## 3. 質問分類フレームワーク（3軸）

### 軸A：質問タイプ（検索意図）

| コード | タイプ |
|---|---|
| A1 | 業者・サービス推薦型 |
| A2 | 課題解決型 |
| A3 | 比較・選定型 |
| A4 | トレンド・市場情報型 |
| A5 | 事例・実績型 |
| A6 | 企業情報直接型 |
| A7 | ABM横断型（複数事業一括・長期パートナー） |

### 軸B：ステークホルダー

| コード | 対象 |
|---|---|
| B1 | 企業の総務・購買担当者 |
| B2 | 経営者・ブランドマネージャー（CDO/CMO含む） |
| B3 | マーケティング・販促担当者 |
| B4 | 大企業の複数事業担当窓口（ABM文脈） |
| B5 | 学校の教務担当・事務局・学校長 |
| B6a | 病院の院長・理事長・会長（経営者） |
| B6b | 病院の看護部長・副看護部長 |
| B6c | 病院の購買・調達担当者 |
| B7a | クリニック院長・開業医（ECサイト向け） |
| B7b | 個人購入者（看護師個人など） |
| B8 | 投資家・ESG担当者・メディア |
| B9 | 就職活動学生・転職希望者 |

### 軸C：事業ドメイン

| コード | 事業名 | 質問数 | 観測URL |
|---|---|---|---|
| C1 | オリジナルユニフォーム | 12問 | onward-cd.co.jp + uniform.onward-cd.co.jp |
| C2 | スクール（学生服） | 10問 | onward-cd.co.jp + school.onward-cd.co.jp |
| C3 | メディカルウェア（病院） | 12問 | onward-cd.co.jp + medical.onward-cd.co.jp |
| C3-EC | メディカルウェア（EC） | 8問 | onward-raffiria.shop + onward-cd.co.jp |
| C4 | インサイトセールス | 10問 | onward-cd.co.jp + solution.onward-cd.co.jp |
| C5 | コーポレート | 8問 | onward-cd.co.jp |
| C6 | 空間ビジネス（全事業共通） | 10問 | onward-cd.co.jp |
| C7 | ABM横断（複数事業クロス） | 8問 | onward-cd.co.jp |
| **合計** | | **78問** | |

---

## 4. 使用LLMモデル（4モデル）

| モデル | モデルID | API提供元 | 既定 | 月額コスト目安（1USD=161円） |
|---|---|---|---|---|
| GPT-4o | `gpt-4o` | OpenAI | 有効 | 約66円 |
| Gemini 1.5 Pro | `gemini-1.5-pro` | Google | 有効 | 約34円（無料枠内の可能性あり） |
| Perplexity Sonar Pro | `sonar-pro` | Perplexity | 有効 | 約113円 |
| Claude Sonnet | `claude-sonnet-4-6` | Anthropic | 有効 | 約98円 |
| Grok 3 | `grok-3` | xAI | 無効 | （参考・既定では実行対象外） |
| **4モデル合計** | | | | **約310円/月**（月1回実行の場合） |

月次APIコール数（全モデル実行時）：78問 × 4モデル = **312コール/月**

> **観測LLMは実行時に選択できます（v5で追加）。** 詳細は「10. 実行コマンド」を参照。
> 特定のモデルだけを実行すればコール数・コストはその分だけになります（例：GPT-4oのみ＝78コール）。
> モデルの有効／無効の既定値は `config/models.json` の `enabled` で管理します。

---

## 5. 出現判定ロジック

以下のいずれかが回答中に含まれれば「出現あり」と判定する。

**① 一次キーワード（社名）**
- `オンワードコーポレートデザイン`
- `Onward Corporate Design`

**② 二次キーワード（ブランド名）**
- `Raffiria` / `ラフィーリア` / `オンワードCD`

**③ ドメイン別URL**
- 質問のドメイン（C1〜C7）に対応する2つのURLを検出
- C6（空間ビジネス）はコーポレートサイトのみ

---

## 6. 計測指標

| 指標 | 内容 |
|---|---|
| 全体出現率 | 出現した回答数 ÷ 総質問数 × 100（%） |
| 事業別出現率 | C軸（8ドメイン）ごとの出現率 |
| モデル別出現率 | 実行したLLMごとの出現率 |
| 質問タイプ別出現率 | A軸（7タイプ）ごとの出現率 |
| 言及ポジション | AIの推薦リストで何番目に登場したか |
| ABMスコア | C7（ABM横断）質問の出現率 |
| 空間ビジネス出現率 | C6質問の出現率 |
| ECサイト出現率 | C3-EC質問の出現率 |

> ※ 特定モデルのみ実行した場合、モデル別出現率は実行したモデルについてのみ集計されます。
> 月次で比較する際は、同じモデルセットで実行することを推奨します。

---

## 7. 出力ファイル

| ファイル | 場所 | 内容 |
|---|---|---|
| results_YYYY-MM-DD.csv | data/results/ | Excel分析用・回答全文保存・UTF-8 BOM |
| log_YYYY-MM-DD.jsonl | data/logs/ | 全APIコールの完全ログ（1行1JSON） |
| report_YYYY-MM-DD.json | data/reports/ | 月次サマリー（各出現率・統計） |
| run_log.txt | data/ | 実行ログ（自動実行時のエラー確認用） |

CSVの主な列：実行日時・質問ID・事業ドメイン・質問タイプ・ステークホルダー・モデル名・質問文・**回答全文**・出現判定・掲載順位・検出キーワード・検出URL・文脈スニペット

---

## 8. 通知

実行完了後、**Microsoft Teams**にAdaptive Card形式で自動通知。
通知内容：全体出現率・ABMスコア・空間ビジネス出現率・ECサイト出現率・事業別出現率・モデル別出現率・質問タイプ別出現率

---

## 9. フォルダ構成

```
monitoring/
├── monitoring_run.bat      ← 【手動】ダブルクリックで実行。観測LLMを選ぶメニューが表示される
├── monitoring_run_all.bat  ← 【自動】全モデル実行。タスクスケジューラ登録用（メニューなし）
├── .env                    ← APIキー記入（自分で作成／BOXには載せない）
├── .env.example            ← APIキーの記入テンプレート
├── requirements.txt        ← 必要パッケージ一覧
├── config/
│   ├── questions.json          ← 78問（テキストエディタで編集可）
│   ├── models.json             ← 使用モデル・パラメータ・有効/無効
│   └── detection_keywords.json ← 検出キーワード・URL
├── src/
│   ├── runner.py           ← メイン実行スクリプト（モデル選択ロジックを含む）
│   ├── llm_client.py       ← LLM API呼び出し
│   ├── detector.py         ← 出現判定
│   ├── logger.py           ← CSV + JSONL保存
│   └── reporter.py         ← レポート生成・Teams通知
└── data/
    ├── results/            ← CSVファイル
    ├── logs/               ← JSONLフルログ
    └── reports/            ← 月次サマリーJSON
```

---

## 10. 実行コマンド

### 10-1. バッチファイル（推奨・パス設定不要）

| ファイル | 用途 | 動作 |
|---|---|---|
| `monitoring_run.bat` | 手動実行 | ダブルクリックすると観測LLMの選択メニューが表示され、選んだモデルだけで実行 |
| `monitoring_run_all.bat` | 自動実行 | メニューを出さず全有効モデルを実行。タスクスケジューラ登録用 |

`monitoring_run.bat` 実行時の選択メニュー例：

```
観測する LLM を選択してください:
  1) GPT-4o
  2) Gemini 1.5 Pro
  3) Perplexity Sonar Pro
  4) Claude Sonnet
  a) 全て（4 モデル）

  複数選択はスペースまたはカンマ区切り（例: 1 3 / 1,3）
  Enter のみ、または a で全モデル

選択 >
```

### 10-2. コマンドライン（上級者・自動化向け）

```bash
# 対話メニューでモデルを選択（端末から引数なしで実行した場合）
python src/runner.py

# 全有効モデルを実行（メニューを表示しない）
python src/runner.py --all

# 特定モデルのみ実行（モデルIDをカンマ区切り）
python src/runner.py --models gpt-4o
python src/runner.py --models gpt-4o,sonar-pro

# モデル名でも指定可能（大文字小文字・スペース可）
python src/runner.py --models "Claude Sonnet"

# 特定事業ドメインのみ実行（テスト向け・モデル選択と併用可）
python src/runner.py --domain C5 --models gpt-4o

# API呼び出しなしで動作確認（モデル選択と併用可）
python src/runner.py --dry-run --all
```

**指定できるモデルID**：`gpt-4o` / `gemini-1.5-pro` / `sonar-pro` / `claude-sonnet-4-6` / `grok-3`

> - `--models` に存在しないモデルを指定した場合は警告のうえ無視します。有効な指定が1つもなければ実行を中止します。
> - `--models` で `grok-3` のように既定で無効なモデルを指定すると、そのモデルも実行対象にできます。
> - 引数なし・かつ非対話環境（タスクスケジューラ等）で実行した場合は、従来どおり全有効モデルを実行します（後方互換）。

---

## 11. 自動化までのステップ

| ステップ | 作業 |
|---|---|
| 1 | monitoringフォルダをBOXに格納（`.env`は載せない。詳細は下記「BOX格納時の注意」） |
| 2 | Pythonをインストール（python.org） |
| 3 | `pip install -r requirements.txt` を実行 |
| 4 | 各APIキーを取得し`.env`ファイルを作成 |
| 5 | Teams Incoming WebhookのURLを`.env`に設定 |
| 6 | `python src/runner.py --dry-run --all` で動作確認 |
| 7 | `monitoring_run.bat` をダブルクリック → 1つのモデルを選んで本番テスト |
| 8 | Windowsタスクスケジューラに **`monitoring_run_all.bat`** を登録（全モデル自動実行） |

> **注意：** タスクスケジューラには必ず `monitoring_run_all.bat`（全モデル・メニューなし）を登録してください。
> `monitoring_run.bat`（対話メニュー版）を登録すると、入力待ちで処理が止まります。

---

## 12. 質問リストの変更方法

`config/questions.json`をテキストエディタで直接編集するだけで、コード変更不要で質問の追加・変更・削除が可能。バージョン管理として`questions_v2.json`のように版管理すると変更前後の比較に役立つ。

---

## 13. BOX格納時の注意

monitoringフォルダ配下を格納する際は、**以下を除外**することを推奨します。

| 対象 | 理由・扱い |
|---|---|
| `.env` | **APIキー・Teams WebhookのURLを含む機密ファイル。共有ドライブに載せない。** 各実行環境でローカルに作成する（`.env.example`をテンプレートとして格納すればOK） |
| `src/__pycache__/`・`*.pyc` | Pythonの自動生成キャッシュ。不要（削除しても問題なし） |
| `data/run_log.txt` | 実行環境ごとのログ。任意（載せても害はないが必須ではない） |

**格納してよいもの（システム本体）**：`monitoring_run.bat`／`monitoring_run_all.bat`／`requirements.txt`／`.env.example`／`config/`（各JSON）／`src/`（各.py）。

**`data/results`・`data/logs`・`data/reports` の扱い**：
過去の計測結果を残して推移を追いたい場合は含めて格納します。BOXを配布用テンプレートとして使う場合は、これらは空にしておくと軽量になります。

---

*詳細設計：AI_Citation_Monitoring_Design_v3.md 参照*
*変更履歴：v5（2026-07-14）観測LLMの選択機能を追加。バッチを手動用／自動用の2種に分割。*
