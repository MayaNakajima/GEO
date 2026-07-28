"""
レポート生成 + Microsoft Teams 通知モジュール
- 月次サマリーを JSON で保存
- Teams Incoming Webhook (Adaptive Card) で通知
"""

import json
import os
import requests
from collections import defaultdict
from pathlib import Path


class ReportGenerator:

    def __init__(self, reports_dir: Path):
        self.reports_dir = Path(reports_dir)
        self.reports_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ #
    # レポート生成
    # ------------------------------------------------------------------ #
    def generate(self, results: list, run_date: str,
                 stem: str = None, meta: dict = None) -> dict:
        total    = len(results)
        detected = [r for r in results if r["mention_detected"]]
        overall  = round(len(detected) / total * 100, 1) if total else 0

        domain_rates = self._rate_by(results, "domain_label")
        model_rates  = self._rate_by(results, "model_name")
        type_rates   = self._rate_by(results, "type_label")

        # 質問セット別（set1/set2）・特異度ティア別（D1〜D4）★v7
        set_rates    = self._rate_by(results, "question_set")
        tier_results = [r for r in results if r.get("specificity_tier")]
        tier_rates   = self._rate_by(tier_results, "specificity_tier") if tier_results else {}

        # ABM スコア（abm_relevant=True の質問のみ）
        abm_all      = [r for r in results if r.get("abm_relevant")]
        abm_hit      = [r for r in abm_all  if r["mention_detected"]]
        abm_rate     = round(len(abm_hit) / len(abm_all) * 100, 1) if abm_all else 0

        # 空間ビジネス出現率
        space_all    = [r for r in results if r.get("axis_domain") == "C6"]
        space_hit    = [r for r in space_all if r["mention_detected"]]
        space_rate   = round(len(space_hit) / len(space_all) * 100, 1) if space_all else 0

        # ECサイト出現率
        ec_all       = [r for r in results if r.get("axis_domain") == "C3-EC"]
        ec_hit       = [r for r in ec_all   if r["mention_detected"]]
        ec_rate      = round(len(ec_hit) / len(ec_all) * 100, 1) if ec_all else 0

        # 出現した上位事例（最大 5 件）
        top = [
            {
                "question": r["question"][:70],
                "model":    r["model_name"],
                "position": r["mention_position"],
                "context":  r["context_snippet"][:120],
            }
            for r in detected[:5]
        ]

        report = {
            "run_date":     run_date,
            "overall_rate": overall,
            "total_queries":  total,
            "total_detected": len(detected),
            "abm_rate":    abm_rate,
            "space_rate":  space_rate,
            "ec_rate":     ec_rate,
            "domain_rates": domain_rates,
            "model_rates":  model_rates,
            "type_rates":   type_rates,
            "set_rates":    set_rates,
            "tier_rates":   tier_rates,
            "top_detections": top,
        }
        if meta:
            report.update(meta)

        out = self.reports_dir / f"report_{stem or run_date}.json"
        with open(out, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"[reporter] レポート保存: {out}")
        return report

    # ------------------------------------------------------------------ #
    # Microsoft Teams 通知（Adaptive Card）
    # ------------------------------------------------------------------ #
    def notify_teams(self, report: dict):
        webhook_url = os.environ.get("TEAMS_WEBHOOK_URL", "")
        if not webhook_url:
            print("[reporter] TEAMS_WEBHOOK_URL 未設定 — 通知をスキップします")
            return

        domain_facts = [
            {"title": domain, "value": f"{rate}%"}
            for domain, rate in sorted(report["domain_rates"].items(), key=lambda x: -x[1])
        ]
        model_facts = [
            {"title": model, "value": f"{rate}%"}
            for model, rate in sorted(report["model_rates"].items(), key=lambda x: -x[1])
        ]

        card = {
            "type": "message",
            "attachments": [
                {
                    "contentType": "application/vnd.microsoft.card.adaptive",
                    "content": {
                        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                        "type":    "AdaptiveCard",
                        "version": "1.4",
                        "body": [
                            {
                                "type": "TextBlock",
                                "text": f"🔍 AI出現モニタリング 月次レポート — {report['run_date']}",
                                "weight": "Bolder",
                                "size":   "Large",
                                "wrap":   True,
                            },
                            {
                                "type": "FactSet",
                                "facts": [
                                    {"title": "📊 全体出現率",     "value": f"{report['overall_rate']}%"},
                                    {"title": "総クエリ数",        "value": str(report['total_queries'])},
                                    {"title": "出現回数",          "value": str(report['total_detected'])},
                                    {"title": "🎯 ABMスコア",      "value": f"{report['abm_rate']}%"},
                                    {"title": "🏢 空間ビジネス出現率", "value": f"{report['space_rate']}%"},
                                    {"title": "🛒 ECサイト出現率",  "value": f"{report['ec_rate']}%"},
                                ],
                            },
                            {
                                "type":      "TextBlock",
                                "text":      "事業別出現率",
                                "weight":    "Bolder",
                                "separator": True,
                            },
                            {
                                "type":  "FactSet",
                                "facts": domain_facts,
                            },
                            {
                                "type":      "TextBlock",
                                "text":      "モデル別出現率",
                                "weight":    "Bolder",
                                "separator": True,
                            },
                            {
                                "type":  "FactSet",
                                "facts": model_facts,
                            },
                            {
                                "type":      "TextBlock",
                                "text":      "質問タイプ別出現率",
                                "weight":    "Bolder",
                                "separator": True,
                            },
                            {
                                "type": "FactSet",
                                "facts": [
                                    {"title": t, "value": f"{r}%"}
                                    for t, r in sorted(report["type_rates"].items(), key=lambda x: -x[1])
                                ],
                            },
                        ],
                    },
                }
            ],
        }

        try:
            resp = requests.post(webhook_url, json=card, timeout=15)
            if resp.status_code == 200:
                print("[reporter] Teams 通知を送信しました ✓")
            else:
                print(f"[reporter] Teams 通知エラー: {resp.status_code} / {resp.text[:200]}")
        except Exception as e:
            print(f"[reporter] Teams 通知に失敗しました: {e}")

    # ------------------------------------------------------------------ #
    # ヘルパー
    # ------------------------------------------------------------------ #
    def _rate_by(self, results: list, key: str) -> dict:
        stats = defaultdict(lambda: {"total": 0, "detected": 0})
        for r in results:
            kv = r.get(key)
            if kv in (None, ""):
                continue
            stats[kv]["total"] += 1
            if r["mention_detected"]:
                stats[kv]["detected"] += 1
        return {
            k: round(v["detected"] / v["total"] * 100, 1)
            for k, v in stats.items() if v["total"] > 0
        }
