"""
データ初期化 / 選択削除ユーティリティ
────────────────────────────────────────────────
data/results, data/logs, data/reports の生成物と data/dashboard.html を対象に、
「全削除」または「タイミング単位の選択削除」を行う。
選択削除後は index.json / trend.json / dashboard.html を残りデータから自動で作り直す。

使い方:
    python src/reset_data.py --list          # タイミング一覧（種別つき）を表示
    python src/reset_data.py --select         # 一覧から番号で選んで削除（対話）
    python src/reset_data.py --timings 20260716_104528,2026-07-01   # 指定して削除
    python src/reset_data.py                  # 全削除（確認あり）
    python src/reset_data.py --all --yes      # 全削除（確認なし）

※ config/ や .env、ソースコードは削除しません。
"""

import sys
import csv
import glob
import json
import collections
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"
RESULTS_DIR = DATA_DIR / "results"
LOGS_DIR = DATA_DIR / "logs"
REPORTS_DIR = DATA_DIR / "reports"

sys.path.insert(0, str(Path(__file__).parent))
import analytics
import dashboard


# ------------------------------------------------------------------ #
# 一覧・分類
# ------------------------------------------------------------------ #
def _classify(stem: str) -> str:
    """results_<stem>.csv の回答内容から種別を判定。"""
    path = RESULTS_DIR / f"results_{stem}.csv"
    if not path.exists():
        return "?"
    kinds = collections.Counter()
    try:
        with open(path, encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                a = (row.get("answer") or "")
                if a.startswith("[DRY-RUN]"):
                    kinds["ドライラン"] += 1
                elif a.startswith("ERROR"):
                    kinds["エラー"] += 1
                elif a == "x":
                    kinds["合成テスト"] += 1
                else:
                    kinds["本番(実データ)"] += 1
    except Exception:
        return "?"
    if not kinds:
        return "空"
    return kinds.most_common(1)[0][0]


def _all_stems() -> list:
    """results_*.csv から全 stem（タイミングID等）を新しい順で返す。"""
    stems = []
    for f in sorted(glob.glob(str(RESULTS_DIR / "results_*.csv"))):
        stems.append(Path(f).name[len("results_"):-4])
    # タイミングIDの _rN を除いた単位でまとめる
    timings = []
    seen = set()
    for s in stems:
        base = s.split("_r")[0] if "_r" in s else s
        if base not in seen:
            seen.add(base)
            timings.append(base)
    return sorted(timings, reverse=True)


def list_timings():
    stems = _all_stems()
    if not stems:
        print("データはありません。")
        return []
    print(f"\n{'No.':>3}  {'タイミング/ID':22} {'種別':14} {'回数':>4}")
    print("-" * 52)
    rows = []
    for i, base in enumerate(stems, 1):
        runs = len(glob.glob(str(RESULTS_DIR / f"results_{base}*.csv")))
        # 種別は代表1ファイルで判定
        rep_stem = base if (RESULTS_DIR / f"results_{base}.csv").exists() else f"{base}_r1"
        kind = _classify(rep_stem)
        rows.append(base)
        print(f"{i:>3}  {base:22} {kind:14} {runs:>4}")
    print()
    return rows


# ------------------------------------------------------------------ #
# 削除
# ------------------------------------------------------------------ #
def _files_for(stem: str) -> list:
    files = []
    files += glob.glob(str(RESULTS_DIR / f"results_{stem}*.csv"))
    files += glob.glob(str(LOGS_DIR / f"log_{stem}*.jsonl"))
    files += glob.glob(str(REPORTS_DIR / f"report_{stem}*.json"))
    files += glob.glob(str(REPORTS_DIR / f"timing_{stem}.json"))
    return [Path(f) for f in files]


def delete_timings(stems: list):
    targets = []
    for s in stems:
        targets += _files_for(s)
    if not targets:
        print("削除対象が見つかりませんでした。")
        return
    print(f"削除対象 {len(targets)} 件:")
    for f in targets:
        print(f"  - {f.relative_to(BASE_DIR)}")
    deleted = 0
    for f in targets:
        try:
            f.unlink()
            deleted += 1
        except Exception as e:
            print(f"  削除失敗: {f.name} ({e})")
    print(f"{deleted} 件を削除しました。")
    rebuild_aggregates()


def full_reset():
    targets = []
    targets += glob.glob(str(RESULTS_DIR / "*.csv"))
    targets += glob.glob(str(LOGS_DIR / "*.jsonl"))
    targets += glob.glob(str(REPORTS_DIR / "*.json"))
    dh = DATA_DIR / "dashboard.html"
    if dh.exists():
        targets.append(str(dh))
    if not targets:
        print("削除対象のデータはありません。")
        return
    print(f"全削除対象 {len(targets)} 件を削除します。")
    deleted = 0
    for f in targets:
        try:
            Path(f).unlink(); deleted += 1
        except Exception as e:
            print(f"  削除失敗: {f} ({e})")
    print(f"{deleted} 件を削除しました。")


# ------------------------------------------------------------------ #
# 集計の再構築（index / trend / dashboard）
# ------------------------------------------------------------------ #
def rebuild_aggregates():
    timing_reports = []
    for p in sorted(REPORTS_DIR.glob("timing_*.json")):
        try:
            timing_reports.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            pass
    # index.json
    idx = [{
        "timing_id": t["timing_id"], "timing_label": t["timing_label"],
        "runs": t["runs"], "overall_mean": t["overall"]["mean"],
        "overall_sd": t["overall"]["sd"], "stability": t["stability"]["score"],
        "mode": t["meta"].get("mode"), "models": t["meta"].get("models"),
    } for t in timing_reports]
    idx.sort(key=lambda e: e["timing_id"])
    (REPORTS_DIR / "index.json").write_text(
        json.dumps(idx, ensure_ascii=False, indent=2), encoding="utf-8")
    # trend.json
    cross = analytics.aggregate_cross_timing(timing_reports)
    (REPORTS_DIR / "trend.json").write_text(
        json.dumps(cross, ensure_ascii=False, indent=2), encoding="utf-8")
    # dashboard
    try:
        dashboard.render(REPORTS_DIR, DATA_DIR / "dashboard.html")
    except Exception as e:
        print(f"  ダッシュボード再生成エラー: {e}")
    print(f"集計を再構築しました（残りタイミング {len(timing_reports)} 件）。")


# ------------------------------------------------------------------ #
# エントリ
# ------------------------------------------------------------------ #
def main():
    args = sys.argv[1:]

    if "--list" in args:
        list_timings()
        return

    if "--select" in args:
        rows = list_timings()
        if not rows:
            return
        raw = input("削除するタイミングの番号をカンマ区切りで入力（例: 1,3,4／空Enterで中止）: ").strip()
        if not raw:
            print("中止しました。")
            return
        picks = []
        for tok in raw.replace(" ", "").split(","):
            if tok.isdigit() and 1 <= int(tok) <= len(rows):
                picks.append(rows[int(tok) - 1])
        if not picks:
            print("有効な番号がありません。中止しました。")
            return
        print("削除対象:", ", ".join(picks))
        if input("よろしいですか？ (y/N): ").strip().lower() == "y":
            delete_timings(picks)
        else:
            print("中止しました。")
        return

    if "--timings" in args:
        i = args.index("--timings")
        ids = args[i + 1].split(",") if i + 1 < len(args) else []
        ids = [s.strip() for s in ids if s.strip()]
        if not ids:
            print("--timings の後にIDをカンマ区切りで指定してください。")
            return
        if "--yes" in args or input(f"{ids} を削除します。よろしいですか？ (y/N): ").strip().lower() == "y":
            delete_timings(ids)
        else:
            print("中止しました。")
        return

    # 既定：全削除
    if "--yes" not in args:
        list_timings()
        if input("上記を含む全データを削除します。よろしいですか？ (y/N): ").strip().lower() != "y":
            print("中止しました。")
            return
    full_reset()


if __name__ == "__main__":
    main()
