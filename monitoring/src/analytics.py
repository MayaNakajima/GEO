"""
集計・分析モジュール（3層レポート）
────────────────────────────────────────────────
Tier1 : 1回ごと（per-run）      … reporter.ReportGenerator.generate() が生成
Tier2 : 1タイミングごと（per-timing）… aggregate_timing()  … M回実行のまとめ・ブレ分析
Tier3 : 複数タイミング（cross-timing）… aggregate_cross_timing() … 時系列トレンド・比較・示唆

重視する分析軸：
  ・応答の安定性（ブレ）＝同一タイミングをM回実行したときの出現のばらつき
  ・時系列トレンド     ＝タイミングをまたいだ出現率の推移
  ・施策への示唆       ＝コンテンツ空白・あと一歩の質問・改善/低下ドメイン
────────────────────────────────────────────────
"""

from datetime import datetime
from statistics import mean, pstdev


def _mean_sd(values: list):
    vals = [v for v in values if v is not None]
    if not vals:
        return 0.0, 0.0
    m = mean(vals)
    sd = pstdev(vals) if len(vals) > 1 else 0.0
    return round(m, 1), round(sd, 1)


def _fmt_timing_label(timing_id: str) -> str:
    try:
        dt = datetime.strptime(timing_id, "%Y%m%d_%H%M%S")
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return timing_id


# ================================================================== #
# Tier2 : 1タイミング（M回）の集計 + ブレ分析
# ================================================================== #
def aggregate_timing(timing_id: str, meta: dict,
                     run_reports: list, run_results_list: list) -> dict:
    """
    Parameters
    ----------
    timing_id : str            例 "20260716_090000"
    meta : dict                プラン情報（models, mode, domain など）
    run_reports : list[dict]   各回の Tier1 レポート（reporter.generate の戻り値）
    run_results_list : list[list[dict]]  各回の生結果（質問×モデルの行）
    """
    M = len(run_reports)

    overall_mean, overall_sd = _mean_sd([r["overall_rate"] for r in run_reports])

    # モデル別 平均±SD
    model_names = set()
    for r in run_reports:
        model_names.update(r.get("model_rates", {}).keys())
    model_stats = {}
    for name in model_names:
        vals = [r.get("model_rates", {}).get(name) for r in run_reports]
        m, sd = _mean_sd(vals)
        model_stats[name] = {"mean": m, "sd": sd}

    # ドメイン別 平均±SD
    domain_names = set()
    for r in run_reports:
        domain_names.update(r.get("domain_rates", {}).keys())
    domain_stats = {}
    for name in domain_names:
        vals = [r.get("domain_rates", {}).get(name) for r in run_reports]
        m, sd = _mean_sd(vals)
        domain_stats[name] = {"mean": m, "sd": sd}

    # 質問セット別・特異度ティア別 平均±SD ★v7
    def _stats_from(rate_key):
        names = set()
        for r in run_reports:
            names.update(r.get(rate_key, {}).keys())
        out = {}
        for name in names:
            vals = [r.get(rate_key, {}).get(name) for r in run_reports]
            mm, ss = _mean_sd(vals)
            out[name] = {"mean": mm, "sd": ss}
        return out
    set_stats  = _stats_from("set_rates")
    tier_stats = _stats_from("tier_rates")

    # ---- ブレ分析（セル = 質問 × モデル） ---- #
    cells = {}   # key -> {"hits":int, "meta":{...}}
    for results in run_results_list:
        for row in results:
            key = (row["question_id"], row["model_id"])
            c = cells.setdefault(key, {
                "hits": 0,
                "question_id": row["question_id"],
                "model_name":  row["model_name"],
                "domain_label": row.get("domain_label", ""),
                "axis_domain":  row.get("axis_domain", ""),
                "question":     row.get("question", "")[:80],
            })
            if row.get("mention_detected"):
                c["hits"] += 1

    total_cells   = len(cells)
    consistent    = sum(1 for c in cells.values() if c["hits"] in (0, M))
    unstable_list = []
    for c in cells.values():
        if 0 < c["hits"] < M:      # M>=2 のときのみ発生
            unstable_list.append({
                "question_id": c["question_id"],
                "model_name":  c["model_name"],
                "domain_label": c["domain_label"],
                "question":    c["question"],
                "hits":        c["hits"],
                "runs":        M,
                "detect_rate": round(c["hits"] / M * 100, 0),
            })
    unstable_list.sort(key=lambda x: -x["hits"])
    stability_score = round(consistent / total_cells * 100, 1) if total_cells else 100.0

    return {
        "timing_id":   timing_id,
        "timing_label": _fmt_timing_label(timing_id),
        "runs":        M,
        "meta":        meta,
        "overall": {
            "mean": overall_mean, "sd": overall_sd,
            "min":  min((r["overall_rate"] for r in run_reports), default=0),
            "max":  max((r["overall_rate"] for r in run_reports), default=0),
            "per_run": [r["overall_rate"] for r in run_reports],
        },
        "model_stats":  model_stats,
        "domain_stats": domain_stats,
        "set_stats":    set_stats,
        "tier_stats":   tier_stats,
        "stability": {
            "score":          stability_score,   # 一貫して同じ結果だったセルの割合(%)
            "total_cells":    total_cells,
            "consistent_cells": consistent,
            "unstable_cells": len(unstable_list),
            "unstable_list":  unstable_list[:50],
            "note": ("M=1 のため、ブレ（安定性）は測定できません。"
                     "同一タイミングを2回以上実行すると安定性を評価できます。"
                     if M < 2 else ""),
        },
        "run_ids": [r.get("run_id") for r in run_reports],
    }


