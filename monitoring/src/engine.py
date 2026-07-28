"""
実行エンジン
────────────────────────────────────────────────
1「タイミング」の実行を統括する。
  ・タイミング = ユーザーが指定した1つの実行時点
  ・1タイミングの中で M 回（●分おきに〇回、または1回のみ）実行する
  ・各回(run)ごとに CSV / JSONL / Tier1レポートを保存
  ・タイミング完了時に Tier2（ブレ分析）、全タイミング横断の Tier3（トレンド）を再生成
  ・HTMLダッシュボードを再生成
────────────────────────────────────────────────
"""

import json
import sys
import time as _time
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(Path(__file__).parent))

import runner
import analytics
from detector import MentionDetector          # noqa: F401 (runner が使用)
from logger   import ResultLogger
from reporter import ReportGenerator
import dashboard

CONFIG_DIR  = BASE_DIR / "config"
DATA_DIR    = BASE_DIR / "data"
REPORTS_DIR = DATA_DIR / "reports"


# ------------------------------------------------------------------ #
# モデル解決
# ------------------------------------------------------------------ #
def resolve_models(model_ids, all_models):
    """モデルIDのリスト → モデル辞書のリスト。空/未指定なら全 enabled。"""
    if not model_ids:
        return [m for m in all_models if m["enabled"]]
    selected = []
    for mid in model_ids:
        m = runner._find_model(all_models, mid)
        if m and m not in selected:
            selected.append(m)
    if not selected:                      # 全部不正なら enabled にフォールバック
        selected = [m for m in all_models if m["enabled"]]
    return selected


def _noop(_info):
    pass


# ------------------------------------------------------------------ #
# タイミング実行
# ------------------------------------------------------------------ #
def execute_timing(plan: dict, dry_run: bool = False,
                   progress_cb=None, stop_check=None,
                   timing_id: str = None) -> dict:
    """
    plan = {
        "models":  ["gpt-4o", ...],       # 空なら全enabled
        "domain":  None or "C5",           # 事業ドメインフィルタ（任意）
        "repeat":  {"type":"once"} or
                   {"type":"interval","interval_minutes":10,"count":3},
        "mode":    "manual" | "auto",
    }
    """
    progress_cb = progress_cb or _noop
    stop_check  = stop_check or (lambda: False)
    timing_id   = timing_id or datetime.now().strftime("%Y%m%d_%H%M%S")

    question_set = plan.get("question_set", "set1")
    questions, all_models, keywords = runner.load_config(question_set)
    domain = plan.get("domain")
    if domain:
        questions = [q for q in questions if q["axis_domain"] == domain]

    active_models = resolve_models(plan.get("models"), all_models)

    repeat = plan.get("repeat", {"type": "once"})
    if repeat.get("type") == "interval":
        M = max(1, int(repeat.get("count", 1)))
        interval_min = max(0, int(repeat.get("interval_minutes", 0)))
    else:
        M, interval_min = 1, 0

    logger   = ResultLogger(DATA_DIR / "results", DATA_DIR / "logs")
    reporter = ReportGenerator(REPORTS_DIR)

    progress_cb({"phase": "start", "timing_id": timing_id,
                 "runs_total": M, "models": [m["name"] for m in active_models],
                 "questions": len(questions), "question_set": question_set})

    run_reports      = []
    run_results_list = []

    for i in range(1, M + 1):
        if stop_check():
            progress_cb({"phase": "stopped", "timing_id": timing_id})
            break

        run_id = f"{timing_id}_r{i}"
        progress_cb({"phase": "run_start", "timing_id": timing_id,
                     "run_index": i, "runs_total": M})

        def _qcb(done, total, label, mark, _i=i):
            progress_cb({"phase": "query", "timing_id": timing_id,
                         "run_index": _i, "runs_total": M,
                         "done": done, "total": total,
                         "label": label, "mark": mark})

        results = runner.run_pass(active_models, questions, keywords,
                                  dry_run=dry_run, progress_cb=_qcb,
                                  stop_check=stop_check)

        # 中断された回は途中結果を保存せず破棄してループを抜ける
        if stop_check():
            progress_cb({"phase": "stopped", "timing_id": timing_id})
            break

        # 保存（per-run）
        logger.save(results, run_date=datetime.now().strftime("%Y-%m-%d"),
                    stem=run_id)
        meta = {"run_id": run_id, "timing_id": timing_id, "run_index": i,
                "runs_total": M, "mode": plan.get("mode", "manual"),
                "models": [m["name"] for m in active_models],
                "domain": domain, "question_set": question_set, "dry_run": dry_run}
        report = reporter.generate(results, run_date=datetime.now().strftime("%Y-%m-%d"),
                                   stem=run_id, meta=meta)
        run_reports.append(report)
        run_results_list.append(results)

        progress_cb({"phase": "run_done", "timing_id": timing_id,
                     "run_index": i, "runs_total": M,
                     "overall_rate": report["overall_rate"]})

        # 次の回まで待機（最終回は待たない）
        if i < M and interval_min > 0:
            waited = 0
            total_wait = interval_min * 60
            while waited < total_wait:
                if stop_check():
                    break
                _time.sleep(min(5, total_wait - waited))
                waited += 5
                progress_cb({"phase": "waiting", "timing_id": timing_id,
                             "next_run": i + 1, "runs_total": M,
                             "waited_sec": waited, "wait_total_sec": total_wait})

    if not run_reports:
        return {}

    # ---- Tier2: タイミング集計（ブレ分析） ---- #
    progress_cb({"phase": "aggregate", "timing_id": timing_id})
    timing_meta = {"mode": plan.get("mode", "manual"),
                   "models": [m["name"] for m in active_models],
                   "domain": domain, "question_set": question_set, "dry_run": dry_run}
    timing_report = analytics.aggregate_timing(
        timing_id, timing_meta, run_reports, run_results_list)
    _save_json(REPORTS_DIR / f"timing_{timing_id}.json", timing_report)

    # ---- index 更新 ---- #
    _update_index(timing_report)

    # ---- Tier3: 横断トレンド ---- #
    cross = _rebuild_cross_timing()

    # ---- ダッシュボード再生成 ---- #
    try:
        dashboard.render(REPORTS_DIR, DATA_DIR / "dashboard.html")
    except Exception as e:
        print(f"[engine] ダッシュボード生成エラー: {e}")

    # ---- Teams 通知（Webhook 設定時のみ） ---- #
    try:
        reporter.notify_teams(_teams_payload(timing_report, run_results_list))
    except Exception as e:
        print(f"[engine] Teams通知エラー: {e}")

    progress_cb({"phase": "done", "timing_id": timing_id,
                 "overall_mean": timing_report["overall"]["mean"],
                 "overall_sd":   timing_report["overall"]["sd"],
                 "stability":    timing_report["stability"]["score"],
                 "runs": timing_report["runs"]})

    return {"timing_report": timing_report, "cross": cross}


