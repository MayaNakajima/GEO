"""
Google 検索チェック（毎月・人が検索 → ブックマークレットで記録）
────────────────────────────────────────────────
設計：Google参考値観測_設計_v1.md §5。

  - 毎月、全設問の「設問文」と「観測キーワード」（config/google_keywords.csv）を Google で検索する。
  - 検索するのは人。ブックマークレットが表示中の検索結果ページから上位10件の表示ドメイン・タイトルと
    AI による概要（AI Overview）の有無・引用元を抜き出し、この GUI（127.0.0.1）に渡す。
  - 自社・競合の判定と保存はここで行う。プログラムから Google に検索を送ることはしない（利用規約のため）。

保存：data/google_check/google_check_YYYY-MM.csv（1行＝その月の1検索語。同じ検索語を記録し直すと上書き）。

使い方（CLI・確認用）：
    python src/google_check.py            # 今月の進捗を表示
    python src/google_check.py --month 2026-10
────────────────────────────────────────────────
"""

import argparse
import csv
import io
import json
import sys
import threading
import unicodedata
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, quote_plus

BASE_DIR   = Path(__file__).parent.parent          # monitoring/
CONFIG_DIR = BASE_DIR / "config"
DATA_DIR   = BASE_DIR / "data" / "google_check"
WEB_DIR    = BASE_DIR / "webapp"
KEYWORDS_CSV   = CONFIG_DIR / "google_keywords.csv"
COMPETITOR_DOM = CONFIG_DIR / "google_competitor_domains.json"
DETECTION_JSON = CONFIG_DIR / "detection_keywords.json"
QUESTION_FILES = [("set1", CONFIG_DIR / "questions.json"), ("set2", CONFIG_DIR / "questions_set2.json")]

# 自社ドメイン（detection_keywords.json の domain_urls に加えて）
EXTRA_OWN_DOMAINS = ["onward-raffiria.shop"]
TOP_N = 10

COLUMNS = ["月", "観測日時", "検索語", "種別", "設問ID", "自社最高順位", "自社URL", "AI Overview",
           "AIO自社引用", "AIO引用元", "競合（上位10件内）", "上位10件", "記録方法", "メモ"]

_lock = threading.Lock()


def norm(s):
    return " ".join(unicodedata.normalize("NFKC", str(s or "")).lower().split())


def this_month():
    return datetime.now().strftime("%Y-%m")


def _read_text(path):
    raw = Path(path).read_bytes()
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:          # Excel で上書き保存すると cp932 になる
        return raw.decode("cp932", errors="replace")


# ────────────────────────────────────────────────────────────────
# 検索リスト（その月に検索する語の一覧）
# ────────────────────────────────────────────────────────────────
def load_keywords():
    if not KEYWORDS_CSV.exists():
        return {}
    out = {}
    for r in csv.DictReader(io.StringIO(_read_text(KEYWORDS_CSV))):
        qid = (r.get("設問ID") or "").strip()
        if qid:
            out[qid] = (r.get("観測キーワード") or "").strip()
    return out


def build_terms():
    """[{term, n, kinds:[設問文|キーワード], qids:[...], domain_label}]（重複する語は1つにまとめる）"""
    kw = load_keywords()
    items, index = [], {}

    def add(term, kind, qid, label):
        n = norm(term)
        if not n:
            return
        if n not in index:
            index[n] = {"term": term.strip(), "n": n, "kinds": [], "qids": [], "domain_label": label}
            items.append(index[n])
        it = index[n]
        if kind not in it["kinds"]:
            it["kinds"].append(kind)
        if qid not in it["qids"]:
            it["qids"].append(qid)

    for _set, path in QUESTION_FILES:
        if not path.exists():
            continue
        for q in json.loads(path.read_text(encoding="utf-8")):
            qid, label = q.get("id", ""), q.get("domain_label", "")
            add(q.get("question", ""), "設問文", qid, label)
            if kw.get(qid):
                add(kw[qid], "キーワード", qid, label)
    return items


def search_url(term):
    return "https://www.google.com/search?q=" + quote_plus(term) + "&hl=ja&gl=jp"