# ================================================================== #
# Tier3 : 複数タイミングの集計（時系列トレンド・比較・示唆）
# ================================================================== #
def aggregate_cross_timing(timing_reports: list) -> dict:
    """timing_reports: Tier2 レポートのリスト（timing_id 昇順で渡す）"""
    tr = sorted(timing_reports, key=lambda t: t["timing_id"])

    series = [{
        "timing_id":   t["timing_id"],
        "label":       t["timing_label"],
        "overall_mean": t["overall"]["mean"],
        "overall_sd":   t["overall"]["sd"],
        "runs":         t["runs"],
        "stability":    t["stability"]["score"],
    } for t in tr]

    # モデル別・ドメイン別 時系列
    def _axis_series(stat_key):
        names = set()
        for t in tr:
            names.update(t.get(stat_key, {}).keys())
        out = {}
        for name in sorted(names):
            out[name] = [t.get(stat_key, {}).get(name, {}).get("mean") for t in tr]
        return out

    model_series  = _axis_series("model_stats")
    domain_series = _axis_series("domain_stats")
    tier_series   = _axis_series("tier_stats")   # D1〜D4 の推移 ★v7
    set_series    = _axis_series("set_stats")    # set1/set2 の推移 ★v7

    # 差分（最新 vs 前回 / 最新 vs 初回）
    deltas = {}
    if len(tr) >= 2:
        latest, prev, base = tr[-1], tr[-2], tr[0]
        deltas = {
            "vs_prev":     round(latest["overall"]["mean"] - prev["overall"]["mean"], 1),
            "vs_baseline": round(latest["overall"]["mean"] - base["overall"]["mean"], 1),
            "prev_label":  prev["timing_label"],
            "base_label":  base["timing_label"],
        }

    # ドメイン別 前回比の変動（movers）
    movers = []
    if len(tr) >= 2:
        latest, prev = tr[-1], tr[-2]
        for name in domain_series:
            cur = latest.get("domain_stats", {}).get(name, {}).get("mean")
            pre = prev.get("domain_stats", {}).get(name, {}).get("mean")
            if cur is not None and pre is not None:
                movers.append({"domain": name, "delta": round(cur - pre, 1),
                               "current": cur, "previous": pre})
        movers.sort(key=lambda x: -abs(x["delta"]))

    insights = _build_insights(tr, domain_series, movers)
    insights = _add_tier_insights(insights, tr)

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "timing_count": len(tr),
        "series":        series,
        "model_series":  model_series,
        "domain_series": domain_series,
        "tier_series":   tier_series,
        "set_series":    set_series,
        "deltas":        deltas,
        "movers":        movers[:10],
        "insights":      insights,
        "latest": series[-1] if series else None,
    }


