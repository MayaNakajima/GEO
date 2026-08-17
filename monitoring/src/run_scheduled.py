"""
ヘッドレス自動実行（OS常駐スケジュール用）
────────────────────────────────────────────────
Windows タスクスケジューラから「毎日」呼び出される前提の実行スクリプト。
GUI（webapp.py）を開いていなくても動作する（＝アプリを閉じても実行される）。

仕組み（デイリーゲート＋キャッチアップ方式）:
  1. タスクスケジューラが毎日決まった時刻に本スクリプトを起動する
     （加えて、スリープ復帰イベントでも起動する）。
  2. 本スクリプトが config/schedule.json の頻度ルールを読み、
     「直近の“実行すべきだった予定時刻”（＝過去の予定）が、まだ実行されて
     いないか」を判定する（キャッチアップ判定）。
     → 既存GUIと同じ頻度ロジック（●日おき / 毎週 / 隔週 / 毎月〇日 /
        第◆曜日 / 第N営業日 / 月初・月末営業日、日本の祝日除外）をそのまま流用。
  3. 未実行の過去予定があれば engine.execute_timing() で本番実行（per-run保存・
     Tier2/Tier3集計・ダッシュボード再生成・Teams通知）を行い、その予定時刻を
     data/last_run.json に記録する。既に実行済みなら何もせず終了する。

なぜ「今日が対象日か」ではなく「未実行の過去予定があるか」なのか:
  スリープ等で起動時刻を逃すと、Windows の StartWhenAvailable による取り残し
  実行は“別の日付になってから”発火する。旧方式（date.today() が対象曜日か）
  だと、翌日に起動された時点で「対象日ではない」と誤判定し、タスク履歴上は
  成功(0)なのにデータが作られない事故が起きていた。予定時刻ベースで
  「未実行の回」を追いかけることで、日付がずれても取りこぼしを確実に実行し、
  かつ二重実行も防ぐ。

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
STATE_PATH   = DATA_DIR / "last_run.json"
DEFAULT_CONF = CONFIG_DIR / "schedule.json"

# ロックが本値より古ければ「取り残し」とみなして上書きする（秒）
STALE_LOCK_SEC = 6 * 60 * 60

# キャッチアップの既定猶予日数（過去予定がこれより古い場合は実行せず記録だけ進める）。
# schedule.json の "catch_up_days" で上書き可能。0以下で無制限。
DEFAULT_CATCH_UP_DAYS = 7


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
# 実行状態（最後に実行した“予定時刻”）の記録
# ------------------------------------------------------------------ #
def load_last_run() -> datetime | None:
    """data/last_run.json に記録された「最後に実行した予定時刻」を返す。"""
    try:
        if not STATE_PATH.exists():
            return None
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        raw = data.get("last_scheduled")
        if not raw:
            return None
        return datetime.strptime(str(raw)[:19], "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


def save_last_run(scheduled_dt: datetime, executed: bool):
    """
    キャッチアップの基準となる「消化済みの予定時刻」を記録する。
    executed=False は「古すぎてスキップした（が消化済み扱いにする）」場合。
    """
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps({
            "last_scheduled": f"{scheduled_dt:%Y-%m-%d %H:%M:%S}",
            "recorded_at":    f"{datetime.now():%Y-%m-%d %H:%M:%S}",
            "executed":       bool(executed),
        }, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


# ------------------------------------------------------------------ #
# キャッチアップ判定
# ------------------------------------------------------------------ #
def due_occurrence(rule: dict, anchor: date, now: datetime) -> datetime | None:
    """now 時点で「本来実行されているべきだった直近の予定時刻」を返す。"""
    return scheduler.previous_timing(rule, before=now, anchor=anchor)


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
# プレビュー
# ------------------------------------------------------------------ #
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
    now    = datetime.now()
    today  = date.today()
    dry    = bool(args.dry_run or conf.get("dry_run", False))
    try:
        catch_up_days = int(conf.get("catch_up_days", DEFAULT_CATCH_UP_DAYS))
    except Exception:
        catch_up_days = DEFAULT_CATCH_UP_DAYS

    desc = scheduler.describe_rule(rule)

    # ---- キャッチアップ判定に使う値 ---- #
    due  = due_occurrence(rule, anchor, now)   # 直近の“実行すべきだった予定時刻”
    last = load_last_run()                     # 最後に消化した予定時刻

    # ---- --check：判定と次回予定を表示して終了 ---- #
    if args.check:
        print(f"設定ファイル   : {conf_path}")
        print(f"有効フラグ     : {conf.get('enabled', True)}")
        print(f"頻度ルール     : {desc}")
        print(f"開始基準日     : {anchor}")
        print(f"現在時刻       : {now:%Y-%m-%d %H:%M}")
        print(f"直近の予定     : {due:%Y-%m-%d %H:%M} " if due else "直近の予定     : （まだありません）")
        print(f"最後に消化した予定: {last:%Y-%m-%d %H:%M}" if last else "最後に消化した予定: （記録なし）")
        pending = due is not None and (last is None or due > last)
        if pending:
            age_days = (now - due).days
            if catch_up_days > 0 and age_days > catch_up_days:
                verdict = f"未消化だが古すぎるためスキップ対象（{age_days}日前 > 猶予{catch_up_days}日）"
            else:
                verdict = "★ 未消化 → 今起動すれば実行する"
        else:
            verdict = "消化済み（今起動しても実行しない）"
        print(f"判定           : {verdict}")
        print(f"キャッチアップ猶予: {catch_up_days}日" + ("（無制限）" if catch_up_days <= 0 else ""))
        print("今後の実行予定:")
        for dt in preview_next(rule, anchor):
            print(f"  - {dt:%Y-%m-%d %H:%M}")
        print(f"モデル         : {plan.get('models')}")
        print(f"質問セット     : {plan.get('question_set', 'set1')}")
        print(f"ドライラン     : {dry}")
        return 0

    # ---- enabled フラグ ---- #
    if not conf.get("enabled", True) and not args.force:
        log(f"スケジュールは無効化されています（enabled:false）。何もせず終了します。設定：{desc}")
        return 0

    # ---- 実行するか（キャッチアップ判定） ---- #
    if not args.force:
        if due is None:
            log(f"まだ実行予定がありません（設定：{desc}／開始基準日 {anchor}）。何もせず終了します。")
            return 0
        if last is not None and due <= last:
            # 直近の予定は消化済み。二重実行しない。
            log(f"直近の予定 {due:%Y-%m-%d %H:%M} は実行済みです（設定：{desc}）。何もせず終了します。")
            return 0
        # 未消化の過去予定あり。古すぎないか（キャッチアップ猶予）を確認。
        age_days = (now - due).days
        if catch_up_days > 0 and age_days > catch_up_days:
            log(f"未実行の予定 {due:%Y-%m-%d %H:%M} は {age_days}日前で、キャッチアップ猶予"
                f"（{catch_up_days}日）を超えています。今回は実行せず消化済みとして記録します"
                f"（設定：{desc}）。")
            save_last_run(due, executed=False)
            return 0
        log(f"未実行の予定 {due:%Y-%m-%d %H:%M} を実行します"
            f"（現在 {now:%Y-%m-%d %H:%M}／設定：{desc}）。")
    else:
        log(f"--force 指定：予定判定を無視して実行します（設定：{desc}）。")

    # ---- 多重起動ロック ---- #
    if not acquire_lock():
        log("別の実行が進行中のようです（ロック有効）。今回はスキップします。")
        return 0

    try:
        engine.execute_timing(plan, dry_run=dry, progress_cb=_progress)
        log("自動実行が正常に完了しました。")
        # 成功したら、この予定を消化済みとして記録（＝次回以降の二重実行を防ぐ）。
        # --force は「判定を無視した手動テスト」なので状態は書き換えない
        #（特に --force --dry-run が本来の定期実行を消化済みにしてしまう事故を防ぐ）。
        if not args.force and due is not None:
            save_last_run(due, executed=True)
        return 0
    except Exception as e:
        log(f"実行中にエラーが発生しました：{e}")
        return 1
    finally:
        release_lock()


if __name__ == "__main__":
    sys.exit(main())

# EOF
