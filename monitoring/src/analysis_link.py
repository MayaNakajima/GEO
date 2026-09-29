"""
分析ダッシュボード（GEO-analysis）との連携
────────────────────────────────────────────────
関係者向けの入口である GEO-analysis の analysis.html を、定点観測（monitoring）側から
開いたり最新化したりするための共通モジュール。

GEO-analysis のコードには手を入れず、既存の CLI
    python generate.py [--no-share]
を外部プロセスとして呼ぶだけの疎結合にしている（share 有りなら generate.py 自身が
config.json の share_dirs＝Box へコピーする）。

設定: config/analysis_link.json（個人環境のパスを含むため .gitignore 済み・Box へも反映しない。
      雛形は analysis_link.json.example）
  ファイルが無い、または enabled=false なら関連機能はすべて無効。

使い方:
    python src/analysis_link.py            # 状態を表示
    python src/analysis_link.py --regen    # analysis.html を再生成（Box へも反映）
    python src/analysis_link.py --regen --no-share
────────────────────────────────────────────────
"""

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

BASE_DIR  = Path(__file__).parent.parent          # monitoring/
CONF_PATH = BASE_DIR / "config" / "analysis_link.json"
LOG_PATH  = BASE_DIR / "data" / "analysis_link.log"

DEFAULT_TIMEOUT_SEC = 180
TAIL_CHARS = 600

# GUI の二重クリックや自動実行と重なっても generate.py を同時に走らせない
_regen_lock = threading.Lock()


def _expand(p) -> Path | None:
    if not p:
        return None
    return Path(os.path.expandvars(os.path.expanduser(str(p))))


def load_conf(path: Path = CONF_PATH) -> dict | None:
    """設定を読み込みパスを解決する。無い／enabled=false／読めない場合は None。"""
    try:
        if not path.exists():
            return None
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not raw.get("enabled", True):
        return None
    repo = _expand(raw.get("analysis_repo"))
    try:
        timeout = int(raw.get("timeout_sec", DEFAULT_TIMEOUT_SEC))
    except Exception:
        timeout = DEFAULT_TIMEOUT_SEC
    return {
        "analysis_repo": repo,
        "generate_py":   repo / raw.get("generate_py", "generate.py") if repo else None,
        "analysis_html": repo / raw.get("analysis_html", "analysis.html") if repo else None,
        "fallback_html": _expand(raw.get("fallback_html")),
        "regenerate_on_open": bool(raw.get("regenerate_on_open", True)),
        "regenerate_after_scheduled_run": bool(raw.get("regenerate_after_scheduled_run", True)),
        "timeout_sec": timeout,
    }


def disabled_reason(path: Path = CONF_PATH) -> str:
    """load_conf() が None を返す理由（GUI のツールチップ用）。"""
    if not path.exists():
        return f"config/{path.name} がありません（{path.name}.example をコピーして作成してください）"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        return f"config/{path.name} を読み込めません：{e}"
    if not raw.get("enabled", True):
        return f"config/{path.name} で enabled=false になっています"
    return ""


def can_regenerate(conf: dict | None) -> bool:
    return bool(conf and conf["generate_py"] and conf["generate_py"].is_file())


def _write_log(line: str):
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {line}\n")
    except Exception:
        pass


def _tail(s: str) -> str:
    s = (s or "").replace("\r", "").strip()
    return s[-TAIL_CHARS:]


def regenerate(share: bool = True, conf: dict | None = None, log=None) -> dict:
    """generate.py を実行して analysis.html を作り直す。失敗しても例外は投げない。

    返り値: {"ok", "message", "returncode", "elapsed_sec", "stdout_tail", "stderr_tail"}
    """
    conf = conf if conf is not None else load_conf()
    res = {"ok": False, "message": "", "returncode": None, "elapsed_sec": 0,
           "stdout_tail": "", "stderr_tail": ""}
    if conf is None:
        res["message"] = "分析ダッシュボード連携は無効です（" + disabled_reason() + "）"
        return res
    if not can_regenerate(conf):
        res["message"] = f"GEO-analysis が見つかりません（{conf['generate_py']}）"
        _write_log("再生成スキップ: " + res["message"])
        return res

    cmd = [sys.executable, str(conf["generate_py"])]
    if not share:
        cmd.append("--no-share")
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    t0 = time.time()
    with _regen_lock:
        try:
            p = subprocess.run(cmd, cwd=str(conf["analysis_repo"]), env=env,
                               capture_output=True, timeout=conf["timeout_sec"],
                               stdin=subprocess.DEVNULL)
            res["returncode"] = p.returncode
            res["stdout_tail"] = _tail(p.stdout.decode("utf-8", "replace"))
            res["stderr_tail"] = _tail(p.stderr.decode("utf-8", "replace"))
            res["ok"] = p.returncode == 0
            res["message"] = ("再生成しました" if res["ok"]
                              else f"generate.py が終了コード {p.returncode} で失敗しました")
        except subprocess.TimeoutExpired:
            res["message"] = f"generate.py が {conf['timeout_sec']} 秒以内に終わりませんでした（タイムアウト）"
        except Exception as e:
            res["message"] = f"generate.py を起動できませんでした：{e}"
    res["elapsed_sec"] = round(time.time() - t0, 1)

    summary = (f"再生成{'（Box反映あり）' if share else '（Box反映なし）'}: "
               f"{'成功' if res['ok'] else '失敗'} / {res['message']} / "
               f"rc={res['returncode']} / {res['elapsed_sec']}秒")
    _write_log(summary)
    if res["stdout_tail"]:
        _write_log("  stdout(末尾): " + res["stdout_tail"].replace("\n", " | "))
    if res["stderr_tail"]:
        _write_log("  stderr(末尾): " + res["stderr_tail"].replace("\n", " | "))
    if log:
        log("分析ダッシュボード " + summary)
    return res