# ────────────────────────────────────────────────────────────────
# 自社・競合の判定
# ────────────────────────────────────────────────────────────────
def own_domains():
    doms = set(EXTRA_OWN_DOMAINS)
    try:
        d = json.loads(DETECTION_JSON.read_text(encoding="utf-8"))
        for lst in (d.get("domain_urls") or {}).values():
            doms.update(lst)
    except Exception:
        pass
    return sorted({x.lower().strip() for x in doms if x})


def competitor_domains():
    """{ドメイン: 会社名}"""
    try:
        d = json.loads(COMPETITOR_DOM.read_text(encoding="utf-8"))
    except Exception:
        return {}
    out = {}
    for c in d.get("competitors", []):
        for dom in c.get("domains", []):
            if dom:
                out[dom.lower().strip()] = c.get("canonical", dom)
    return out


def host_of(s):
    """'https://www.clasic.jp › journal' / 'www.clasic.jp' / URL → 'www.clasic.jp'"""
    s = str(s or "").strip().split("›")[0].strip()
    if "://" in s:
        s = s.split("://", 1)[1]
    return s.split("/")[0].split("?")[0].split(":")[0].lower().strip(" .")


def match_domain(host, domains):
    host = host_of(host)
    for d in domains:
        if host == d or host.endswith("." + d):
            return d
    return None


def judge(results, aio_links):
    own = own_domains()
    comp = competitor_domains()
    own_rank, own_url = "", ""
    comps = []
    for r in results:
        h = host_of(r.get("host") or r.get("url"))
        if not own_rank and match_domain(h, own):
            own_rank, own_url = r["rank"], r.get("url") or h
        d = match_domain(h, comp)
        if d and comp[d] not in comps:
            comps.append(comp[d])
    aio_hosts = []
    for a in aio_links:
        h = host_of(a.get("host") or a.get("url"))
        if h and h not in aio_hosts:
            aio_hosts.append(h)
    aio_own = any(match_domain(h, own) for h in aio_hosts)
    return own_rank, own_url, comps, aio_hosts, aio_own


# ────────────────────────────────────────────────────────────────
# 保存・読み込み
# ────────────────────────────────────────────────────────────────
def data_path(month):
    return DATA_DIR / f"google_check_{month}.csv"


def load_records(month):
    p = data_path(month)
    if not p.exists():
        return {}
    return {norm(r["検索語"]): r for r in csv.DictReader(io.StringIO(_read_text(p)))}


def _write(month, records):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    p = data_path(month)
    tmp = p.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        for r in records.values():
            w.writerow({k: r.get(k, "") for k in COLUMNS})
    tmp.replace(p)


def _clean(s, n=300):
    return " ".join(str(s or "").split())[:n]


