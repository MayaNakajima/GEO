"""
AI Citation Monitoring — メイン実行スクリプト
株式会社オンワードコーポレートデザイン

使い方:
    python src/runner.py                       # 対話メニューでモデルを選択（端末実行時）
    python src/runner.py --all                 # 全有効モデルを実行（メニューなし）
    python src/runner.py --models gpt-4o        # 特定モデルのみ実行
    python src/runner.py --models gpt-4o,sonar-pro  # 複数モデルを実行（カンマ区切り）
    python src/runner.py --domain C3           # 特定事業ドメインのみ実行
    python src/runner.py --dry-run             # API 呼び出しなしで動作確認

    ※ --models はモデルID（gpt-4o / gemini-1.5-pro / sonar-pro /
       claude-sonnet-4-6 / grok-3）またはモデル名で指定可。
    ※ 引数なしで端末から実行した場合は対話メニューを表示。
       引数なし・非対話（スケジューラ等）の場合は全有効モデルを実行（後方互換）。

スケジュール実行（例: 毎月1日 09:00）:
    cron: 0 9 1 * * cd /path/to/monitoring && python src/runner.py --all
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

# プロジェクトルートを基準にパスを解決
BASE_DIR = Path(__file__).parent.parent

sys.path.insert(0, str(Path(__file__).parent))
from envload import load_env
load_env(BASE_DIR / ".env")
from llm_client import LLMClient
from detector   import MentionDetector
from logger     import ResultLogger
from reporter   import ReportGenerator


CONFIG_DIR = BASE_DIR / "config"
DATA_DIR   = BASE_DIR / "data"


# ------------------------------------------------------------------ #
# 質問セット定義
#   set1 : 現行78問（questions.json）
#   set2 : 新規60問（questions_set2.json・特異度D1〜D4）
#   both : set1 + set2（並行）
# ------------------------------------------------------------------ #
QUESTION_SETS = {
    "set1": ["questions.json"],
    "set2": ["questions_set2.json"],
    "both": ["questions.json", "questions_set2.json"],
}


def load_questions(question_set: str = "set1") -> list:
    """
    指定した質問セットの質問リストを読み込む。

    - 各質問に `question_set`（set1/set2）を付与（未設定時のみ）。
    - `specificity_tier`（D1〜D4。set1は空欄）も未設定なら空文字を補完。
    これにより既存の set1（questions.json）は無改変のまま、後段で
    セット・特異度による集計/フィルタが可能になる。
    """
    files = QUESTION_SETS.get(question_set, QUESTION_SETS["set1"])
    questions = []
    for fn in files:
        path = CONFIG_DIR / fn
        if not path.exists():
            print(f"⚠ 質問ファイルが見つかりません: {path}")
            continue
        with open(path, encoding="utf-8") as f:
            qs = json.load(f)
        default_set = "set2" if "set2" in fn else "set1"
        for q in qs:
            q.setdefault("question_set", default_set)
            q.setdefault("specificity_tier", "")
        questions.extend(qs)
    return questions


# ------------------------------------------------------------------ #
# 設定読み込み
# ------------------------------------------------------------------ #
def load_config(question_set: str = "set1"):
    """既定は set1（後方互換：従来と同一の78問を読み込む）。"""
    questions = load_questions(question_set)
    with open(CONFIG_DIR / "models.json",             encoding="utf-8") as f:
        models = json.load(f)["models"]
    with open(CONFIG_DIR / "detection_keywords.json", encoding="utf-8") as f:
        keywords = json.load(f)
    return questions, models, keywords


# ------------------------------------------------------------------ #
# モデル選択
# ------------------------------------------------------------------ #
def _find_model(all_models: list, token: str):
    """モデルID または モデル名（大文字小文字問わず）で 1 件を検索。"""
    t = token.strip().lower()
    for m in all_models:
        if m["id"].lower() == t or m["name"].lower() == t:
            return m
    return None


def _interactive_select(enabled_models: list) -> list:
    """対話メニューで観測するモデルを選択させる。"""
    print("\n観測する LLM を選択してください:")
    for i, m in enumerate(enabled_models, 1):
        print(f"  {i}) {m['name']}")
    print(f"  a) 全て（{len(enabled_models)} モデル）")
    print("\n  複数選択はスペースまたはカンマ区切り（例: 1 3 / 1,3）")
    print("  Enter のみ、または a で全モデル\n")

    raw = input("選択 > ").strip().lower()

    if raw == "" or raw == "a":
        print(f"→ 全 {len(enabled_models)} モデルを実行します。")
        return enabled_models

    selected = []
    for tok in raw.replace(",", " ").split():
        if tok.isdigit():
            idx = int(tok) - 1
            if 0 <= idx < len(enabled_models):
                m = enabled_models[idx]
                if m not in selected:
                    selected.append(m)
            else:
                print(f"  ⚠ 範囲外の番号を無視: {tok}")
        else:
            print(f"  ⚠ 数字以外の入力を無視: {tok}")

    if not selected:
        print("→ 有効な選択がありません。全モデルを実行します。")
        return enabled_models

    print("→ 選択: " + ", ".join(m["name"] for m in selected))
    return selected


def select_models(all_models: list,
                  models_arg: str = None,
                  use_all: bool = False) -> list:
    """
    実行対象モデルを決定する。

    優先順位:
      1. --models 指定 → 指定モデル（enabled でなくても実行対象にできる）
      2. --all 指定    → 全 enabled モデル
      3. 端末（対話可）→ 対話メニュー（enabled モデルから選択）
      4. 非対話        → 全 enabled モデル（後方互換）
    """
    enabled = [m for m in all_models if m["enabled"]]

    # 1. --models（カンマ区切り。モデル名にはスペースを含み得るため , でのみ分割）
    if models_arg:
        wanted = [t.strip() for t in models_arg.split(",") if t.strip()]
        selected = []
        for w in wanted:
            m = _find_model(all_models, w)
            if m is None:
                valid = ", ".join(x["id"] for x in all_models)
                print(f"⚠ モデルが見つかりません: '{w}'  （指定可能: {valid}）")
                continue
            if m not in selected:
                selected.append(m)
        if not selected:
            print("有効なモデルが指定されませんでした。終了します。")
            sys.exit(1)
        return selected

    # 2. --all
    if use_all:
        return enabled

    # 3. 対話メニュー（標準入力が端末の場合のみ）
    if sys.stdin.isatty():
        return _interactive_select(enabled)

    # 4. 非対話・引数なし → 全 enabled（後方互換）
    return enabled


# ------------------------------------------------------------------ #
# 1 パス実行（CLI / GUI 共通のコアループ）
# ------------------------------------------------------------------ #
def run_pass(active_models: list, questions: list, keywords: dict,
             dry_run: bool = False, progress_cb=None, stop_check=None) -> list:
    """
    質問 × モデル を 1 回総当たりし、結果リストを返す（ファイル保存はしない）。

    progress_cb(done:int, total:int, label:str, mark:str) を渡すと
    各クエリ完了ごとに呼び出す（GUI の進捗表示用）。渡さない場合は標準出力に表示。
    stop_check() が True を返すと、その時点で中断し途中までの結果を返す（GUIの中断用）。
    """
    client   = LLMClient()
    detector = MentionDetector(keywords)

    run_date = datetime.now().strftime("%Y-%m-%d")
    total    = len(questions) * len(active_models)
    results  = []
    count    = 0

    for question in questions:
        for model in active_models:
            if stop_check and stop_check():
                return results          # 中断：途中結果を返す
            count += 1
            label = f"[{count:>3}/{total}] {model['name']:<22} | {question['id']}"

            if dry_run:
                results.append(_dummy_result(run_date, question, model))
                if progress_cb:
                    progress_cb(count, total, label, "DRY")
                else:
                    print(f"  DRY  {label}")
                continue

            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            try:
                answer    = client.ask(model, question["question"])
                detection = detector.detect(
                    answer,
                    domain=question["axis_domain"],
                    question=question["question"],
                )
                mark      = "✓" if detection["detected"] else "✗"

                results.append({
                    "run_date":          run_date,
                    "run_timestamp":     ts,
                    "question_id":       question["id"],
                    "question_set":      question.get("question_set", "set1"),
                    "specificity_tier":  question.get("specificity_tier", ""),
                    "axis_domain":       question["axis_domain"],
                    "domain_label":      question["domain_label"],
                    "axis_type":         question["axis_type"],
                    "type_label":        question["type_label"],
                    "axis_stakeholder":  question["axis_stakeholder"],
                    "stakeholder_label": question["stakeholder_label"],
                    "abm_relevant":      question.get("abm_relevant", False),
                    "model_id":          model["id"],
                    "model_name":        model["name"],
                    "question":          question["question"],
                    "answer":            answer,          # 全文保存（切り捨てなし）
                    "mention_detected":  detection["detected"],
                    "mention_position":  detection["position"],
                    "entities_found":    ", ".join(detection["entities"]),
                    "urls_found":        ", ".join(detection["urls_found"]),
                    "context_snippet":   detection["context"],
                    "disclaimer_detected": detection["disclaimer_detected"],
                })
                if progress_cb:
                    progress_cb(count, total, label, mark)
                else:
                    print(f"  → {label} [{mark}]")

            except Exception as e:
                results.append(_error_result(run_date, ts, question, model, str(e)))
                if progress_cb:
                    progress_cb(count, total, label, "ERR")
                else:
                    print(f"  → {label} [ERROR: {e}]")

    return results


# ------------------------------------------------------------------ #
# メイン処理
# ------------------------------------------------------------------ #
def run_monitoring(domain_filter: str = None, dry_run: bool = False,
                   models_arg: str = None, use_all: bool = False,
                   question_set: str = "set1"):
    print(f"\n{'='*60}")
    print(f"  AI 出現モニタリング 開始: {datetime.now():%Y-%m-%d %H:%M}")
    if dry_run:
        print("  ★ DRY-RUN モード（API 呼び出しなし）")
    print(f"{'='*60}\n")

    questions, all_models, keywords = load_config(question_set)
    print(f"質問セット: {question_set} → {len(questions)} 問")

    # ドメインフィルタ
    if domain_filter:
        questions = [q for q in questions if q["axis_domain"] == domain_filter]
        print(f"ドメインフィルタ: {domain_filter} → {len(questions)} 問")
        if not questions:
            avail = sorted({q["axis_domain"] for q in load_questions(question_set)})
            print(f"⚠ 質問セット '{question_set}' にドメイン '{domain_filter}' は存在しません。"
                  f"（利用可能: {', '.join(avail)}）実行する質問がありません。")
            return []

    active_models = select_models(all_models, models_arg=models_arg, use_all=use_all)
    total = len(questions) * len(active_models)
    model_names = ", ".join(m["name"] for m in active_models)
    print(f"\n対象モデル: {model_names}")
    print(f"質問数: {len(questions)} 問 × モデル数: {len(active_models)} = {total} クエリ\n")

    logger   = ResultLogger(
        results_dir = DATA_DIR / "results",
        logs_dir    = DATA_DIR / "logs",
    )
    reporter = ReportGenerator(DATA_DIR / "reports")

    # 1 パス実行（共通ロジック）
    results = run_pass(active_models, questions, keywords, dry_run=dry_run)

    # 保存（CSV + JSONL）
    run_date = datetime.now().strftime("%Y-%m-%d")
    csv_path, jsonl_path = logger.save(results, run_date)

    # レポート生成 & Teams 通知
    report = reporter.generate(results, run_date)
    reporter.notify_teams(report)

    # サマリー表示
    detected_count = sum(1 for r in results if r["mention_detected"])
    overall_rate   = detected_count / len(results) * 100 if results else 0
    print(f"\n{'='*60}")
    print(f"  完了: {datetime.now():%Y-%m-%d %H:%M}")
    print(f"  全体出現率: {overall_rate:.1f}%  ({detected_count}/{len(results)})")
    print(f"  CSV:  {csv_path}")
    print(f"  ログ: {jsonl_path}")
    print(f"{'='*60}\n")

    return results


# ------------------------------------------------------------------ #
# ヘルパー
# ------------------------------------------------------------------ #
def _dummy_result(run_date: str, question: dict, model: dict) -> dict:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return {
        "run_date":          run_date,
        "run_timestamp":     ts,
        "question_id":       question["id"],
        "question_set":      question.get("question_set", "set1"),
        "specificity_tier":  question.get("specificity_tier", ""),
        "axis_domain":       question["axis_domain"],
        "domain_label":      question["domain_label"],
        "axis_type":         question["axis_type"],
        "type_label":        question["type_label"],
        "axis_stakeholder":  question["axis_stakeholder"],
        "stakeholder_label": question["stakeholder_label"],
        "abm_relevant":      question.get("abm_relevant", False),
        "model_id":          model["id"],
        "model_name":        model["name"],
        "question":          question["question"],
        "answer":            "[DRY-RUN]",
        "mention_detected":  False,
        "mention_position":  None,
        "entities_found":    "",
        "urls_found":        "",
        "context_snippet":   "",
        "disclaimer_detected": False,
    }


def _error_result(run_date: str, ts: str, question: dict, model: dict, error_msg: str) -> dict:
    result = _dummy_result(run_date, question, model)
    result["run_timestamp"] = ts
    result["answer"] = f"ERROR: {error_msg}"
    return result


# ------------------------------------------------------------------ #
# エントリポイント
# ------------------------------------------------------------------ #
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AI Citation Monitoring Runner")
    parser.add_argument("--set",     dest="question_set", type=str, default="set1",
                        choices=["set1", "set2", "both"],
                        help="質問セット選択（set1=現行78問 / set2=新規60問 / both=両方）。既定 set1")
    parser.add_argument("--domain",  type=str, default=None,
                        help="事業ドメインフィルタ (例: C1, C3, C3-EC, C7)")
    parser.add_argument("--models",  type=str, default=None,
                        help="観測するモデルを指定（カンマ区切り）。"
                             "モデルID または モデル名。例: --models gpt-4o,sonar-pro")
    parser.add_argument("--all",     dest="use_all", action="store_true",
                        help="全有効モデルを実行（対話メニューを表示しない）")
    parser.add_argument("--dry-run", action="store_true",
                        help="API 呼び出しなしで動作確認")
    args = parser.parse_args()

    run_monitoring(domain_filter=args.domain, dry_run=args.dry_run,
                   models_arg=args.models, use_all=args.use_all,
                   question_set=args.question_set)

# EOF