def resolve_html(conf: dict | None = None) -> tuple[Path | None, str | None]:
    """開く HTML を決める。(パス, "local"|"box") または (None, None)。"""
    conf = conf if conf is not None else load_conf()
    if conf is None:
        return None, None
    if conf["analysis_html"] and conf["analysis_html"].is_file():
        return conf["analysis_html"], "local"
    if conf["fallback_html"] and conf["fallback_html"].is_file():
        return conf["fallback_html"], "box"
    return None, None


def status() -> dict:
    """GUI 表示用の状態。"""
    conf = load_conf()
    if conf is None:
        return {"available": False, "reason": disabled_reason()}
    html, source = resolve_html(conf)
    mtime = None
    if html:
        mtime = datetime.fromtimestamp(html.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
    return {
        "available": True,
        "reason": "",
        "can_regenerate": can_regenerate(conf),
        "regenerate_on_open": conf["regenerate_on_open"],
        "html": str(html) if html else None,
        "source": source,              # local | box | None
        "mtime": mtime,
        "analysis_repo": str(conf["analysis_repo"]) if conf["analysis_repo"] else None,
        "fallback_html": str(conf["fallback_html"]) if conf["fallback_html"] else None,
    }


# ------------------------------------------------------------------ #
# dashboard.html / insights.html のヘッダーに入れるリンク帯
# ------------------------------------------------------------------ #
def link_band_html(theme: str = "dark") -> str:
    """「関係者向けの分析・示唆は 分析ダッシュボード へ」のリンク帯。設定が無ければ空文字。

    GUI（http）経由で表示しているときは /api/analysis、ファイルを直接開いたときは
    fallback_html（Box 上の analysis.html）への file:/// リンクにする。
    """
    conf = load_conf()
    if conf is None:
        return ""
    fb = conf["fallback_html"]
    file_url = fb.as_uri() if fb and fb.is_absolute() else ""
    if theme == "dark":
        style = ("background:#0b1220;border-bottom:1px solid #334155;color:#94a3b8;"
                 "padding:8px 28px;font-size:13px")
        a_style = "color:#38bdf8;font-weight:700"
    else:
        style = ("background:#eef4ff;border:1px solid #c7d7fe;color:#374151;border-radius:10px;"
                 "padding:8px 14px;font-size:13px;margin:0 0 16px")
        a_style = "color:#2563eb;font-weight:700"
    return (
        f'<div id="analysis-link-band" style="{style}">🔎 関係者向けの分析・示唆は '
        f'<a id="analysis-link" href="/api/analysis" target="_blank" style="{a_style}">'
        f'分析ダッシュボード</a> へ</div>\n'
        "<script>(function(){var f=" + json.dumps(file_url) + ";"
        "if(location.protocol==='file:'){var a=document.getElementById('analysis-link');"
        "if(f){a.href=f;}else{document.getElementById('analysis-link-band').style.display='none';}}"
        "})();</script>\n")


def main():
    ap = argparse.ArgumentParser(description="分析ダッシュボード（GEO-analysis）連携")
    ap.add_argument("--regen", action="store_true", help="analysis.html を再生成する")
    ap.add_argument("--no-share", action="store_true", help="Box へのコピーを行わない")
    args = ap.parse_args()
    if args.regen:
        r = regenerate(share=not args.no_share, log=print)
        return 0 if r["ok"] else 1
    print(json.dumps(status(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
