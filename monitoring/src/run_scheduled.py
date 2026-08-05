"""
ヘッドレス自動実行（OS常駐スケジュール用）
────────────────────────────────────────────────
Windows タスクスケジューラから「毎日」呼び出される前提の実行スクリプト。
GUI（webapp.py）を開いていなくても動作する（＝アプリを閉じても実行される）。

仕組み（デイリーゲート方式）:
  1. タスクスケジューラが毎日決まった時刻に本スクリプトを起動する。
  2. 本スクリプトが config/schedule.json の頻度ルールを読み、
     「本日が実行対象日か」を scheduler.rule_matches() で判定する。
     → 既存GUIと同じ頻度ロジック（●日おき / 毎週 / 隔週 / 毎月〇日 /
        第◆曜日 / 第N営業日 / 月初・月末営業日、日本の祝日除外）をそのまま流用。
  3. 対象日なら engine.execute_timing() で本番実行（per-run保存・Tier2/Tier3集計・
     ダッシュボード再生成・Teams通知）を行う。対象外なら何もせず正常終了する。

使い方:
    python src/run_scheduled.py            # 本日が対象日なら実行（タスクからの通常呼び出し）
    python src/run_scheduled.py --check    # 実行はせず、本日の判定と次回予定だけ表示
    python src/run_scheduled.py --force     # 対象日判定を無視して今すぐ1回実行（動作確認用）
    python src/run_scheduled.py --dry-run   # API呼び出しなしで実行（--force と併用可）
    python src/run_scheduled.py --config path/to/schedule.json  # 設定ファイルを指定

ログは data/run_log.txt に追記される（.gitignore 済み）。
────────────────────────────────────────────────
"""

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

# ---- パス解決（他の src/*.py と同じ流儀） ---- #
BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(Path(__file__).parent))

from envload import load_env
load_env(BASE_DIR / ".env")

import scheduler
import engine

CONFIG_DIR   = BASE_DIR / "config"
DATA_DIR     = BASE_DIR / "data"
LOG_PATH     = DATA_DIR / "run_log.txt"
LOCK_PATH    = DATA_DIR / ".scheduled.lock"
DEFAULT_CONF = CONFIG_DIR / "schedule.json"

# ロックが本値より古ければ「取り残し」とみなして上書きする（秒）
STALE_LOCK_SEC = 6 * 60 * 60


# ------------------------------------------------------------------ #
# ログ
# ------------------------------------------------------------------ #
def log(msg: str):
    """data/run_log.txt に1行追記し、標準出力にも出す。"""
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line, flush=True)
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


# ------------------------------------------------------------------ #
# 設定読み込み
# ------------------------------------------------------------------ #
def load_schedule(conf_path: Path) -> dict:
    if not conf_path.exists():
        raise FileNotFoundError(
            f"スケジュール設定が見つかりません: {conf_path}\n"
            f"  → GUI（monitoring_gui.bat）の「OS自動実行として保存」で作成するか、"
            f"config/schedule.json.example をコピーして編集してください。")
    with open(conf_path, encoding="utf-8") as f:
        conf = json.load(f)
    if "rule" not in conf or "plan" not in conf:
        raise ValueError("schedule.json に 'rule' または 'plan' がありません。")
    return conf


def parse_anchor(conf: dict) -> date:
    """anchor（開始基準日）を date に。未設定なら本日を採用。"""
    raw = conf.get("anchor")
    if not raw:
        return date.today()
    try:
        return datetime.strptime(str(raw)[:10], "%Y-%m-%d").date()
    except Exception:
        return date.today()


# ------------------------------------------------------------------ #
# 多重起動ロック
# ------------------------------------------------------------------ #
def acquire_lock() -> bool:
    """実行ロックを取得。既に有効なロックがあれば False。"""
    try:
        if LOCK_PATH.exists():
            age = datetime.now().timestamp() - LOCK_PATH.stat().st_mtime
            if age < STALE_LOCK_SEC:
                return False
            log(f"古いロック（{int(age)}秒経過）を無視して上書きします。")
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        LOCK_PATH.write_text(
            f"pid={os.getpid()} at={datetime.now():%Y-%m-%d %H:%M:%S}",
            encoding="utf-8")
        return True
    except Exception:
        # ロック機構が使えなくても実行自体は妨げない
        return True


def release_lock():
    try:
        if LOCK_PATH.exists():
            LOCK_PATH.unlink()
    except Exception:
        pass