# ------------------------------------------------------------------ #
# 横断（Tier3）再構築
# ------------------------------------------------------------------ #
def _rebuild_cross_timing() -> dict:
    timing_reports = []
    for p in sorted(REPORTS_DIR.glob("timing_*.json")):
        try:
            timing_reports.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            pass
    cross = analytics.aggregate_cross_timing(timing_reports)
    _save_json(REPORTS_DIR / "trend.json", cross)
    return cross


def _update_index(timing_report: dict):
    idx_path = REPORTS_DIR / "index.json"
    idx = []
    if idx_path.exists():
        try:
            idx = json.loads(idx_path.read_text(encoding="utf-8"))
        except Exception:
            idx = []
    idx = [e for e in idx if e.get("timing_id") != timing_report["timing_id"]]
    idx.append({
        "timing_id":    timing_report["timing_id"],
        "timing_label": timing_report["timing_label"],
        "runs":         timing_report["runs"],
        "overall_mean": timing_report["overall"]["mean"],
        "overall_sd":   timing_report["overall"]["sd"],
        "stability":    timing_report["stability"]["score"],
        "mode":         timing_report["meta"].get("mode"),
        "models":       timing_report["meta"].get("models"),
    })
    idx.sort(key=lambda e: e["timing_id"])
    _save_json(idx_path, idx)


def _teams_payload(timing_report: dict, run_results_list: list) -> dict:
    """timing 集計 + プール結果から Teams 通知用の dict を作る。"""
    pooled = [row for results in run_results_list for row in results]
    total = len(pooled)
    det   = [r for r in pooled if r["mention_detected"]]

    def _rate(pred_all):
        allr = [r for r in pooled if pred_all(r)]
        hit  = [r for r in allr if r["mention_detected"]]
        return round(len(hit) / len(allr) * 100, 1) if allr else 0

    domain_rates = {k: v["mean"] for k, v in timing_report.get("domain_stats", {}).items()}
    model_rates  = {k: v["mean"] for k, v in timing_report.get("model_stats", {}).items()}

    return {
        "run_date":     timing_report["timing_label"],
        "overall_rate": timing_report["overall"]["mean"],
        "total_queries":  total,
        "total_detected": len(det),
        "abm_rate":   _rate(lambda r: r.get("abm_relevant")),
        "space_rate": _rate(lambda r: r.get("axis_domain") == "C6"),
        "ec_rate":    _rate(lambda r: r.get("axis_domain") == "C3-EC"),
        "domain_rates": domain_rates,
        "model_rates":  model_rates,
        "type_rates":   {},
    }


def _save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
