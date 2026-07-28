"""
ローカルWeb GUI サーバ
────────────────────────────────────────────────
monitoring_gui.bat から起動され、ブラウザで設定画面を開く。
標準ライブラリのみ（追加インストール不要）で動作する。

・モデル選択（複数/単一）
・手動実行 / 自動実行（定期）の切替
・開始タイミング（すぐ / ●分後）
・繰り返し（1回のみ / ●分おきに〇回）
・自動実行の頻度（●日おき/毎週/隔週/毎月/第◆曜日/第□営業日/月初/月末 …）
・進捗表示、レポート（HTMLダッシュボード）閲覧、rowデータCSVエクスポート

自動実行は「GUI常駐型」：この画面（サーバ）を起動している間だけ有効。
ウィンドウを閉じると停止する。
────────────────────────────────────────────────
"""

import csv
import io
import json
import threading
import time as _time
import webbrowser
from datetime import datetime, date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import sys
BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(Path(__file__).parent))

from envload import load_env
load_env(BASE_DIR / ".env")

import runner
import engine
import scheduler
import dashboard
import logger

WEB_DIR     = BASE_DIR / "webapp"
DATA_DIR    = BASE_DIR / "data"
REPORTS_DIR = DATA_DIR / "reports"
RESULTS_DIR = DATA_DIR / "results"

HOST = "127.0.0.1"


