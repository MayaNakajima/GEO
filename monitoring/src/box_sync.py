"""
Box 共有フォルダとの同期
────────────────────────────────────────────────
関係者が作業に使う Box 上のコピー（例: Box 上の 生成AI/GEO フォルダ）を、GitHub 側
（このリポジトリ＝定期自動実行の書き込み先）と揃える。

方針（GitHub 側がマスター）:
  1. 結果データの取り込み（Box → GitHub）
     Box の data/results・logs・reports にあって GitHub に無いファイルを追加する。
     （関係者が Box の GUI で手動実行した回を取り込むため。上書き・削除はしない）
  2. 集計の再構築（取り込みがあった場合のみ）
     index.json / trend.json / dashboard.html / insights.html を作り直す。
  3. プログラム・資料の反映（GitHub → Box）
     リポジトリのファイル（data/・.env・個人設定を除く）を Box にコピーする。
     Box 側の方が新しく編集されているファイルは上書きせず警告だけ出す。
     上書きする Box 側の旧ファイルは data/_archive/sync_backup/ に退避する。
  4. 結果データの反映（GitHub → Box）
     GitHub にあって Box に無い結果ファイルを追加し、集計ファイルは GitHub 側で置き換える。

設定: config/box_sync.json（ユーザ個別のため .gitignore 済み。雛形は box_sync.json.example）
    {"enabled": true, "box_dir": "C:/Users/<you>/Box/<共有フォルダ>/GEO"}
  box_dir はリポジトリのルート（monitoring の親）に相当する Box フォルダ。

使い方:
    python src/box_sync.py            # 同期を実行
    python src/box_sync.py --dry-run  # 何がコピーされるかだけ表示
────────────────────────────────────────────────
"""

import argparse
import filecmp
import json
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

BASE_DIR    = Path(__file__).parent.parent          # monitoring/
REPO_DIR    = BASE_DIR.parent                       # GEO/
sys.path.insert(0, str(Path(__file__).parent))

CONF_PATH   = BASE_DIR / "config" / "box_sync.json"
DATA_DIR    = BASE_DIR / "data"
RESULTS_DIR = DATA_DIR / "results"
REPORTS_DIR = DATA_DIR / "reports"

# 結果データ（追加のみで双方向に揃える）: (data 配下のフォルダ, パターン)
DATA_PATTERNS = [
    ("results", "results_*.csv"),
    ("logs",    "log_*.jsonl"),
    ("reports", "report_*.json"),
    ("reports", "timing_*.json"),
    ("reports", "insights_*.json"),
]
# 集計ファイル（GitHub 側で作り直したものを Box に上書き）
DERIVED_FILES = ["reports/index.json", "reports/trend.json",
                 "dashboard.html", "insights.html"]

# プログラム反映の対象外（リポジトリルートからの相対パス）
EXCLUDE_DIRS  = {".git", ".claude", "__pycache__", ".venv", "venv",
                 ".ipynb_checkpoints"}
EXCLUDE_FILES = {"monitoring/.env", "monitoring/config/schedule.json",
                 "monitoring/config/box_sync.json"}
EXCLUDE_SUFFIXES = (".pyc", ".pyo", ".bak", ".tmp", "~")

# 書き込み途中のファイルを拾わないよう、直近に更新されたものは次回に回す
SETTLE_SEC = 10 * 60


def load_conf(path: Path = CONF_PATH):
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _settled(p: Path) -> bool:
    return time.time() - p.stat().st_mtime >= SETTLE_SEC


def _copy(src: Path, dst: Path, dry: bool):
    if dry:
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)   # mtime を保持（次回の新旧判定に使う）


def _add_missing(src_data: Path, dst_data: Path, dry: bool) -> list:
    """src にあって dst に無い結果ファイルを追加。追加した相対パスを返す。"""
    added = []
    for sub, pat in DATA_PATTERNS:
        for p in sorted((src_data / sub).glob(pat)):
            dst = dst_data / sub / p.name
            if dst.exists() or not _settled(p):
                continue
            _copy(p, dst, dry)
            added.append(f"{sub}/{p.name}")
    return added


def _is_excluded(rel: str) -> bool:
    if rel.startswith("monitoring/data/"):
        return True
    if any(part in EXCLUDE_DIRS for part in rel.split("/")[:-1]):
        return True
    return rel in EXCLUDE_FILES or rel.endswith(EXCLUDE_SUFFIXES)


