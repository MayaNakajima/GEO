"""
示唆レポート（1枚もの）生成モジュール
────────────────────────────────────────────────────────────────────
GEOモニタリング結果 → 「コンテンツ改善の示唆」へ変換する Tier1.5 レポート。

出力する3ブロック:
  1) 弱いセルランキング … 出現率が低い「事業ドメイン × 質問タイプ（× ステークホルダー）」
                         セルを、母数と失敗モデルつきで弱い順に並べる
  2) 非出現回答の競合/観点抽出 … 自社が出なかった回答本文から、
       ・代わりに挙がっている競合（辞書＋別名。未登録の頻出エンティティも候補提示）
       ・AIが評価軸にしている観点（属性語彙）
       ・引用されているドメイン
     を集計する
  3) 改善アクション案 … 弱いセルの質問タイプ × 競合が勝っている観点 から
                       具体的なコンテンツ施策を自動生成する

抽出方式:
  DictionaryExtractor（既定・方式a）… 決定論的・APIコストゼロ・定期実行に安全。
  方式b（LLM抽出）を足したい場合は Extractor を差し替えるだけ（末尾のフック参照）。

スタンドアロン実行:
    python src/insight_report.py                 # 最新の results CSV から生成
    python src/insight_report.py --csv <path>    # 指定CSVから生成
    python src/insight_report.py --open          # 生成後ブラウザで開く
出力: data/insights.html （＋ data/reports/insights_<stem>.json）
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import webbrowser
from collections import Counter, defaultdict
from datetime import datetime
from html import escape
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
CONFIG_DIR = BASE / "config"
DATA_DIR = BASE / "data"
RESULTS_DIR = DATA_DIR / "results"
REPORTS_DIR = DATA_DIR / "reports"


# ================================================================== #
# 入力の正規化（CSV文字列 / メモリ内dict どちらでも動く）
# ================================================================== #
def _to_bool(v) -> bool:
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("true", "1", "yes")


def normalize_rows(rows: list) -> list:
    """CSV由来（文字列）でもランナー由来（bool）でも同じ形にそろえる。"""
    out = []
    for r in rows:
        d = dict(r)
        d["mention_detected"] = _to_bool(d.get("mention_detected"))
        d["abm_relevant"] = _to_bool(d.get("abm_relevant"))
        for k in ("answer", "question", "domain_label", "type_label",
                  "stakeholder_label", "model_name", "question_id",
                  "urls_found", "entities_found", "specificity_tier"):
            d.setdefault(k, "")
            if d[k] is None:
                d[k] = ""
        out.append(d)
    return out


def load_latest_csv(results_dir: Path = RESULTS_DIR) -> Path | None:
    files = sorted(results_dir.glob("results_*.csv"))
    return files[-1] if files else None


def read_csv_rows(path: Path) -> list:
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


# ================================================================== #
# 抽出器（方式a: 辞書ベース）
# ================================================================== #
# 会社サフィックス／強調表現から「エンティティ候補」を拾う正規表現
_COMPANY_PAT = re.compile(
    r"(?:株式会社|有限会社|合同会社)?\s*"
    r"([一-龠ぁ-んァ-ヴA-Za-z0-9][一-龠ぁ-んァ-ヴA-Za-z0-9・ーＡ-Ｚａ-ｚ]{1,20})"
    r"\s*(?:株式会社|\(株\)|（株）)?"
)
# **太字** / 【見出し】 で強調されたトークン（AIが候補として列挙する典型形）
_BOLD_PAT = re.compile(r"\*\*(.+?)\*\*|【(.+?)】|「(.+?)」")
_URL_PAT = re.compile(r"https?://([A-Za-z0-9.\-]+)")
_DOMAIN_PAT = re.compile(r"([a-z0-9\-]+(?:\.[a-z0-9\-]+)+\.(?:co\.jp|jp|com|net|shop))")

# 競合ではないので除外する語（素材メーカー・異業種事例・自社）
_OWN = ("オンワード", "onward", "raffiria", "ラフィーリア")


class DictionaryExtractor:
    """方式a: 競合辞書＋属性語彙による決定論的抽出。"""

    def __init__(self, competitors_cfg: dict):
        self.attributes = competitors_cfg.get("attributes", {})
        # alias(lower) -> canonical
        self.alias_map = {}
        self.known_aliases = set()
        for c in competitors_cfg.get("competitors", []):
            canon = c["canonical"]
            for a in c.get("aliases", []):
                self.alias_map[a.lower()] = canon
                self.known_aliases.add(a.lower())
        # 属性語（観点）はエンティティ候補から除外するための集合
        self._attr_words = set()
        for kws in self.attributes.values():
            for kw in kws:
                self._attr_words.add(kw.lower())
        self._attr_words |= {k.lower() for k in self.attributes.keys()}

    def competitors(self, text: str) -> list:
        """本文に登場する既知競合（canonical名）を返す。"""
        low = text.lower()
        found = []
        for alias_low, canon in self.alias_map.items():
            if alias_low and alias_low in low:
                found.append(canon)
        return sorted(set(found))

    def attributes_in(self, text: str) -> list:
        """本文が触れている評価観点を返す。"""
        hits = []
        for label, kws in self.attributes.items():
            if any(kw in text for kw in kws):
                hits.append(label)
        return hits

    def domains(self, text: str) -> list:
        doms = set(_URL_PAT.findall(text)) | set(_DOMAIN_PAT.findall(text))
        return sorted(d for d in doms if not any(o in d.lower() for o in _OWN))

    def unknown_entities(self, text: str) -> list:
        """辞書未登録だが強調表現で列挙されている候補（＝新規競合の芽）。"""
        cands = set()
        for m in _BOLD_PAT.finditer(text):
            tok = next((g for g in m.groups() if g), "").strip()
            tok = re.sub(r"[（(].*?[)）]", "", tok).strip()  # 括弧内の読みを除去
            tok = tok.split("：")[0].split(":")[0].strip()
            if not (2 <= len(tok) <= 22):
                continue
            low = tok.lower()
            if low in self.alias_map:
                continue
            # 既知競合に社名接頭辞などが付いた重複（例: 株式会社ボンマックス）を除外
            if any(a in low or low in a for a in self.alias_map):
                continue
            if any(o in low for o in _OWN):
                continue
            # 評価観点の語はエンティティではないので除外（例: アフターサポート）
            if low in self._attr_words or any(w in low for w in self._attr_words):
                continue
            # 明らかな一般語/見出しは除外（記号・数字のみ、助詞始まり等）
            if re.fullmatch(r"[0-9〜~\-.,%％ 　]+", tok):
                continue
            cands.add(tok)
        return sorted(cands)


# ================================================================== #
# 集計本体
# ================================================================== #
def _cell_key(r: dict) -> tuple:
    return (r.get("domain_label", "") or "－",
            r.get("type_label", "") or "－")


def _rate(detected: int, total: int) -> float:
    return round(detected / total * 100, 1) if total else 0.0


def build_insight_report(rows: list, extractor: DictionaryExtractor,
                         source_label: str = "", top_cells: int = 12) -> dict:
    rows = normalize_rows(rows)
    total_rows = len(rows)
    detected_rows = [r for r in rows if r["mention_detected"]]
    nd_rows = [r for r in rows if not r["mention_detected"]]

    # ---- (1) 弱いセルランキング（ドメイン×タイプ） ---- #
    cells = defaultdict(lambda: {"total": 0, "detected": 0,
                                 "fail_models": Counter(),
                                 "questions": set(), "nd_answers": []})
    for r in rows:
        c = cells[_cell_key(r)]
        c["total"] += 1
        if r["mention_detected"]:
            c["detected"] += 1
        else:
            c["fail_models"][r.get("model_name", "")] += 1
            c["questions"].add(r.get("question", "")[:60])
            if r.get("answer"):
                c["nd_answers"].append(r["answer"])

    cell_list = []
    for (dom, typ), c in cells.items():
        cell_list.append({
            "domain": dom, "type": typ,
            "total": c["total"], "detected": c["detected"],
            "rate": _rate(c["detected"], c["total"]),
            "miss": c["total"] - c["detected"],
            "fail_models": c["fail_models"].most_common(),
            "sample_questions": sorted(c["questions"])[:3],
            "_nd_answers": c["nd_answers"],
        })
    # 弱い順（出現率昇順 → 母数が大きい＝影響大を優先）
    cell_list.sort(key=lambda x: (x["rate"], -x["total"]))
    weak_cells = cell_list[:top_cells]

    # ---- (2) 非出現回答の競合/観点/ドメイン抽出（全体） ---- #
    comp_counter = Counter()
    attr_counter = Counter()
    domain_counter = Counter()
    unknown_counter = Counter()
    # 競合 × 観点（その競合が語られる文脈で挙がる観点）
    for r in nd_rows:
        ans = r.get("answer", "") or ""
        if not ans:
            continue
        comps = extractor.competitors(ans)
        attrs = extractor.attributes_in(ans)
        for c in comps:
            comp_counter[c] += 1
        for a in attrs:
            attr_counter[a] += 1
        dom_src = ans + " " + (r.get("urls_found", "") or "")
        for d in extractor.domains(dom_src):
            domain_counter[d] += 1
        for u in extractor.unknown_entities(ans):
            unknown_counter[u] += 1

    extraction = {
        "nd_count": len(nd_rows),
        "competitors": comp_counter.most_common(15),
        "attributes": attr_counter.most_common(12),
        "domains": domain_counter.most_common(12),
        "unknown_entities": [u for u in unknown_counter.most_common(20) if u[1] >= 2],
    }

    # ---- (3) 改善アクション案（弱いセル × 観点） ---- #
    actions = _build_actions(weak_cells, extractor, extraction)

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": source_label,
        "summary": {
            "total": total_rows,
            "detected": len(detected_rows),
            "overall_rate": _rate(len(detected_rows), total_rows),
            "nd_count": len(nd_rows),
        },
        "weak_cells": [{k: v for k, v in c.items() if k != "_nd_answers"}
                       for c in weak_cells],
        "extraction": extraction,
        "actions": actions,
    }


# 質問タイプ → コンテンツ施策のテンプレ
_TYPE_PLAYBOOK = {
    "業者推薦型": "候補として想起されるための「会社比較・選定ガイド」ページを整備。"
                "自社の強みを第三者視点の一覧に載る形（実績数・対応業種・ロット）で明示する。",
    "課題解決型": "課題起点のノウハウ記事（○○の解決方法）を作り、その中で自社サービスを解決策として提示する。",
    "比較・選定型": "比較表・選定チェックリストを持つページを用意し、評価軸ごとに自社の値を埋めた表を掲載する。",
    "トレンド・市場情報型": "市場トレンドを語るオウンドメディア記事を出し、自社を業界の情報源として位置づける（E-E-A-T強化）。",
    "事例・実績型": "導入事例ページを増やす。企業名・課題・成果を構造化データつきで掲載する。",
}


def _build_actions(weak_cells: list, extractor: DictionaryExtractor,
                   extraction: dict) -> list:
    top_attrs = [a for a, _ in extraction["attributes"][:5]]
    top_comps = [c for c, _ in extraction["competitors"][:5]]
    actions = []
    for c in weak_cells:
        if c["rate"] >= 50:  # 十分出ているセルは施策対象外
            continue
        # このセルの非出現回答に固有の観点
        joined = "\n".join(c["_nd_answers"]) if c.get("_nd_answers") else ""
        cell_attrs = extractor.attributes_in(joined) if joined else []
        cell_comps = extractor.competitors(joined) if joined else []
        playbook = _TYPE_PLAYBOOK.get(c["type"],
                                      "対象意図に直接答える専用ページを用意する。")
        focus_attrs = cell_attrs[:4] or top_attrs[:4]
        focus_comps = cell_comps[:4] or top_comps[:4]
        actions.append({
            "domain": c["domain"], "type": c["type"],
            "rate": c["rate"], "miss": c["miss"], "total": c["total"],
            "priority": _priority(c),
            "playbook": playbook,
            "cover_attributes": focus_attrs,
            "beating_competitors": focus_comps,
            "text": (f"【{c['domain']}／{c['type']}】出現率{c['rate']}%"
                     f"（{c['miss']}/{c['total']}件で非出現）。"
                     f"{playbook}"
                     + (f" 回答で重視されている観点＝{('・'.join(focus_attrs))}を、"
                        f"該当ページに具体的に記載する。" if focus_attrs else "")
                     + (f" 競合として{('・'.join(focus_comps))}が想起されている。"
                        if focus_comps else "")),
        })
    actions.sort(key=lambda a: {"高": 0, "中": 1, "低": 2}[a["priority"]])
    return actions


def _priority(cell: dict) -> str:
    # 母数が多く出現率が低いほど高優先
    if cell["rate"] <= 10 and cell["total"] >= 4:
        return "高"
    if cell["rate"] <= 30:
        return "中"
    return "低"


# ================================================================== #
# HTML レンダリング（1枚もの・自己完結）
# ================================================================== #
def render_html(report: dict, out_path: Path) -> Path:
    s = report["summary"]
    ex = report["extraction"]

    def bars(items, unit="件"):
        if not items:
            return '<p class="muted">該当なし</p>'
        mx = max(n for _, n in items) or 1
        rows = []
        for name, n in items:
            w = int(n / mx * 100)
            rows.append(
                f'<div class="bar-row"><span class="bar-label">{escape(str(name))}</span>'
                f'<span class="bar-track"><span class="bar-fill" style="width:{w}%"></span></span>'
                f'<span class="bar-val">{n}{unit}</span></div>')
        return "".join(rows)

    # 弱いセル表
    cell_rows = []
    for c in report["weak_cells"]:
        fm = "、".join(f"{m}:{n}" for m, n in c["fail_models"][:3]) or "－"
        qs = "<br>".join("・" + escape(q) for q in c["sample_questions"]) or "－"
        cls = "rate-bad" if c["rate"] <= 10 else ("rate-mid" if c["rate"] <= 30 else "")
        cell_rows.append(
            f"<tr><td>{escape(c['domain'])}</td><td>{escape(c['type'])}</td>"
            f"<td class='num {cls}'>{c['rate']}%</td>"
            f"<td class='num'>{c['detected']}/{c['total']}</td>"
            f"<td class='small'>{escape(fm)}</td>"
            f"<td class='small'>{qs}</td></tr>")

    # アクション
    act_rows = []
    for a in report["actions"]:
        badge = {"高": "p-high", "中": "p-mid", "低": "p-low"}[a["priority"]]
        attrs = "、".join(a["cover_attributes"]) or "－"
        comps = "、".join(a["beating_competitors"]) or "－"
        act_rows.append(
            f"<div class='action'><div class='act-head'>"
            f"<span class='pri {badge}'>{a['priority']}</span>"
            f"<b>{escape(a['domain'])} ／ {escape(a['type'])}</b>"
            f"<span class='muted'>　出現率 {a['rate']}%（非出現 {a['miss']}/{a['total']}）</span></div>"
            f"<div class='act-body'>{escape(a['playbook'])}</div>"
            f"<div class='act-meta'>▸ 記載すべき観点：<b>{escape(attrs)}</b>"
            f"　｜　想起されている競合：<b>{escape(comps)}</b></div></div>")

    unknown = ex.get("unknown_entities", [])
    unknown_html = (bars(unknown) if unknown else
                    '<p class="muted">辞書未登録の頻出エンティティはありません。</p>')

    html = f"""<!doctype html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>GEO 示唆レポート</title>