def _add_tier_insights(ins: list, tr: list) -> list:
    """特異度ティア（D1〜D4）の出現率カーブから「崖の位置」を示唆する ★v7（Set2）。"""
    if not tr:
        return ins
    tier_stats = tr[-1].get("tier_stats", {})
    if not tier_stats:
        return ins
    order = ["D1", "D2", "D3", "D4"]
    labels = {"D1": "指名", "D2": "業種特化・実績", "D3": "高特異度・非指名", "D4": "一般需要"}
    present = [t for t in order if t in tier_stats]
    if not present:
        return ins
    # ティア示唆を出す場合、汎用プレースホルダ（特筆なし）は除去
    ins = [i for i in ins if i.get("type") != "info"
           or i.get("text") != "特筆すべき変動・空白は検出されませんでした。"]
    curve = "／".join(f"{t}({labels[t]}) {tier_stats[t]['mean']}%" for t in present)
    # 崖 = 出現率がしきい値(10%)未満に落ちる最初のティア
    cliff = next((t for t in present if tier_stats[t]["mean"] < 10.0), None)
    if cliff and cliff != "D1":
        prev = present[present.index(cliff) - 1]
        text = (f"特異度の崖：Set2の出現率カーブは {curve}。"
                f"{prev}までは出現するが {cliff}（{labels[cliff]}）で {tier_stats[cliff]['mean']}% に落ちる。"
                f"埋めるべきGEOギャップは {prev}→{cliff} の間。該当ドメインの権威性・被引用の強化が優先。")
        lvl = "high"
    elif cliff == "D1":
        text = (f"特異度カーブ：{curve}。指名（D1）でも出現が弱く、"
                f"AIの学習記憶に当社情報が薄い可能性。グラウンディング型モデルでの再測定も検討。")
        lvl = "high"
    else:
        text = (f"特異度カーブ：{curve}。非指名でも出現が確認できており、"
                f"勝てる非指名クエリの拡大余地がある。有効ページの横展開を推奨。")
        lvl = "info"
    ins.append({"type": "tier_curve", "level": lvl, "text": text})
    return ins


def _build_insights(tr: list, domain_series: dict, movers: list) -> list:
    """ルールベースで施策示唆を生成。"""
    ins = []
    if not tr:
        return ins
    latest = tr[-1]

    # 1) コンテンツ空白：最新タイミングで平均出現率が低いドメイン
    gaps = []
    for name, stat in latest.get("domain_stats", {}).items():
        if stat["mean"] <= 10.0:
            gaps.append((name, stat["mean"]))
    gaps.sort(key=lambda x: x[1])
    for name, val in gaps[:5]:
        ins.append({
            "type": "content_gap",
            "level": "high",
            "text": f"コンテンツ空白：「{name}」は最新タイミングで平均出現率 {val}%。"
                    f"この事業ドメインの専用コンテンツ拡充・事例掲載を優先検討。",
        })

    # 2) あと一歩：最新タイミングでブレている質問（安定出現していない）
    unstable = latest.get("stability", {}).get("unstable_list", [])
    if unstable:
        top = unstable[:5]
        qs = "、".join(f"{u['question_id']}({u['model_name']}:{u['hits']}/{u['runs']}回)"
                       for u in top)
        ins.append({
            "type": "almost_there",
            "level": "medium",
            "text": f"あと一歩：以下の質問は出現が安定していません（ブレあり）。"
                    f"該当ページの情報充実で安定出現を狙えます → {qs}",
        })

    # 3) 低下ドメイン（前回比マイナス）
    for m in movers:
        if m["delta"] <= -10.0:
            ins.append({
                "type": "regression",
                "level": "high",
                "text": f"低下：「{m['domain']}」が前回比 {m['delta']}pt"
                        f"（{m['previous']}% → {m['current']}%）。原因調査を推奨。",
            })
    # 4) 改善ドメイン
    for m in movers:
        if m["delta"] >= 10.0:
            ins.append({
                "type": "improvement",
                "level": "info",
                "text": f"改善：「{m['domain']}」が前回比 +{m['delta']}pt"
                        f"（{m['previous']}% → {m['current']}%）。有効施策の横展開を検討。",
            })

    if not ins:
        ins.append({"type": "info", "level": "info",
                    "text": "特筆すべき変動・空白は検出されませんでした。"})
    return ins