def _push_code(box_root: Path, backup_dir: Path, dry: bool, log) -> dict:
    copied, skipped = [], []
    for p in sorted(REPO_DIR.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(REPO_DIR).as_posix()
        if _is_excluded(rel):
            continue
        dst = box_root / rel
        if dst.exists():
            if filecmp.cmp(p, dst, shallow=False):
                continue
            if dst.stat().st_mtime > p.stat().st_mtime + 2:
                skipped.append(rel)
                log(f"Box同期: Box側の方が新しいため上書きしません → {rel}"
                    "（GitHub側へ反映するか、Box側を元に戻してください）")
                continue
            if not dry:
                bk = backup_dir / rel
                bk.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(dst, bk)
        _copy(p, dst, dry)
        copied.append(rel)
    return {"copied": copied, "skipped": skipped}


def _rebuild(log):
    """取り込んだ回を含めて集計・ダッシュボード・示唆レポートを作り直す。"""
    import reset_data
    import insight_report
    reset_data.rebuild_aggregates()
    timings = sorted(REPORTS_DIR.glob("timing_*.json"))
    if not timings:
        return
    tid = timings[-1].stem.replace("timing_", "")
    files = sorted(RESULTS_DIR.glob(f"results_{tid}_r*.csv"))
    if not files:
        return
    rows = [r for f in files for r in insight_report.read_csv_rows(f)]
    insight_report.generate_from_rows(
        rows, source_label=f"timing {tid}",
        out_html=DATA_DIR / "insights.html",
        out_json=REPORTS_DIR / f"insights_{tid}.json")
    log(f"Box同期: 集計を再構築しました（最新タイミング {tid}）。")


def sync(dry: bool = False, log=print, conf_path: Path = CONF_PATH) -> dict:
    conf = load_conf(conf_path)
    if not conf or not conf.get("enabled", True):
        return {"status": "disabled"}
    box_root = Path(conf["box_dir"])
    box_mon  = box_root / "monitoring"
    if not box_mon.is_dir():
        log(f"Box同期: Box フォルダが見つからないためスキップしました（{box_root}）。")
        return {"status": "missing"}
    box_data = box_mon / "data"
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # 1) Box → GitHub（追加のみ）
    pulled = _add_missing(box_data, DATA_DIR, dry)
    for rel in pulled:
        log(f"Box同期: Box側の結果を取り込み → {rel}")

    # 2) 取り込みがあれば集計を作り直す
    if pulled and not dry:
        _rebuild(log)

    # 3) プログラム・資料 GitHub → Box
    code = _push_code(box_root, box_data / "_archive" / "sync_backup" / stamp, dry, log)

    # 4) 結果データ GitHub → Box
    pushed = _add_missing(DATA_DIR, box_data, dry)
    derived = []
    for rel in DERIVED_FILES:
        src, dst = DATA_DIR / rel, box_data / rel
        if src.exists() and not (dst.exists() and filecmp.cmp(src, dst, shallow=False)):
            _copy(src, dst, dry)
            derived.append(rel)

    summary = (f"Box同期{'（ドライラン）' if dry else ''}: 取り込み {len(pulled)}件 / "
               f"プログラム反映 {len(code['copied'])}件（保留 {len(code['skipped'])}件） / "
               f"結果反映 {len(pushed)}件 / 集計更新 {len(derived)}件")
    log(summary)
    if dry:
        for rel in code["copied"] + [f"data/{r}" for r in pushed + derived]:
            log(f"  - {rel}")
    return {"status": "ok", "pulled": pulled, "code": code,
            "pushed": pushed, "derived": derived}


def main():
    ap = argparse.ArgumentParser(description="Box 共有フォルダとの同期")
    ap.add_argument("--dry-run", action="store_true", help="コピーせず内容だけ表示")
    args = ap.parse_args()
    res = sync(dry=args.dry_run)
    if res["status"] == "disabled":
        print(f"Box同期は未設定です。{CONF_PATH.name}.example をコピーして "
              f"{CONF_PATH} を作成してください。")
    return 0 if res["status"] in ("ok", "disabled") else 1


if __name__ == "__main__":
    sys.exit(main())
