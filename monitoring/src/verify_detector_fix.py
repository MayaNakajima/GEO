"""
出現判定の誤検知（false-positive）修正 検証スクリプト
────────────────────────────────────────────────
保存済み CSV の回答全文（answer 列）に対して、現在の detector.py（否定・留保ガード入り）で
再判定し、CSV に記録された当時の判定（mention_detected 列）と件数比較する。

用途（指示書 §回帰チェック）：
  - True→False に変わった件数（＝誤検知として抑止できた件数）
  - False→True に変わっていないこと（＝真陽性を壊していないこと）
  を提示する。既存 CSV は書き換えない（読み取り専用）。

実行：
  cd monitoring
  python src/verify_detector_fix.py            # data/results 内の全CSVを検証
  python src/verify_detector_fix.py <csv...>   # 指定CSVのみ
"""

import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from detector import MentionDetector  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
KEYWORDS_PATH = ROOT / "config" / "detection_keywords.json"
RESULTS_DIR = ROOT / "data" / "results"

# 指示書に明記された受け入れ基準の代表3例
ACCEPTANCE = {
    "Q-C3EC-A6-B7b-042": False,  # Raffiria 留保回答 → False であるべき
    "Q-S2-C3-D1-02":     False,  # ラフィーリア 留保回答 → False であるべき
    "Q-C5-A6-B8-053":    True,   # 会社説明を実際に生成 → True 維持
}


def _parse_bool(v: str) -> bool:
    return str(v).strip().lower() in ("true", "1", "yes")


def _skip_answer(ans: str) -> bool:
    a = (ans or "").strip()
    return (not a) or a.startswith("ERROR:") or a.startswith("[DRY-RUN]")


def main(argv):
    with open(KEYWORDS_PATH, encoding="utf-8") as f:
        keywords = json.load(f)
    detector = MentionDetector(keywords)

    if argv:
        files = [Path(p) for p in argv]
    else:
        files = sorted(RESULTS_DIR.glob("results_*.csv"))

    if not files:
        print("検証対象のCSVが見つかりません。")
        return 1

    grand_t2f = 0
    grand_f2t = 0
    grand_eval = 0
    acceptance_seen = {}

    for path in files:
        if not path.exists():
            print(f"[skip] 見つかりません: {path}")
            continue
        t2f = []   # True→False（誤検知抑止できた）
        f2t = []   # False→True（あってはならない）
        evaluated = 0
        with open(path, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                ans = row.get("answer", "")
                if _skip_answer(ans):
                    continue
                evaluated += 1
                old = _parse_bool(row.get("mention_detected", ""))
                det = detector.detect(ans, domain=row.get("axis_domain") or None,
                                      question=row.get("question"))
                new = det["detected"]

                qid = row.get("question_id", "")
                if qid in ACCEPTANCE:
                    acceptance_seen.setdefault(qid, []).append((path.name, new))

                if old and not new:
                    t2f.append((qid, row.get("entities_found", ""),
                                det["disclaimer_detected"]))
                elif (not old) and new:
                    f2t.append((qid, det["entities_found"] if "entities_found" in det
                                else ", ".join(det["entities"])))

        grand_t2f += len(t2f)
        grand_f2t += len(f2t)
        grand_eval += evaluated
        print(f"\n=== {path.name} ===")
        print(f"  評価対象（answer有り）: {evaluated} 件")
        print(f"  True→False（誤検知抑止）: {len(t2f)} 件")
        for qid, ents, disc in t2f:
            print(f"      - {qid:<22} entities(旧)=[{ents}] disclaimer={disc}")
        print(f"  False→True（真陽性破壊＝0であるべき）: {len(f2t)} 件")
        for qid, ents in f2t:
            print(f"      - {qid:<22} entities(新)=[{ents}]  ★要確認")

    print("\n" + "=" * 60)
    print("【合計】")
    print(f"  評価対象: {grand_eval} 件")
    print(f"  True→False（誤検知抑止）: {grand_t2f} 件")
    print(f"  False→True（あってはならない）: {grand_f2t} 件")

    print("\n【受け入れ基準（代表3例）】")
    ok = True
    for qid, expected in ACCEPTANCE.items():
        seen = acceptance_seen.get(qid, [])
        if not seen:
            print(f"  {qid:<22} : 実データに出現なし（スキップ）")
            continue
        for fname, new in seen:
            mark = "OK" if new == expected else "NG"
            if new != expected:
                ok = False
            print(f"  {qid:<22} : 期待={expected!s:<5} 実際={new!s:<5} [{mark}] ({fname})")

    print("\n判定：", "全基準を満たしています。" if (ok and grand_f2t == 0)
          else "★基準未達の項目があります。上記を確認してください。")
    return 0 if (ok and grand_f2t == 0) else 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