def save(payload, method="ブックマークレット", month=None):
    """ブックマークレット／手入力の結果を記録する。返り値：画面表示用のまとめ。"""
    month = month or this_month()
    term = _clean(payload.get("q"), 200)
    if not term:
        return {"ok": False, "message": "検索語がありません（Google の検索結果ページで実行してください）"}
    terms = {t["n"]: t for t in build_terms()}
    t = terms.get(norm(term))
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    if method == "手入力":
        rank = str(payload.get("own_rank", "")).strip()
        rank = rank if rank.isdigit() else ("圏外" if rank in ("圏外", "out", "") else rank)
        rec = {"自社最高順位": rank, "自社URL": _clean(payload.get("own_url")),
               "AI Overview": "あり" if payload.get("aio") else "なし",
               "AIO自社引用": "あり" if payload.get("aio_own") else "なし",
               "AIO引用元": "", "競合（上位10件内）": _clean(payload.get("competitors")),
               "上位10件": "[]"}
        n_res = None
    else:
        results = []
        for r in (payload.get("results") or [])[:TOP_N]:
            results.append({"rank": len(results) + 1, "host": host_of(r.get("host") or r.get("url")),
                            "title": _clean(r.get("title"), 120), "url": _clean(r.get("url"), 300)})
        aio = payload.get("aio") or {}
        aio_links = [{"host": host_of(a.get("host") or a.get("url")), "title": _clean(a.get("title"), 120)}
                     for a in (aio.get("links") or [])[:30]]
        own_rank, own_url, comps, aio_hosts, aio_own = judge(results, aio_links)
        rec = {"自社最高順位": own_rank if own_rank else "圏外", "自社URL": own_url,
               "AI Overview": "あり" if aio.get("present") else "なし",
               "AIO自社引用": "あり" if aio_own else "なし",
               "AIO引用元": ";".join(aio_hosts), "競合（上位10件内）": ";".join(comps),
               "上位10件": json.dumps([[r["rank"], r["host"], r["title"]] for r in results], ensure_ascii=False)}
        n_res = len(results)

    rec.update({"月": month, "観測日時": now, "検索語": t["term"] if t else term,
                "種別": "・".join(t["kinds"]) if t else "リスト外",
                "設問ID": ";".join(t["qids"]) if t else "", "記録方法": method,
                "メモ": _clean(payload.get("memo"))})
    with _lock:
        recs = load_records(month)
        recs[norm(rec["検索語"])] = rec
        # 一覧の順番で並べ直す（リスト外は末尾）
        order = [x["n"] for x in build_terms()]
        recs = dict(sorted(recs.items(), key=lambda kv: order.index(kv[0]) if kv[0] in order else 10 ** 6))
        _write(month, recs)
    st = state(month)
    warn = ""
    if n_res == 0:
        warn = ("検索結果を1件も読み取れませんでした（Google の画面が変わった可能性があります）。"
                "GUI の「手入力」で記録し直してください。")
    return {"ok": True, "month": month, "term": rec["検索語"], "listed": bool(t),
            "own_rank": rec["自社最高順位"], "aio": rec["AI Overview"], "aio_own": rec["AIO自社引用"],
            "competitors": rec["競合（上位10件内）"], "n_results": n_res, "warning": warn,
            "done": st["done"], "total": st["total"], "next_url": st["next_url"]}


def delete(term, month=None):
    month = month or this_month()
    with _lock:
        recs = load_records(month)
        if recs.pop(norm(term), None) is None:
            return {"ok": False, "message": "記録がありません"}
        _write(month, recs)
    return {"ok": True}


def state(month=None):
    month = month or this_month()
    recs = load_records(month)
    items = []
    next_url = None
    for t in build_terms():
        r = recs.get(t["n"])
        if not r and next_url is None:
            next_url = search_url(t["term"])
        items.append({"term": t["term"], "kinds": t["kinds"], "qids": t["qids"], "domain_label": t["domain_label"],
                      "url": search_url(t["term"]), "done": bool(r),
                      "own_rank": r["自社最高順位"] if r else "", "aio": r["AI Overview"] if r else "",
                      "aio_own": r["AIO自社引用"] if r else "", "competitors": r["競合（上位10件内）"] if r else "",
                      "observed_at": r["観測日時"] if r else "", "method": r["記録方法"] if r else ""})
    months = sorted({p.stem.replace("google_check_", "") for p in DATA_DIR.glob("google_check_*.csv")} | {month},
                    reverse=True)
    done = sum(1 for i in items if i["done"])
    return {"month": month, "months": months, "total": len(items), "done": done, "items": items,
            "next_url": next_url, "file": str(data_path(month))}


# ────────────────────────────────────────────────────────────────
# ブックマークレット
# ────────────────────────────────────────────────────────────────
def bookmarklet(port):
    """webapp/bookmarklet.js の __RECEIVER__ を差し込み、javascript: URL にして返す。"""
    src = (WEB_DIR / "bookmarklet.js").read_text(encoding="utf-8")
    lines = []
    for ln in src.splitlines():
        s = ln.strip()
        if not s or s.startswith("//"):
            continue
        lines.append(s)
    code = " ".join(lines).replace("__RECEIVER__", f"http://127.0.0.1:{port}/gc/receive")
    return "javascript:" + quote(code, safe="()=;,:/?&'+*!~._-[]{}<>|$@")


def main():
    ap = argparse.ArgumentParser(description="Google 検索チェックの進捗")
    ap.add_argument("--month", default=None, help="YYYY-MM（省略時は今月）")
    a = ap.parse_args()
    st = state(a.month)
    print(f"{st['month']}：{st['done']} / {st['total']} 件記録済み（{st['file']}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
