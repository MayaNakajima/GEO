# 生成AI出現モニタリング システム仕様まとめ
## 株式会社オンワードコーポレートデザイン

作成日：2026年7月9日

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

| モデル | API提供元 | 月額コスト目安（1USD=161円） |
|---|---|---|
| GPT-4o | OpenAI | 約66円 |
| Gemini 1.5 Pro | Google | 約34円（無料枠内の可能性あり） |
| Perplexity Sonar Pro | Perplexity | 約113円 |
| Claude Sonnet | Anthropic | 約98円 |
| **4モデル合計** | | **約310円/月**（月1回実行の場合） |

月次APIコール数：78問 × 4モデル = **312コール/月**

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
| モデル別出現率 | 4LLMごとの出現率 |
| 質問タイプ別出現率 | A軸（7タイプ）ごとの出現率 |
| 言及ポジション | AIの推薦リストで何番目に登場したか |
| ABMスコア | C7（ABM横断）質問の出現率 |
| 空間ビジネス出現率 | C6質問の出現率 |
| ECサイト出現率 | C3-EC質問の出現率 |

---

## 7. 出力ファイル

| ファイル | 場所 | 内容 |
|---|---|---|
| results_YYYY-MM-DD.csv | data/results/ | Excel分析用・回答全文保存・UTF-8 BOM |
| log_YYYY-MM-DD.jsonl | data/logs/ | 全APIコールの完全ログ（1行1JSON） |
| report_YYYY-MM-DD.json | data/reports/ | 月次サマリー（各出現率・統計） |
| run_log.txt | data/ | 実行ログ（エラー確認用） |

CSVの主な列：実行日時・質問ID・事業ドメイン・質問タイプ・ステークホルダー・モデル名・質問文・**回答全文**・出現判定・掲載順位・検出キーワード・検出URL・文脈スニペット

---

## 8. 通知

実行完了後、**Microsoft Teams**にAdaptive Card形式で自動通知。
通知内容：全体出現率・ABMスコア・空間ビジネス出現率・ECサイト出現率・事業別出現率・モデル別出現率・質問タイプ別出現率

---

## 9. フォルダ構成

```
monitoring/
├── monitoring_run.bat      ← ダブルクリックで実行（パス設定不要）
├── .env                    ← APIキー記入（自分で作成）
├── .env.example            ← APIキーの記入テンプレート
├── requirements.txt        ← 必要パッケージ一覧
├── config/
│   ├── questions.json          ← 78問（テキストエディタで編集可）
│   ├── models.json             ← 使用モデル・パラメータ
│   └── detection_keywords.json ← 検出キーワード・URL
├── src/
│   ├── runner.py           ← メイン実行スクリプト
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

```bash
# 全質問・全モデルを実行（月次本番）
python src/runner.py

# 特定事業ドメインのみ実行（テスト向け）
python src/runner.py --domain C5

# API呼び出しなしで動作確認
python src/runner.py --dry-run
```

---

## 11. 自動化までのステップ

| ステップ | 作業 |
|---|---|
| 1 | monitoringフォルダをBOXに格納 |
| 2 | Pythonをインストール（python.org） |
| 3 | `pip install -r requirements.txt` を実行 |
| 4 | 各APIキーを取得し`.env`ファイルを作成 |
| 5 | Teams Incoming WebhookのURLを`.env`に設定 |
| 6 | `python src/runner.py --dry-run` で動作確認 |
| 7 | `python src/runner.py --domain C5` で本番テスト（32コール） |
| 8 | Windowsタスクスケジューラに`monitoring_run.bat`を登録 |

---

## 12. 質問リストの変更方法

`config/questions.json`をテキストエディタで直接編集するだけで、コード変更不要で質問の追加・変更・削除が可能。バージョン管理として`questions_v2.json`のように版管理すると変更前後の比較に役立つ。

---

*詳細設計：AI_Citation_Monitoring_Design_v3.md 参照*