# ------------------------------------------------------------------ #
# 進捗コールバック（ログへ要約出力）
# ------------------------------------------------------------------ #
def _progress(info: dict):
    phase = info.get("phase")
    if phase == "start":
        log(f"タイミング開始：{info.get('runs_total')}回 / "
            f"モデル {', '.join(info.get('models', []))} / {info.get('questions')}問")
    elif phase == "run_start":
        log(f"第{info['run_index']}/{info['runs_total']}回 実行開始")
    elif phase == "run_done":
        log(f"第{info['run_index']}/{info['runs_total']}回 完了：全体出現率 {info['overall_rate']}%")
    elif phase == "aggregate":
        log("集計・レポート生成中…")
    elif phase == "done":
        log(f"タイミング完了：平均 {info['overall_mean']}% / SD ±{info['overall_sd']}pt / "
            f"安定性 {info['stability']}%")
    elif phase == "stopped":
        log("中断されました")


# ------------------------------------------------------------------ #
# 判定・プレビュー
# ------------------------------------------------------------------ #
def is_run_day(rule: dict, today: date, anchor: date) -> bool:
    if today < anchor:
        return False
    return scheduler.rule_matches(rule, today, anchor)


def preview_next(rule: dict, anchor: date, count: int = 5) -> list:
    """本日以降の実行予定日を count 件返す（時刻はルールの time を使用）。"""
    out = []
    after = datetime.combine(date.today(), datetime.min.time()) - timedelta(seconds=1)
    for _ in range(count):
        nxt = scheduler.next_timing(rule, after=after, anchor=anchor)
        if not nxt:
            break
        out.append(nxt)
        after = nxt
    return out


# ------------------------------------------------------------------ #
# メイン
# ------------------------------------------------------------------ #
def main():
    parser = argparse.ArgumentParser(
        description="AI出現モニタリング ヘッドレス自動実行（OS常駐スケジュール用）")
    parser.add_argument("--config", type=str, default=None,
                        help="スケジュール設定ファイル（既定 config/schedule.json）")
    parser.add_argument("--check", action="store_true",
                        help="実行せず、本日の判定と次回予定だけ表示")
    parser.add_argument("--force", "--now", dest="force", action="store_true",
                        help="対象日判定を無視して今すぐ1回実行（動作確認用）")
    parser.add_argument("--dry-run", action="store_true",
                        help="API呼び出しなしで実行")
    args = parser.parse_args()

    conf_path = Path(args.config) if args.config else DEFAULT_CONF

    try:
        conf = load_schedule(conf_path)
    except Exception as e:
        log(f"設定エラー：{e}")
        return 1

    rule   = conf.get("rule", {})
    plan   = dict(conf.get("plan", {}))
    plan.setdefault("mode", "auto")
    anchor = parse_anchor(conf)
    today  = date.today()
    dry    = bool(args.dry_run or conf.get("dry_run", False))

    desc = scheduler.describe_rule(rule)

    # ---- --check：判定と次回予定を表示して終了 ---- #
    if args.check:
        matched = is_run_day(rule, today, anchor)
        print(f"設定ファイル : {conf_path}")
        print(f"有効フラグ   : {conf.get('enabled', True)}")
        print(f"頻度ルール   : {desc}")
        print(f"開始基準日   : {anchor}")
        print(f"本日({today}) : {'★ 実行対象日' if matched else '対象外（実行しない）'}")
        print("今後の実行予定:")
        for dt in preview_next(rule, anchor):
            print(f"  - {dt:%Y-%m-%d %H:%M}")
        print(f"モデル       : {plan.get('models')}")
        print(f"質問セット   : {plan.get('question_set', 'set1')}")
        print(f"ドライラン   : {dry}")
        return 0

    # ---- enabled フラグ ---- #
    if not conf.get("enabled", True) and not args.force:
        log(f"スケジュールは無効化されています（enabled:false）。何もせず終了します。設定：{desc}")
        return 0

    # ---- 実行対象日か ---- #
    if not args.force and not is_run_day(rule, today, anchor):
        log(f"本日 {today} は実行対象日ではありません（設定：{desc}）。何もせず終了します。")
        return 0

    if args.force:
        log(f"--force 指定：対象日判定を無視して実行します（設定：{desc}）。")
    else:
        log(f"本日 {today} は実行対象日です（設定：{desc}）。実行を開始します。")

    # ---- 多重起動ロック ---- #
    if not acquire_lock():
        log("別の実行が進行中のようです（ロック有効）。今回はスキップします。")
        return 0

    try:
        engine.execute_timing(plan, dry_run=dry, progress_cb=_progress)
        log("自動実行が正常に完了しました。")
        return 0
    except Exception as e:
        log(f"実行中にエラーが発生しました：{e}")
        return 1
    finally:
        release_lock()


if __name__ == "__main__":
    sys.exit(main())

# EOF
