"""
ログ保存モジュール
────────────────────────────────────────────────
【出力ファイル】
  data/results/results_YYYY-MM-DD.csv   … Excel 分析用（UTF-8 BOM, 回答全文保存）
  data/logs/log_YYYY-MM-DD.jsonl        … APIコール全ログ（1行1JSON, 回答全文・全メタ情報）
────────────────────────────────────────────────
"""

import csv
import json
from pathlib import Path


# CSV の列定義（Excelでフィルタ・集計しやすい順）
FIELDNAMES = [
    "run_date",
    "run_timestamp",
    "question_id",
    "axis_domain",
    "domain_label",
    "axis_type",
    "type_label",
    "axis_stakeholder",
    "stakeholder_label",
    "abm_relevant",
    "model_id",
    "model_name",
    "question",
    "answer",            # ★ 全文保存（切り捨てなし）
    "mention_detected",
    "mention_position",
    "entities_found",
    "urls_found",        # ★ 検出されたURL（カンマ区切り）
    "context_snippet",
    # ↓ 質問セット対応で追加（末尾に追加＝既存列の位置は不変）
    "question_set",      # set1 / set2
    "specificity_tier",  # D1〜D4（set1は空欄）
]


class ResultLogger:

    def __init__(self, results_dir: Path, logs_dir: Path):
        self.results_dir = Path(results_dir)
        self.logs_dir    = Path(logs_dir)
        self.results_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)

    def save(self, results: list, run_date: str, stem: str = None) -> tuple:
        """
        CSV と JSONL を保存する。

        stem を指定するとファイル名の識別子に使う（例: 20260716_0900_r1）。
        指定しない場合は run_date（YYYY-MM-DD）を使う（従来動作）。

        Returns
        -------
        (csv_path, jsonl_path) : tuple[Path, Path]
        """
        stem = stem or run_date
        csv_path   = self._save_csv(results, stem)
        jsonl_path = self._save_jsonl(results, stem)
        return csv_path, jsonl_path

    # ------------------------------------------------------------------ #
    # CSV（Excel用）
    # ------------------------------------------------------------------ #
    def _save_csv(self, results: list, run_date: str) -> Path:
        path = self.results_dir / f"results_{run_date}.csv"
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDNAMES, extrasaction="ignore")
            writer.writeheader()
            for row in results:
                writer.writerow({k: row.get(k, "") for k in FIELDNAMES})
        print(f"[logger] CSV 保存: {path}  ({len(results)} 件)")
        return path

    # ------------------------------------------------------------------ #
    # JSONL（全ログ）
    # ------------------------------------------------------------------ #
    def _save_jsonl(self, results: list, run_date: str) -> Path:
        """
        1行1JSON 形式の完全ログ。
        回答全文・検出情報・タイムスタンプをすべて含む。
        JSONビューアや grep での検索に利用可能。
        """
        path = self.logs_dir / f"log_{run_date}.jsonl"
        with open(path, "w", encoding="utf-8") as f:
            for r in results:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"[logger] 全ログ JSONL 保存: {path}  ({len(results)} 件)")
        return path