# ================================================================== #
# ジョブ管理（実行はシングルスレッド：同時に1タイミングのみ）
# ================================================================== #
class JobManager:
    def __init__(self):
        self.lock = threading.Lock()
        self.exec_lock = threading.Lock()      # 実行の排他
        self._cancel = threading.Event()
        self._stop_sched = threading.Event()
        self._sched_thread = None
        self._worker = None
        self.state = {
            "status": "idle",          # idle | pending | running | scheduled
            "mode": None,              # manual | auto
            "message": "待機中",
            "current": {},             # 進捗
            "schedule": None,          # 現在の自動設定
            "next_timing": None,       # 次回予定 (ISO)
            "countdown_sec": None,
            "history": [],             # 直近の完了タイミング
            "log": [],                 # ログ末尾
        }

    # ---- 状態更新ヘルパー ---- #
    def _set(self, **kw):
        with self.lock:
            self.state.update(kw)

    def _log(self, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        with self.lock:
            self.state["log"].append(f"[{ts}] {msg}")
            self.state["log"] = self.state["log"][-200:]

    def snapshot(self):
        with self.lock:
            return json.loads(json.dumps(self.state, ensure_ascii=False, default=str))

    def busy(self):
        return self.state["status"] in ("running", "pending") or \
               (self._worker and self._worker.is_alive())

    # ---- 進捗コールバック ---- #
    def _progress(self, info):
        phase = info.get("phase")
        cur = {"phase": phase}
        if phase == "start":
            cur.update({"runs_total": info.get("runs_total"),
                        "models": info.get("models"),
                        "questions": info.get("questions")})
            self._log(f"タイミング開始：{info.get('runs_total')}回 / "
                      f"モデル {', '.join(info.get('models', []))} / {info.get('questions')}問")
        elif phase == "run_start":
            self._log(f"第{info['run_index']}/{info['runs_total']}回 実行開始")
        elif phase == "query":
            cur.update({"run_index": info["run_index"], "runs_total": info["runs_total"],
                        "done": info["done"], "total": info["total"],
                        "label": info["label"], "mark": info["mark"]})
        elif phase == "run_done":
            self._log(f"第{info['run_index']}/{info['runs_total']}回 完了：全体出現率 {info['overall_rate']}%")
        elif phase == "waiting":
            cur.update({"next_run": info["next_run"],
                        "waited_sec": info["waited_sec"], "wait_total_sec": info["wait_total_sec"]})
        elif phase == "aggregate":
            self._log("集計・レポート生成中…")
        elif phase == "done":
            self._log(f"タイミング完了：平均 {info['overall_mean']}% / SD ±{info['overall_sd']}pt / "
                      f"安定性 {info['stability']}%")
        elif phase == "stopped":
            self._log("中断しました")
        with self.lock:
            merged = dict(self.state.get("current", {}))
            merged.update(cur)
            self.state["current"] = merged

    def _refresh_history(self):
        idx_path = REPORTS_DIR / "index.json"
        hist = []
        if idx_path.exists():
            try:
                hist = json.loads(idx_path.read_text(encoding="utf-8"))
            except Exception:
                hist = []
        self._set(history=list(reversed(hist))[:30])

    # ---- 1タイミング実行（排他） ---- #
    def _run_timing(self, plan, dry_run, timing_id=None):
        with self.exec_lock:
            if self._cancel.is_set():
                return
            self._set(status="running", message="実行中")
            try:
                engine.execute_timing(
                    plan, dry_run=dry_run,
                    progress_cb=self._progress,
                    stop_check=self._cancel.is_set,
                    timing_id=timing_id)
            except Exception as e:
                self._log(f"エラー：{e}")
            finally:
                self._refresh_history()

    # ---- 手動実行 ---- #
    def start_manual(self, plan, delay_min=0, dry_run=False):
        if self.busy():
            return False, "すでに実行中です。完了後に再度お試しください。"
        self._cancel.clear()

        def worker():
            if delay_min > 0:
                self._set(status="pending", mode="manual",
                          message=f"{delay_min}分後に開始予定")
                target = datetime.now() + timedelta(minutes=delay_min)
                self._log(f"手動（遅延）：{target:%H:%M} に開始予定")
                while datetime.now() < target:
                    if self._cancel.is_set():
                        self._cancel.clear()
                        self._set(status="idle", message="キャンセルしました",
                                  countdown_sec=None, next_timing=None)
                        return
                    remain = int((target - datetime.now()).total_seconds())
                    self._set(countdown_sec=remain, next_timing=target.isoformat())
                    _time.sleep(1)
            self._set(countdown_sec=None, next_timing=None)
            self._run_timing(plan, dry_run)
            # 中断・完了いずれの場合も必ず idle に戻す（次回実行できるように）
            cancelled = self._cancel.is_set()
            self._cancel.clear()
            self._set(status="idle", countdown_sec=None, next_timing=None,
                      message="中断しました（再度「実行する」で再開できます）" if cancelled else "完了")

        self._worker = threading.Thread(target=worker, daemon=True)
        self._worker.start()
        return True, "手動実行を開始しました。"

    # ---- 自動実行（定期） ---- #
    def start_auto(self, plan, rule, offset_min=0, dry_run=False):
        self.stop_auto()
        self._cancel.clear()
        self._stop_sched.clear()
        anchor_dt = datetime.now() + timedelta(minutes=offset_min)
        anchor = anchor_dt.date()
        self._set(status="scheduled", mode="auto",
                  schedule={"rule": rule, "desc": scheduler.describe_rule(rule),
                            "offset_min": offset_min,
                            "repeat": plan.get("repeat"),
                            "models": plan.get("models"),
                            "domain": plan.get("domain"),
                            "question_set": plan.get("question_set")},
                  message=f"自動実行を設定：{scheduler.describe_rule(rule)}")
        self._log(f"自動実行を開始：{scheduler.describe_rule(rule)} / "
                  f"初回 {anchor_dt:%Y-%m-%d %H:%M}")

        def loop():
            fire = anchor_dt
            while not self._stop_sched.is_set():
                self._set(next_timing=fire.isoformat(), status="scheduled",
                          message=f"次回 {fire:%Y-%m-%d %H:%M} に実行予定")
                while datetime.now() < fire:
                    if self._stop_sched.is_set():
                        return
                    remain = int((fire - datetime.now()).total_seconds())
                    self._set(countdown_sec=remain)
                    _time.sleep(min(5, max(1, remain)))
                if self._stop_sched.is_set():
                    return
                self._set(countdown_sec=None)
                self._run_timing(plan, dry_run)
                # 中断された場合はフラグを解除し、次回予定は継続する
                if self._cancel.is_set():
                    self._cancel.clear()
                    self._log("現在の回を中断しました。次回予定は継続します。")
                nxt = scheduler.next_timing(rule, after=fire, anchor=anchor)
                if nxt is None:
                    self._log("次回タイミングが算出できませんでした。自動実行を終了します。")
                    break
                fire = nxt
            self._set(status="idle", message="自動実行を停止しました", next_timing=None)

        self._sched_thread = threading.Thread(target=loop, daemon=True)
        self._sched_thread.start()
        return True, "自動実行を設定しました。"

    def stop_auto(self):
        self._stop_sched.set()
        if self._sched_thread and self._sched_thread.is_alive():
            self._sched_thread.join(timeout=2)
        self._set(status="idle", mode=None, schedule=None,
                  next_timing=None, countdown_sec=None,
                  message="自動実行を停止しました")
        return True, "自動実行を停止しました。"

    def cancel_current(self):
        self._cancel.set()
        self._log("中断要求を受け付けました（現在の回の区切りで停止します）")
        return True, "中断要求を送信しました。"


JOBS = JobManager()


# ================================================================== #
# HTTP ハンドラ
# ================================================================== #
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # 標準のアクセスログを抑制

    # ---- 応答ヘルパー ---- #
    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path: Path, ctype: str):
        if not path.exists():
            self._json({"error": "not found"}, 404)
            return
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        length = int(self.headers.get("Content-Length", 0))
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            return {}

    # ---- GET ---- #
    def do_GET(self):
        u = urlparse(self.path)
        p = u.path
        if p in ("/", "/index.html"):
            return self._file(WEB_DIR / "index.html", "text/html; charset=utf-8")
        if p == "/app.js":
            return self._file(WEB_DIR / "app.js", "application/javascript; charset=utf-8")
        if p == "/style.css":
            return self._file(WEB_DIR / "style.css", "text/css; charset=utf-8")

        if p == "/api/models":
            _, all_models, _ = runner.load_config()
            return self._json({"models": all_models,
                               "has_jpholiday": scheduler.has_jpholiday()})
        if p == "/api/domains":
            return self._json(self._domains_by_set())
        if p == "/api/state":
            return self._json(JOBS.snapshot())
        if p == "/api/reports":
            return self._json(self._reports_summary())
        if p == "/api/dashboard":
            out = DATA_DIR / "dashboard.html"
            if not out.exists():
                try:
                    dashboard.render(REPORTS_DIR, out)
                except Exception:
                    pass
            return self._file(out, "text/html; charset=utf-8")
        if p == "/api/preview_schedule":
            return self._json(self._preview_schedule(parse_qs(u.query)))
        if p == "/api/export":
            return self._export(parse_qs(u.query))
        return self._json({"error": "unknown endpoint"}, 404)

    # ---- POST ---- #
    def do_POST(self):
        p = urlparse(self.path).path
        b = self._body()
        if p == "/api/run":
            plan = self._plan_from(b)
            delay = int(b.get("start", {}).get("minutes", 0)) \
                if b.get("start", {}).get("type") == "after_minutes" else 0
            ok, msg = JOBS.start_manual(plan, delay_min=delay,
                                        dry_run=bool(b.get("dry_run")))
            return self._json({"ok": ok, "message": msg})
        if p == "/api/schedule":
            plan = self._plan_from(b)
            rule = b.get("frequency", {})
            offset = int(b.get("start", {}).get("minutes", 0)) \
                if b.get("start", {}).get("type") == "after_minutes" else 0
            ok, msg = JOBS.start_auto(plan, rule, offset_min=offset,
                                      dry_run=bool(b.get("dry_run")))
            return self._json({"ok": ok, "message": msg})
        if p == "/api/schedule/stop":
            ok, msg = JOBS.stop_auto()
            return self._json({"ok": ok, "message": msg})
        if p == "/api/cancel":
            ok, msg = JOBS.cancel_current()
            return self._json({"ok": ok, "message": msg})
        return self._json({"error": "unknown endpoint"}, 404)

    # ---- プラン整形 ---- #
    def _plan_from(self, b):
        qset = b.get("question_set", "set1")
        if qset not in ("set1", "set2", "both"):
            qset = "set1"
        return {
            "models": b.get("models", []),
            "domain": b.get("domain") or None,
            "question_set": qset,
            "repeat": b.get("repeat", {"type": "once"}),
            "mode":   b.get("mode", "manual"),
        }

    # ---- 質問セット別の事業ドメイン一覧 ---- #
    def _domains_by_set(self):
        """各質問セット（set1/set2/both）に実在する axis_domain を、
        質問ファイルから動的に抽出して返す（GUIのドメイン絞り込み用）。"""
        out = {}
        for s in ("set1", "set2", "both"):
            try:
                qs = runner.load_questions(s)
            except Exception:
                qs = []
            seen, order = {}, []
            for q in qs:
                c = q.get("axis_domain")
                if c and c not in seen:
                    seen[c] = q.get("domain_label", c)
                    order.append(c)
            out[s] = [{"code": c, "label": seen[c]} for c in order]
        return {"domains": out}

    # ---- レポート一覧サマリー ---- #
    def _reports_summary(self):
        idx = []
        idx_path = REPORTS_DIR / "index.json"
        if idx_path.exists():
            try:
                idx = json.loads(idx_path.read_text(encoding="utf-8"))
            except Exception:
                idx = []
        trend = {}
        tp = REPORTS_DIR / "trend.json"
        if tp.exists():
            try:
                trend = json.loads(tp.read_text(encoding="utf-8"))
            except Exception:
                trend = {}
        return {"index": list(reversed(idx)),
                "insights": trend.get("insights", []),
                "deltas": trend.get("deltas", {}),
                "latest": trend.get("latest")}

    # ---- 次回タイミングのプレビュー ---- #
    def _preview_schedule(self, q):
        try:
            rule = json.loads(q.get("rule", ["{}"])[0])
        except Exception:
            rule = {}
        offset = int(q.get("offset", ["0"])[0] or 0)
        anchor_dt = datetime.now() + timedelta(minutes=offset)
        anchor = anchor_dt.date()
        out = [anchor_dt.strftime("%Y-%m-%d %H:%M") + "（初回）"]
        after = anchor_dt
        for _ in range(4):
            nxt = scheduler.next_timing(rule, after=after, anchor=anchor)
            if not nxt:
                break
            out.append(nxt.strftime("%Y-%m-%d %H:%M"))
            after = nxt
        return {"desc": scheduler.describe_rule(rule), "next": out}

    # ---- CSVエクスポート（rowデータ） ---- #
    def _export(self, q):
        scope = q.get("scope", ["all"])[0]
        tid = q.get("id", [""])[0]
        files = sorted(RESULTS_DIR.glob("results_*.csv"))
        if scope == "timing" and tid:
            files = [f for f in files if f.stem.startswith(f"results_{tid}")]

        # 全ファイルを読み込み、列の和集合をとってからヘッダを確定する。
        # （旧フォーマット19列と新フォーマット21列が混在しても、新列
        #  question_set / specificity_tier を取りこぼさない。旧行は空欄補完）
        all_rows = []
        extra_cols = []            # FIELDNAMES 外の列があれば末尾に追加
        base_cols = list(logger.FIELDNAMES)
        for f in files:
            source = f.stem.replace("results_", "")
            try:
                with open(f, encoding="utf-8-sig", newline="") as fh:
                    for row in csv.DictReader(fh):
                        row["source_run"] = source
                        for k in row.keys():
                            if k not in base_cols and k != "source_run" and k not in extra_cols:
                                extra_cols.append(k)
                        all_rows.append(row)
            except Exception:
                continue

        cols = ["source_run"] + base_cols + extra_cols
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
        writer.writeheader()
        for row in all_rows:
            writer.writerow({k: row.get(k, "") for k in cols})
        data = "﻿" + buf.getvalue()      # UTF-8 BOM
        body = data.encode("utf-8")
        fname = f"export_{scope}_{datetime.now():%Y%m%d_%H%M%S}.csv"
        self.send_response(200)
        self.send_header("Content-Type", "text/csv; charset=utf-8")
        self.send_header("Content-Disposition", f'attachment; filename="{fname}"')
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _find_port(start=8765, tries=20):
    import socket
    for port in range(start, start + tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex((HOST, port)) != 0:
                return port
    return start


def main():
    port = _find_port()
    url = f"http://{HOST}:{port}/"
    httpd = ThreadingHTTPServer((HOST, port), Handler)
    print("=" * 56)
    print("  AI出現モニタリング GUI を起動しました")
    print(f"  ブラウザで開いてください： {url}")
    print("  ※ この画面（ウィンドウ）を閉じると自動実行も停止します")
    print("=" * 56)
    try:
        webbrowser.open(url)
    except Exception:
        pass
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n終了します。")


if __name__ == "__main__":
    main()