<style>
:root{{--bg:#f7f8fa;--card:#fff;--ink:#1a2233;--muted:#6b7280;--line:#e5e7eb;
--accent:#2563eb;--bad:#dc2626;--mid:#d97706;--good:#059669;}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);
font-family:"Segoe UI","Hiragino Kaku Gothic ProN","Meiryo",sans-serif;line-height:1.6}}
.wrap{{max-width:1040px;margin:0 auto;padding:28px 20px 60px}}
h1{{font-size:22px;margin:0 0 4px}}h2{{font-size:16px;margin:30px 0 12px;
padding-left:10px;border-left:4px solid var(--accent)}}
.sub{{color:var(--muted);font-size:13px;margin-bottom:18px}}
.kpis{{display:flex;gap:14px;flex-wrap:wrap}}
.kpi{{background:var(--card);border:1px solid var(--line);border-radius:12px;
padding:14px 18px;min-width:140px}}
.kpi .v{{font-size:26px;font-weight:700}}.kpi .l{{font-size:12px;color:var(--muted)}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px 18px}}
.grid2{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}
@media(max-width:760px){{.grid2{{grid-template-columns:1fr}}}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
th,td{{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line);vertical-align:top}}
th{{color:var(--muted);font-weight:600;font-size:12px}}
td.num{{text-align:right;font-variant-numeric:tabular-nums;font-weight:600}}
td.small{{font-size:12px;color:#374151}}
.rate-bad{{color:var(--bad)}}.rate-mid{{color:var(--mid)}}
.bar-row{{display:flex;align-items:center;gap:8px;margin:5px 0;font-size:13px}}
.bar-label{{flex:0 0 40%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.bar-track{{flex:1;background:#eef1f6;border-radius:5px;height:12px;overflow:hidden}}
.bar-fill{{display:block;height:100%;background:var(--accent);border-radius:5px}}
.bar-val{{flex:0 0 46px;text-align:right;color:var(--muted);font-size:12px}}
.action{{border:1px solid var(--line);border-radius:10px;padding:12px 14px;margin:10px 0;background:#fff}}
.act-head{{display:flex;align-items:center;gap:8px;font-size:14px;flex-wrap:wrap}}
.act-body{{margin:6px 0;font-size:13px}}
.act-meta{{font-size:12px;color:#374151;background:#f3f6fb;border-radius:8px;padding:6px 10px}}
.pri{{color:#fff;border-radius:6px;padding:1px 9px;font-size:12px;font-weight:700}}
.p-high{{background:var(--bad)}}.p-mid{{background:var(--mid)}}.p-low{{background:#9ca3af}}
.muted{{color:var(--muted);font-size:13px}}
.note{{font-size:12px;color:var(--muted);margin-top:8px}}
</style></head><body><div class="wrap">
<h1>GEO 示唆レポート — コンテンツ改善の打ち手</h1>
<div class="sub">生成: {escape(report['generated_at'])} ／ 対象: {escape(report['source'] or '-')}
　抽出方式: 辞書ベース（方式a）</div>

<div class="kpis">
<div class="kpi"><div class="v">{s['overall_rate']}%</div><div class="l">全体出現率</div></div>
<div class="kpi"><div class="v">{s['detected']}/{s['total']}</div><div class="l">出現 / 総回答</div></div>
<div class="kpi"><div class="v">{s['nd_count']}</div><div class="l">非出現回答（分析対象）</div></div>
<div class="kpi"><div class="v">{len(report['actions'])}</div><div class="l">改善アクション</div></div>
</div>

<h2>① 弱いセルランキング（事業ドメイン × 質問タイプ）</h2>
<div class="card"><table>
<tr><th>事業ドメイン</th><th>質問タイプ</th><th>出現率</th><th>出現/母数</th>
<th>非出現の多いモデル</th><th>代表質問</th></tr>
{''.join(cell_rows)}
</table><div class="note">出現率が低く母数の大きいセルほど、改善インパクトが大きい。</div></div>

<h2>② 非出現回答から見える「誰に・何で負けているか」</h2>
<div class="grid2">
<div class="card"><b>代わりに挙がっている競合</b>{bars(ex['competitors'])}</div>
<div class="card"><b>AIが評価軸にしている観点</b>{bars(ex['attributes'])}</div>
</div>
<div class="grid2" style="margin-top:16px">
<div class="card"><b>引用されているドメイン</b>{bars(ex['domains'])}</div>
<div class="card"><b>辞書未登録の頻出エンティティ（新規競合の候補）</b>{unknown_html}
<div class="note">2回以上出た未登録語のみ表示。competitors.json への追記候補。</div></div>
</div>

<h2>③ 改善アクション案（優先度つき）</h2>
<div class="card">
{''.join(act_rows) if act_rows else '<p class="muted">出現率50%未満のセルはありません。</p>'}
</div>

<div class="note">※ 競合・観点は方式a（辞書）による自動抽出のため、取りこぼし・誤検出があり得ます。
最終判断は非出現回答の原文確認と併用してください。</div>
</div></body></html>"""

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    return out_path


# ================================================================== #
# 公開API（engine から呼べる） / CLI
# ================================================================== #
def load_competitors_cfg() -> dict:
    p = CONFIG_DIR / "competitors.json"
    if not p.exists():
        return {"competitors": [], "attributes": {}}
    return json.loads(p.read_text(encoding="utf-8"))


def generate_from_rows(rows: list, source_label: str = "",
                       out_html: Path = None, out_json: Path = None) -> dict:
    """engine 等からメモリ内 results で呼ぶ用。"""
    extractor = DictionaryExtractor(load_competitors_cfg())
    report = build_insight_report(rows, extractor, source_label=source_label)
    if out_html:
        render_html(report, Path(out_html))
    if out_json:
        Path(out_json).parent.mkdir(parents=True, exist_ok=True)
        Path(out_json).write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                  encoding="utf-8")
    return report


def main(argv=None):
    ap = argparse.ArgumentParser(description="GEO 示唆レポート生成")
    ap.add_argument("--csv", help="対象の results CSV（省略時は最新）")
    ap.add_argument("--out", help="出力HTMLパス（省略時は data/insights.html）")
    ap.add_argument("--open", action="store_true", help="生成後にブラウザで開く")
    args = ap.parse_args(argv)

    csv_path = Path(args.csv) if args.csv else load_latest_csv()
    if not csv_path or not csv_path.exists():
        print("[insight] results CSV が見つかりません。")
        return 1

    rows = read_csv_rows(csv_path)
    out_html = Path(args.out) if args.out else (DATA_DIR / "insights.html")
    out_json = REPORTS_DIR / f"insights_{csv_path.stem.replace('results_', '')}.json"
    report = generate_from_rows(rows, source_label=csv_path.name,
                                out_html=out_html, out_json=out_json)

    s = report["summary"]
    print(f"[insight] 対象: {csv_path.name}")
    print(f"[insight] 全体出現率 {s['overall_rate']}%  非出現 {s['nd_count']}件")
    print(f"[insight] 弱いセル {len(report['weak_cells'])} / アクション {len(report['actions'])}")
    top_comp = report['extraction']['competitors'][:5]
    if top_comp:
        print("[insight] 競合TOP: " + "、".join(f"{c}({n})" for c, n in top_comp))
    print(f"[insight] HTML: {out_html}")
    print(f"[insight] JSON: {out_json}")
    if args.open:
        webbrowser.open(out_html.resolve().as_uri())
    return 0


if __name__ == "__main__":
    sys.exit(main())
