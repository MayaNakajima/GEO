"""
回答の読み取り判定（推薦の残り方・推される理由）
────────────────────────────────────────────────────────────────────
保存済みのAI回答を、別のAI（判定AI）に読ませて次を判定する。

  ・回答の形      … 候補を並べて最後に絞り込んだか／並べただけか／候補を挙げていないか／答えられていないか
  ・挙がった会社  … 回答の中で依頼先・購入先の候補として挙がった会社・ブランド
  ・最後のおすすめ … まとめ・結論で絞り込まれて推された会社か
  ・推される理由  … competitors.json の観点（attributes）から選ぶ

判定結果から次を集計して data/judge_report.html にまとめる。
  1) 名前が出たあと、最後のおすすめまで残った割合（自社・競合）
  2) 立場別の自社の扱い（1社だけおすすめ／他社と並ぶ／外れる／並ぶだけ／出ない）
  3) 会社ごとの推される理由
  4) おすすめの顔ぶれが固まっているか（直近の実行回をまたいで同じ質問を比べる）
  5) 施策の示唆（ルールで作成）

判定結果は data/judgments/judgments.jsonl に保存し、同じ回答は二度判定しない（費用を抑えるため）。

使い方（monitoring フォルダで）:
    python src/answer_judge.py                # 直近5回分を判定してレポート作成
    python src/answer_judge.py --dry-run      # 判定せず、新たに判定する件数だけ表示
    python src/answer_judge.py --limit 10     # 新たに判定するのは10件まで（お試し）
    python src/answer_judge.py --runs 1       # 最新1回分だけ
    python src/answer_judge.py --csv <path>   # 指定した results CSV だけ
    python src/answer_judge.py --open         # 作成後にブラウザで開く
出力: data/judge_report.html ／ data/reports/judge_<最新の回>.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import threading
import webbrowser
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from html import escape
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).parent))
from envload import load_env  # noqa: E402

load_env(BASE / ".env")
import insight_report  # noqa: E402  (CSV 読み込み・競合辞書を共用)
import llm_client  # noqa: E402,F401  (社内ネットワーク向けに OS の証明書ストアを使う設定を読み込む)

CONFIG_DIR = BASE / "config"
DATA_DIR = BASE / "data"
RESULTS_DIR = DATA_DIR / "results"
REPORTS_DIR = DATA_DIR / "reports"
JUDGE_DIR = DATA_DIR / "judgments"
CACHE_PATH = JUDGE_DIR / "judgments.jsonl"

# 判定の指示文を変えたら上げる（キャッシュの作り直しの合図）
PROMPT_VERSION = "1"

KIND_PICK = "絞り込みあり"
KIND_LIST = "一覧のみ"
KIND_NONE = "候補なし"
KIND_REFUSAL = "回答不能"
ANSWER_KINDS = [KIND_PICK, KIND_LIST, KIND_NONE, KIND_REFUSAL]
REC_KINDS = (KIND_PICK, KIND_LIST)  # 推薦の形の回答

OTHER_REASON = "その他"

# 自社の扱い（推薦の形の回答だけに付ける）
ST_ONLY = "1社だけおすすめ"
ST_WITH = "他社と並んでおすすめ"
ST_DROP = "おすすめから外れる"
ST_LISTED = "並ぶだけ（絞り込みなし）"
ST_ABSENT = "名前が出ない"
OWN_STATUSES = [ST_ONLY, ST_WITH, ST_DROP, ST_LISTED, ST_ABSENT]


# ================================================================== #
# 設定
# ================================================================== #
def load_cfg() -> dict:
    p = CONFIG_DIR / "judge.json"
    cfg = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    cfg.setdefault("model", "claude-opus-5-5")
    cfg.setdefault("effort", "medium")
    cfg.setdefault("max_tokens", 16000)
    cfg.setdefault("fallbacks", "default")
    cfg.setdefault("votes", 1)
    cfg.setdefault("workers", 4)
    cfg.setdefault("report_runs", 5)
    cfg.setdefault("stability_min_runs", 3)
    cfg.setdefault("stability_threshold", 0.8)
    cfg.setdefault("own_label", "自社")
    cfg.setdefault("own_aliases_extra", [])
    return cfg


def load_own_aliases(cfg: dict) -> list:
    p = CONFIG_DIR / "detection_keywords.json"
    kw = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    aliases = kw.get("primary", []) + kw.get("secondary", []) + cfg.get("own_aliases_extra", [])
    return [a for a in aliases if a]


# ================================================================== #
# 判定AIへの指示
# ================================================================== #
SYSTEM_PROMPT = (
    "あなたは、生成AIの回答を読み解いて分類する分析者です。"
    "与えられた「質問」と「AIの回答」を読み、回答に書かれていることだけをもとに判定してください。"
    "回答に書かれていないことを推測で補ってはいけません。"
)


def _build_user_prompt(question: str, answer: str, categories: dict) -> str:
    cat_lines = "\n".join(
        f"- {label}（例: {'、'.join(kws[:6])}）" for label, kws in categories.items())
    return f"""次の「質問」に対する「AIの回答」を読み、以下の手順で判定してください。

## 1. 挙がった会社（companies）
回答の中で、質問への答えとして「依頼先・購入先・相談先の候補」として挙がった会社・ブランドをすべて挙げてください。
- 含める: ユニフォーム・制服・作業服などのメーカー、販売会社、サービス会社、ブランド
- 含めない: 素材メーカー（例: 東レ・帝人）や、導入事例の顧客企業、比較のための一般的な例など、候補として勧められていない会社
- name は回答に書かれた表記のまま（正式な社名が書かれていれば社名）

## 2. 最後のおすすめ（final）
回答の最後のまとめ・結論・「特におすすめ」「迷ったら」「まず相談すべきは」などで、候補が絞り込まれて推されている会社を final=true にしてください。
- 候補を並べただけで絞り込みがない場合は、すべて final=false
- 候補が1社だけで、その会社を勧めている場合は、その会社を final=true

## 3. 推される理由（reasons）
各社について、回答の中でその会社が紹介・推薦される理由として書かれている観点を、次の一覧から選んでください（複数可）。
どれにも当てはまらない理由は「{OTHER_REASON}」にしてください。理由が書かれていなければ空の配列にしてください。
{cat_lines}
- {OTHER_REASON}

evidence には、その会社の理由を示す回答中の短い抜粋（60字以内）を入れてください。

## 4. 回答の形（answer_kind）
- {KIND_PICK}: 候補を挙げ、最後にどれかに絞り込んで推している（候補が1社だけで勧めている場合も含む）
- {KIND_LIST}: 候補を並べただけで、絞り込みはしていない
- {KIND_NONE}: 会社名の候補を挙げず、一般的な説明だけをしている（特定の1社について説明しているだけの場合も含む）
- {KIND_REFUSAL}: 情報がない・分からないなどで、答えられていない

{KIND_NONE} と {KIND_REFUSAL} の場合、companies は空の配列にしてください。

## 質問
{question}

## AIの回答
{answer}
"""


def _schema(categories: dict) -> dict:
    reason_enum = list(categories.keys()) + [OTHER_REASON]
    return {
        "type": "object",
        "properties": {
            "answer_kind": {"type": "string", "enum": ANSWER_KINDS},
            "companies": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "final": {"type": "boolean"},
                        "reasons": {"type": "array",
                                    "items": {"type": "string", "enum": reason_enum}},
                        "evidence": {"type": "string"},
                    },
                    "required": ["name", "final", "reasons", "evidence"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["answer_kind", "companies"],
        "additionalProperties": False,
    }


# ================================================================== #
# 判定器
# ================================================================== #
class AnswerJudge:

    def __init__(self, cfg: dict, competitors_cfg: dict, own_aliases: list):
        self.cfg = cfg
        self.categories = competitors_cfg.get("attributes", {})
        self.schema = _schema(self.categories)
        self.own_label = cfg["own_label"]
        self.own_aliases = [a.lower() for a in own_aliases]
        self.alias_map = {}
        for c in competitors_cfg.get("competitors", []):
            for a in c.get("aliases", []):
                self.alias_map[a.lower()] = c["canonical"]
        self._client = None
        self._lock = threading.Lock()
        self.cache = self._load_cache()

    # ---- 会社名をそろえる ---- #
    def canonical(self, name: str) -> tuple:
        """表記 → (そろえた名前, 自社か)。"""
        low = (name or "").strip().lower()
        if any(a in low for a in self.own_aliases):
            return self.own_label, True
        if low in self.alias_map:
            return self.alias_map[low], False
        # 「株式会社ボンマックス」「BONMAX（ボンマックス）」など、別名を含む表記
        for alias, canon in sorted(self.alias_map.items(), key=lambda x: -len(x[0])):
            if len(alias) >= 3 and alias in low:
                return canon, False
        clean = name.strip()
        for suffix in ("株式会社", "（株）", "(株)", "有限会社"):
            clean = clean.replace(suffix, "")
        return clean.strip() or name.strip(), False

    # ---- キャッシュ ---- #
    def key(self, question: str, answer: str) -> str:
        src = "\x1f".join([PROMPT_VERSION, self.cfg["model"], str(self.cfg["votes"]),
                           question or "", answer or ""])
        return hashlib.sha1(src.encode("utf-8")).hexdigest()

    def _load_cache(self) -> dict:
        cache = {}
        if CACHE_PATH.exists():
            for line in CACHE_PATH.read_text(encoding="utf-8").splitlines():
                try:
                    d = json.loads(line)
                    cache[d["key"]] = d
                except Exception:
                    pass
        return cache

    def _save(self, rec: dict):
        with self._lock:
            self.cache[rec["key"]] = rec
            JUDGE_DIR.mkdir(parents=True, exist_ok=True)
            with open(CACHE_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # ---- API 呼び出し ---- #
    def _call(self, question: str, answer: str) -> dict:
        import anthropic
        if self._client is None:
            self._client = anthropic.Anthropic()
        kwargs = dict(
            model=self.cfg["model"],
            max_tokens=self.cfg["max_tokens"],
            system=SYSTEM_PROMPT,
            messages=[{"role": "user",
                       "content": _build_user_prompt(question, answer, self.categories)}],
            output_config={"effort": self.cfg["effort"],
                           "format": {"type": "json_schema", "schema": self.schema}},
        )
        if self.cfg.get("fallbacks"):
            response = self._client.beta.messages.create(
                betas=["server-side-fallback-2026-07-01"],
                fallbacks=self.cfg["fallbacks"], **kwargs)
        else:
            response = self._client.messages.create(**kwargs)
        if response.stop_reason == "refusal":
            raise RuntimeError("判定AIが処理を断りました（refusal）")
        if response.stop_reason == "max_tokens":
            raise RuntimeError("判定が max_tokens で打ち切られました")
        text = next((b.text for b in response.content if b.type == "text"), "")
        return json.loads(text)

    def _merge_votes(self, votes: list) -> dict:
        """複数回の判定を多数決でまとめる。"""
        if len(votes) == 1:
            return votes[0]
        need = len(votes) / 2
        kind = Counter(v["answer_kind"] for v in votes).most_common(1)[0][0]
        per = defaultdict(list)
        for v in votes:
            seen = set()
            for c in v["companies"]:
                name, _ = self.canonical(c["name"])
                if name not in seen:
                    seen.add(name)
                    per[name].append(c)
        companies = []
        for name, cs in per.items():
            if len(cs) <= need:
                continue
            reasons = Counter(r for c in cs for r in set(c["reasons"]))
            companies.append({
                "name": cs[0]["name"],
                "final": sum(c["final"] for c in cs) > len(cs) / 2,
                "reasons": [r for r, n in reasons.items() if n > len(cs) / 2],
                "evidence": cs[0]["evidence"],
            })
        return {"answer_kind": kind, "companies": companies}

    def judge(self, question: str, answer: str) -> dict:
        k = self.key(question, answer)
        if k in self.cache:
            return self.cache[k]
        votes = [self._call(question, answer) for _ in range(max(1, int(self.cfg["votes"])))]
        result = self._merge_votes(votes)
        rec = {"key": k, "judged_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
               "model": self.cfg["model"], "prompt_version": PROMPT_VERSION,
               "votes": len(votes), **result}
        self._save(rec)
        return rec

    # ---- 判定結果を集計しやすい形にする ---- #
    def enrich(self, rec: dict) -> dict:
        kind = rec["answer_kind"]
        companies = []
        seen = {}
        for c in rec.get("companies", []) if kind in REC_KINDS else []:
            name, is_own = self.canonical(c["name"])
            if name in seen:  # 同じ会社が2回挙がったらまとめる
                prev = seen[name]
                prev["final"] = prev["final"] or c["final"]
                prev["reasons"] = sorted(set(prev["reasons"]) | set(c["reasons"]))
                continue
            d = {"name": name, "is_own": is_own, "final": bool(c["final"]),
                 "reasons": sorted(set(c["reasons"])), "evidence": c.get("evidence", "")}
            seen[name] = d
            companies.append(d)
        if kind == KIND_LIST:  # 絞り込みなしなら最後のおすすめは無い
            for c in companies:
                c["final"] = False
        finals = [c["name"] for c in companies if c["final"]]
        own = next((c for c in companies if c["is_own"]), None)
        if kind not in REC_KINDS:
            status = ""
        elif own is None:
            status = ST_ABSENT
        elif kind == KIND_LIST:
            status = ST_LISTED
        elif own["final"]:
            status = ST_ONLY if len(finals) == 1 else ST_WITH
        else:
            status = ST_DROP
        return {"answer_kind": kind, "companies": companies, "finals": finals,
                "own_status": status}


def needs_judge(row: dict) -> bool:
    return bool((row.get("answer") or "").strip())


def judge_rows(judge: AnswerJudge, rows: list, limit: int | None = None,
               log=print) -> dict:
    """rows を判定する。戻り値: {キー: 判定結果}。limit は新たに判定する上限。"""
    todo, seen = [], set()
    for r in rows:
        if not needs_judge(r):
            continue
        k = judge.key(r.get("question", ""), r.get("answer", ""))
        if k in judge.cache or k in seen:
            continue
        seen.add(k)
        todo.append(r)
    if limit is not None:
        todo = todo[:limit]
    if todo:
        log(f"[judge] 新たに判定: {len(todo)}件（判定済み {len(judge.cache)}件）"
            f" モデル: {judge.cfg['model']}")
    errors = 0
    with ThreadPoolExecutor(max_workers=max(1, int(judge.cfg["workers"]))) as ex:
        futs = {ex.submit(judge.judge, r.get("question", ""), r.get("answer", "")): r
                for r in todo}
        for i, f in enumerate(as_completed(futs), 1):
            try:
                f.result()
            except Exception as e:
                errors += 1
                log(f"[judge] 判定エラー（{futs[f].get('question_id', '')}）: {e}")
            if i % 20 == 0 or i == len(todo):
                log(f"[judge] {i}/{len(todo)}件")
    if errors:
        log(f"[judge] エラー {errors}件（次回の実行で再判定します）")
    return judge.cache


# ================================================================== #
# 集計
# ================================================================== #
def _pct(n: int, d: int) -> float:
    return round(n / d * 100, 1) if d else 0.0


def build_report(runs: list, judge: AnswerJudge, cfg: dict) -> dict:
    """runs = [(回の名前, rows), ...]（古い順）。"""
    items = []  # 判定済みの回答
    for stem, rows in runs:
        for r in rows:
            if not needs_judge(r):
                continue
            rec = judge.cache.get(judge.key(r.get("question", ""), r.get("answer", "")))
            if not rec:
                continue
            items.append({"run": stem, "row": r, **judge.enrich(rec)})

    rec_items = [it for it in items if it["answer_kind"] in REC_KINDS]
    pick_items = [it for it in items if it["answer_kind"] == KIND_PICK]
    own_label = cfg["own_label"]

    # ---- 1) 最後のおすすめまで残った割合 ---- #
    listed, kept = Counter(), Counter()
    for it in pick_items:
        for c in it["companies"]:
            listed[c["name"]] += 1
            if c["final"]:
                kept[c["name"]] += 1
    total_listed, total_kept = sum(listed.values()), sum(kept.values())
    top_names = [n for n, _ in listed.most_common(12)]
    if own_label in listed and own_label not in top_names:
        top_names.append(own_label)
    survival = [{"name": n, "listed": listed[n], "kept": kept[n],
                 "rate": _pct(kept[n], listed[n]), "is_own": n == own_label}
                for n in top_names]
    survival.sort(key=lambda x: (not x["is_own"], -x["listed"]))

    # ---- 2) 立場別の自社の扱い ---- #
    by_st = defaultdict(Counter)
    non_rec = Counter()
    for it in items:
        st = it["row"].get("stakeholder_label") or "－"
        if it["answer_kind"] in REC_KINDS:
            by_st[st][it["own_status"]] += 1
        else:
            non_rec[st] += 1
    stakeholder_rows = []
    for st in sorted(set(by_st) | set(non_rec), key=lambda s: -sum(by_st[s].values())):
        cnt = by_st[st]
        n = sum(cnt.values())
        stakeholder_rows.append({"stakeholder": st, "rec_total": n,
                                 "counts": {s: cnt[s] for s in OWN_STATUSES},
                                 "absent_rate": _pct(cnt[ST_ABSENT], n),
                                 "non_rec": non_rec[st]})
    own_total = Counter(it["own_status"] for it in rec_items)

    # ---- 3) 推される理由（名前が出た推薦回答に占める割合） ---- #
    rec_listed = Counter()
    reason_cnt = defaultdict(Counter)
    for it in rec_items:
        for c in it["companies"]:
            rec_listed[c["name"]] += 1
            for rs in c["reasons"]:
                reason_cnt[c["name"]][rs] += 1
    comp_names = [n for n, _ in rec_listed.most_common() if n != own_label][:4]
    reason_cols = ([own_label] if rec_listed[own_label] else []) + comp_names
    reason_labels = list(judge.categories.keys()) + [OTHER_REASON]
    reasons = {
        "columns": [{"name": n, "listed": rec_listed[n]} for n in reason_cols],
        "rows": [{"reason": rs,
                  "values": [_pct(reason_cnt[n][rs], rec_listed[n]) for n in reason_cols]}
                 for rs in reason_labels
                 if any(reason_cnt[n][rs] for n in reason_cols)],
    }

    # ---- 4) 顔ぶれの固定度（同じ質問を回をまたいで比べる） ---- #
    per_q = defaultdict(list)
    for it in pick_items:
        per_q[it["row"].get("question_id") or it["row"].get("question", "")].append(it)
    min_runs = int(cfg["stability_min_runs"])
    thr = float(cfg["stability_threshold"])
    stability_q = []
    for qid, its in per_q.items():
        by_run = {}
        for it in its:
            by_run.setdefault(it["run"], it)
        if len(by_run) < min_runs:
            continue
        runs_n = len(by_run)
        top = Counter(n for it in by_run.values() for n in set(it["finals"]))
        top_name, top_n = top.most_common(1)[0] if top else ("－", 0)
        share = top_n / runs_n
        own_final = sum(own_label in it["finals"] for it in by_run.values())
        row0 = its[0]["row"]
        stability_q.append({
            "question_id": qid, "question": row0.get("question", ""),
            "stakeholder": row0.get("stakeholder_label") or "－",
            "runs": runs_n, "top": top_name, "top_runs": top_n,
            "share": round(share * 100), "fixed": share >= thr, "own_final": own_final,
        })
    stab_by_st = defaultdict(lambda: [0, 0])
    for q in stability_q:
        stab_by_st[q["stakeholder"]][1] += 1
        if q["fixed"]:
            stab_by_st[q["stakeholder"]][0] += 1
    unfixed = sorted([q for q in stability_q if not q["fixed"]],
                     key=lambda q: (q["own_final"] > 0, q["share"]))

    report = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "runs": [stem for stem, _ in runs],
        "model": cfg["model"], "votes": cfg["votes"],
        "own_label": own_label,
        "summary": {
            "answers": sum(1 for _, rows in runs for r in rows if needs_judge(r)),
            "judged": len(items),
            "rec": len(rec_items), "pick": len(pick_items),
            "kinds": dict(Counter(it["answer_kind"] for it in items)),
            "listed_total": total_listed, "kept_total": total_kept,
            "kept_rate": _pct(total_kept, total_listed),
            "own_listed": listed[own_label], "own_kept": kept[own_label],
            "own_kept_rate": _pct(kept[own_label], listed[own_label]),
            "own_status_total": {s: own_total[s] for s in OWN_STATUSES},
        },
        "survival": survival,
        "stakeholders": stakeholder_rows,
        "reasons": reasons,
        "stability": {
            "min_runs": min_runs, "threshold": round(thr * 100),
            "questions": len(stability_q),
            "fixed": sum(q["fixed"] for q in stability_q),
            "by_stakeholder": [{"stakeholder": s, "fixed": v[0], "total": v[1]}
                               for s, v in sorted(stab_by_st.items(), key=lambda x: -x[1][1])],
            "unfixed": unfixed[:30],
        },
    }
    report["google"] = build_google_join(items, own_label)
    report["suggestions"] = _suggestions(report)
    return report


# ================================================================== #
# Google参考値（毎月の検索チェック）との突き合わせ
# ================================================================== #
GOOGLE_DIR = DATA_DIR / "google_check"

G_NOT_CONVEYED = "Googleでは引用・Claudeでは出ない"
G_SERP_ONLY = "Google検索では上位・Claudeでは出ない"
G_NO_PAGE = "どちらにも出ない"
G_BOTH = "どちらにも出る"
G_CLAUDE_ONLY = "Claudeだけ出る"
G_NO_DATA = "検索チェック未記録"
G_CATEGORIES = [G_NOT_CONVEYED, G_SERP_ONLY, G_NO_PAGE, G_BOTH, G_CLAUDE_ONLY, G_NO_DATA]
G_HINTS = {
    G_NOT_CONVEYED: "ページはあり、GoogleのAIによる概要も引用している。Claudeに推す理由として伝わる書き方（業種・機能・実績の具体）が足りない可能性",
    G_SERP_ONLY: "検索結果の上位10件には入るが、AIによる概要には引用されていない。ページの中身がAIに答えとして使われにくい可能性",
    G_NO_PAGE: "Googleでも上位10件に入らず、AIによる概要にも引用されていない。質問に答えるページ自体が足りない可能性",
    G_BOTH: "Claude・Googleの両方で自社が出ている",
    G_CLAUDE_ONLY: "Claudeでは出るが、Googleでは上位10件・AIによる概要のどちらにも出ていない",
    G_NO_DATA: "この質問の検索チェックがまだ記録されていない",
}


def load_google_rows(month: str | None = None) -> tuple:
    """最新月（または指定月）の検索チェックを読む。戻り値: (月, 行のリスト)。"""
    files = sorted(GOOGLE_DIR.glob("google_check_*.csv"))
    if month:
        files = [p for p in files if p.stem.endswith(month)]
    if not files:
        return "", []
    p = files[-1]
    return p.stem.replace("google_check_", ""), insight_report.read_csv_rows(p)


def _rank(v: str):
    try:
        return int(str(v).strip())
    except Exception:
        return None


def build_google_join(items: list, own_label: str, month: str | None = None) -> dict:
    """質問ごとに Claude の結果（判定）と Google の検索チェックを並べ、6つに分ける。"""
    g_month, g_rows = load_google_rows(month)
    g_by_q = defaultdict(list)
    for g in g_rows:
        for qid in (g.get("設問ID") or "").split(";"):
            if qid.strip():
                g_by_q[qid.strip()].append(g)

    per_q = defaultdict(list)
    for it in items:
        qid = it["row"].get("question_id") or ""
        if qid:
            per_q[qid].append(it)

    questions = []
    for qid, its in per_q.items():
        row0 = its[-1]["row"]
        runs = len({it["run"] for it in its})
        named_runs = len({it["run"] for it in its
                          if any(c["is_own"] for c in it["companies"])
                          or (it["answer_kind"] not in REC_KINDS
                              and insight_report._to_bool(it["row"].get("mention_detected")))})
        comp_cnt = Counter(c["name"] for it in its for c in it["companies"] if not c["is_own"])
        top_comps = [n for n, _ in comp_cnt.most_common(3)]

        gs = g_by_q.get(qid, [])
        g_aio_own = any(g.get("AIO自社引用") == "あり" for g in gs)
        ranks = [(r, g) for g in gs for r in [_rank(g.get("自社最高順位"))] if r is not None]
        best = min(ranks, key=lambda x: x[0]) if ranks else None
        g_top10 = best is not None and best[0] <= 10
        g_comps = {n for g in gs for n in (g.get("競合（上位10件内）") or "").split(";") if n}
        overlap = [n for n in top_comps if any(n in gc or gc in n for gc in g_comps)]

        if not gs:
            cat = G_NO_DATA
        elif named_runs:
            cat = G_BOTH if (g_aio_own or g_top10) else G_CLAUDE_ONLY
        elif g_aio_own:
            cat = G_NOT_CONVEYED
        elif g_top10:
            cat = G_SERP_ONLY
        else:
            cat = G_NO_PAGE

        questions.append({
            "question_id": qid, "question": row0.get("question", ""),
            "stakeholder": row0.get("stakeholder_label") or "－",
            "category": cat, "claude_named": named_runs, "runs": runs,
            "g_terms": len(gs), "g_aio_own": g_aio_own,
            "g_best_rank": best[0] if best else None,
            "g_own_url": best[1].get("自社URL", "") if best else "",
            "claude_top_comps": top_comps, "comps_also_in_google": overlap,
        })

    order = {c: i for i, c in enumerate(G_CATEGORIES)}
    questions.sort(key=lambda q: (order[q["category"]],
                                  q["g_best_rank"] if q["g_best_rank"] is not None else 99))
    counts = Counter(q["category"] for q in questions)
    by_st = defaultdict(Counter)
    for q in questions:
        by_st[q["stakeholder"]][q["category"]] += 1
    return {
        "month": g_month, "terms": len(g_rows), "questions": questions,
        "counts": {c: counts[c] for c in G_CATEGORIES},
        "by_stakeholder": [{"stakeholder": s, "counts": {c: v[c] for c in G_CATEGORIES},
                            "total": sum(v.values())}
                           for s, v in sorted(by_st.items(), key=lambda x: -sum(x[1].values()))],
        "hints": G_HINTS,
    }


def _suggestions(rep: dict) -> list:
    """集計結果から施策の示唆をルールで作る。"""
    out = []
    own = rep["own_label"]
    s = rep["summary"]

    # 名前が出たときに残れているか（少ない件数では比べない）
    min_n = 10
    comps = [x for x in rep["survival"] if not x["is_own"] and x["listed"] >= min_n]
    if s["own_listed"] >= min_n and comps:
        avg = round(sum(x["rate"] for x in comps) / len(comps), 1)
        txt = (f"名前が出た回答のうち、最後のおすすめまで残ったのは {s['own_kept_rate']}%"
               f"（{s['own_kept']}/{s['own_listed']}回）。名前が{min_n}回以上出た競合の平均は {avg}%。")
        txt += (" 名前が出れば残れている状態なので、まず名前が出る質問を増やすことが先決です。"
                if s["own_kept_rate"] >= avg else
                " 名前は出ても最後に外れやすいため、推される理由（下の表）の差を埋めることが先決です。")
        out.append({"title": "最後まで残れているか", "text": txt})
    elif s["rec"]:
        out.append({"title": "最後まで残れているか",
                    "text": f"最後に絞り込む回答（{KIND_PICK}）は推薦の形の回答 {s['rec']}件中 {s['pick']}件で、"
                            f"その中で自社の名前が出たのは {s['own_listed']}回です。"
                            "残り方を比べるには少ないため、まず名前が出ることを課題として見てください。"})

    # 名前が出ない立場
    weak = [r for r in rep["stakeholders"] if r["rec_total"] >= 3]
    weak.sort(key=lambda r: -r["absent_rate"])
    for r in weak[:2]:
        if r["absent_rate"] < 50:
            break
        out.append({"title": f"{r['stakeholder']}の質問で名前が出ない",
                    "text": f"推薦の形の回答 {r['rec_total']}件中 {r['counts'][ST_ABSENT]}件"
                            f"（{r['absent_rate']}%）で自社の名前が出ていません。"
                            "この立場の質問でよく挙がる会社と、その理由を原文で確認し、"
                            "同じ観点の記述をサイトに足すことが候補です。"})

    # 理由の差
    cols = rep["reasons"]["columns"]
    if cols and cols[0]["name"] == own and len(cols) > 1:
        gaps = []
        for row in rep["reasons"]["rows"]:
            own_v = row["values"][0]
            comp_v = row["values"][1:]
            avg = sum(comp_v) / len(comp_v)
            if avg - own_v >= 20:
                gaps.append((row["reason"], own_v, round(avg, 1)))
        gaps.sort(key=lambda g: -(g[2] - g[1]))
        if gaps:
            txt = "、".join(f"{g[0]}（競合平均 {g[2]}% ／ 自社 {g[1]}%）" for g in gaps[:3])
            out.append({"title": "競合は推されているのに、自社は語られていない理由",
                        "text": f"{txt}。これらの観点の具体的な記述（数値・規格・体制など）を、"
                                "AIがよく読むページに書き足すことが候補です。"})
        strong = sorted(rep["reasons"]["rows"], key=lambda r: -r["values"][0])[:2]
        strong = [r for r in strong if r["values"][0] > 0]
        if strong:
            out.append({"title": "自社が推されている理由（強み）",
                        "text": f"自社の名前が出た推薦の形の回答 {cols[0]['listed']}件のうち、" + "、".join(f"{r['reason']}（{r['values'][0]}%）" for r in strong)
                                + "。今の記述は残し、ほかのページにも広げると効果が期待できます。"})

    # 顔ぶれが固まっていない質問
    st = rep["stability"]
    if 0 < st["questions"] < 5:
        out.append({"title": "おすすめの顔ぶれが固まっているか",
                    "text": f"比べられたのは {st['questions']}問だけです（最後に絞り込む回答が少ないため）。"
                            "今の判定AI・質問の形では、この観点の判断材料にはなりません。"})
    elif st["questions"]:
        n_un = st["questions"] - st["fixed"]
        out.append({"title": "おすすめの顔ぶれが固まっていない質問",
                    "text": f"比べられた {st['questions']}問のうち {n_un}問は、最後のおすすめの会社が回ごとに入れ替わっています。"
                            "定番の会社がまだいないため、記述を足せば入り込める余地があります（下の一覧が狙い目）。"})

    # Google参考値との突き合わせ
    g = rep.get("google") or {}
    gc = g.get("counts") or {}
    if g.get("questions"):
        n_nc, n_serp, n_np = gc.get(G_NOT_CONVEYED, 0), gc.get(G_SERP_ONLY, 0), gc.get(G_NO_PAGE, 0)
        out.append({"title": "Googleでは引用されているのに、Claudeでは名前が出ない質問",
                    "text": f"{n_nc}問あります（Google {g['month']} の検索チェックと突き合わせ）。"
                            "ページはあり、GoogleのAIによる概要にも引用されているので、新しく作るより、"
                            "そのページ（⑤の表の自社URL）に業種・機能・実績などの推す理由を具体的に書き足すのが近道です。"
                            if n_nc else
                            f"0問でした（Google {g['month']} の検索チェックと突き合わせ）。"})
        if n_np:
            out.append({"title": "Googleでも出ていない質問（ページが足りない）",
                        "text": f"{n_np}問は、Googleの上位10件にもAIによる概要にも自社が出ていません。"
                                f"この質問に答えるページを新しく作る候補です。"
                                + (f" ほかに、検索の上位10件には入るがAIによる概要に引用されない質問が {n_serp}問あります。"
                                   if n_serp else "")})
    return out


# ================================================================== #
# HTML
# ================================================================== #
def render_html(rep: dict, out_path: Path) -> Path:
    s = rep["summary"]

    def table(head, rows):
        th = "".join(f"<th>{h}</th>" for h in head)
        return f"<table><tr>{th}</tr>{''.join(rows)}</table>"

    surv_rows = []
    for x in rep["survival"]:
        cls = " class='own'" if x["is_own"] else ""
        surv_rows.append(
            f"<tr{cls}><td>{escape(x['name'])}</td><td class='num'>{x['listed']}</td>"
            f"<td class='num'>{x['kept']}</td><td class='num'><b>{x['rate']}%</b></td></tr>")

    st_rows = []
    for r in rep["stakeholders"]:
        cells = "".join(
            f"<td class='num{' bad' if k == ST_ABSENT and r['absent_rate'] >= 50 else ''}'>"
            f"{r['counts'][k]}</td>" for k in OWN_STATUSES)
        st_rows.append(f"<tr><td>{escape(r['stakeholder'])}</td><td class='num'>{r['rec_total']}</td>"
                       f"{cells}<td class='num muted'>{r['non_rec']}</td></tr>")

    cols = rep["reasons"]["columns"]
    rs_rows = []
    for row in rep["reasons"]["rows"]:
        cells = "".join(f"<td class='num'>{v}%</td>" for v in row["values"])
        rs_rows.append(f"<tr><td>{escape(row['reason'])}</td>{cells}</tr>")
    rs_head = ["推される理由"] + [f"{escape(c['name'])}<br><span class='muted'>{c['listed']}回</span>"
                                for c in cols]

    st = rep["stability"]
    stab_rows = [f"<tr><td>{escape(x['stakeholder'])}</td><td class='num'>{x['fixed']}/{x['total']}</td></tr>"
                 for x in st["by_stakeholder"]]
    un_rows = [f"<tr><td class='small'>{escape(q['question'][:70])}</td><td>{escape(q['stakeholder'])}</td>"
               f"<td>{escape(q['top'])}</td><td class='num'>{q['top_runs']}/{q['runs']}</td>"
               f"<td class='num'>{q['own_final']}/{q['runs']}</td></tr>" for q in st["unfixed"]]
    if st["questions"]:
        stab_html = (f"<div class='grid2'><div class='card'>{table(['立場', '固まっている質問'], stab_rows)}</div>"
                     f"<div class='card'><b>固まっていない質問（狙い目）</b>"
                     f"{table(['質問', '立場', '最も多く残った会社', '残った回', '自社が残った回'], un_rows)}</div></div>")
    else:
        stab_html = (f"<div class='card muted'>同じ質問を {st['min_runs']}回以上判定できていないため、まだ比べられません。"
                     "実行回が増えると表示されます。</div>")

    g_html = _google_html(rep.get("google") or {}, table)

    sug = "".join(f"<div class='sug'><b>{escape(x['title'])}</b><div>{escape(x['text'])}</div></div>"
                  for x in rep["suggestions"]) or "<p class='muted'>示唆を出すにはデータが足りません。</p>"

    kinds = "、".join(f"{k} {s['kinds'].get(k, 0)}" for k in ANSWER_KINDS)
    pending = s["answers"] - s["judged"]
    pending_note = (f"<div class='note bad'>判定が済んでいない回答が {pending}件あります（エラーまたは件数制限）。"
                    "集計は判定済みの回答だけで行っています。</div>" if pending else "")

    html = f"""<!doctype html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>回答の読み取り判定</title>
<style>
:root{{--bg:#f7f8fa;--card:#fff;--ink:#1a2233;--muted:#6b7280;--line:#e5e7eb;--accent:#2563eb;--bad:#dc2626;}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);
font-family:"Segoe UI","Hiragino Kaku Gothic ProN","Meiryo",sans-serif;line-height:1.6}}
.wrap{{max-width:1080px;margin:0 auto;padding:28px 16px 60px}}
h1{{font-size:22px;margin:0 0 4px}}h2{{font-size:16px;margin:30px 0 12px;padding-left:10px;border-left:4px solid var(--accent)}}
.sub{{color:var(--muted);font-size:13px;margin-bottom:18px}}
.kpis{{display:flex;gap:14px;flex-wrap:wrap}}
.kpi{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 18px;min-width:150px}}
.kpi .v{{font-size:26px;font-weight:700}}.kpi .l{{font-size:12px;color:var(--muted)}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px 18px;overflow-x:auto}}
.grid2{{display:grid;grid-template-columns:1fr 2fr;gap:16px}}
@media(max-width:760px){{.grid2{{grid-template-columns:1fr}}}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
th,td{{text-align:left;padding:7px 9px;border-bottom:1px solid var(--line);vertical-align:top}}
th{{color:var(--muted);font-weight:600;font-size:12px}}
td.num{{text-align:right;font-variant-numeric:tabular-nums}}
td.small{{font-size:12px}}tr.own td{{background:#eef4ff;font-weight:600}}
.bad{{color:var(--bad);font-weight:700}}.muted{{color:var(--muted);font-size:12px}}
.sug{{background:#fffaf0;border-left:4px solid #f59e0b;border-radius:8px;padding:10px 14px;margin:10px 0;font-size:14px}}
.note{{font-size:12px;color:var(--muted);margin-top:8px}}
</style></head><body><div class="wrap">
<h1>回答の読み取り判定 — 最後のおすすめに残るか・推される理由</h1>
<div class="sub">作成: {escape(rep['generated_at'])} ／ 対象: {len(rep['runs'])}回分（{escape(rep['runs'][0] if rep['runs'] else '-')} 〜 {escape(rep['runs'][-1] if rep['runs'] else '-')}）
／ 判定AI: {escape(rep['model'])}（{rep['votes']}回判定）</div>
{pending_note}
<div class="kpis">
<div class="kpi"><div class="v">{s['own_kept_rate']}%</div><div class="l">自社：名前が出たあと最後まで残った割合<br>（{s['own_kept']}/{s['own_listed']}回）</div></div>
<div class="kpi"><div class="v">{s['kept_rate']}%</div><div class="l">全社平均の残った割合<br>（{s['kept_total']}/{s['listed_total']}回）</div></div>
<div class="kpi"><div class="v">{s['rec']}</div><div class="l">推薦の形の回答<br>（判定済み {s['judged']}件中）</div></div>
<div class="kpi"><div class="v">{s['own_status_total'][ST_ABSENT]}</div><div class="l">推薦の形なのに<br>自社の名前が出ない回答</div></div>
</div>
<div class="note">回答の形：{escape(kinds)}</div>

<h2>施策の示唆</h2>
{sug}

<h2>① 名前が出たあと、最後のおすすめまで残った割合</h2>
<div class="card">{table(['会社', '名前が出た回', '最後まで残った回', '残った割合'], surv_rows)}
<div class="note">「{KIND_PICK}」（候補を並べて最後に絞り込んだ）回答だけで計算。名前が出る回数と、最後まで残るかは別の力です。</div></div>

<h2>② 立場別の自社の扱い（推薦の形の回答）</h2>
<div class="card">{table(['立場', '推薦の形の回答'] + OWN_STATUSES + ['推薦の形でない回答'], st_rows)}
<div class="note">「並ぶだけ」は、候補を並べただけで絞り込みのない回答に自社が入っていたもの。赤字は名前が出ない割合が半分以上の立場。</div></div>

<h2>③ 会社ごとの推される理由</h2>
<div class="card">{table(rs_head, rs_rows) if cols else '<p class="muted">データがありません。</p>'}
<div class="note">各社の名前が出た推薦の形の回答のうち、その理由で紹介・推薦されていた割合。観点の一覧は competitors.json の attributes。</div></div>

<h2>④ おすすめの顔ぶれが固まっているか</h2>
{stab_html}
<div class="note">同じ質問を{st['min_runs']}回以上判定できたものが対象。最後のおすすめで最も多く残った会社が {st['threshold']}%以上の回で同じなら「固まっている」。</div>

<h2>⑤ Google参考値との突き合わせ（質問ごと）</h2>
{g_html}

<div class="note" style="margin-top:24px">※ 判定はAIによるもので、読み違いがあり得ます。重要な判断の前には回答の原文も確認してください。
判定結果は data/judgments/judgments.jsonl に保存しています。</div>
</div></body></html>"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    return out_path


def _google_html(g: dict, table) -> str:
    if not g.get("questions"):
        return ("<div class='card muted'>検索チェック（data/google_check/google_check_YYYY-MM.csv）が無いか、"
                "設問IDで突き合わせられる質問がありません。</div>")
    counts = g["counts"]
    sum_rows = [f"<tr><td><b>{escape(c)}</b></td><td class='num'>{counts[c]}</td>"
                f"<td class='small'>{escape(g['hints'][c])}</td></tr>" for c in G_CATEGORIES]
    short = {G_NOT_CONVEYED: "Google引用・Claude×", G_SERP_ONLY: "検索上位・Claude×",
             G_NO_PAGE: "どちらも×", G_BOTH: "どちらも○", G_CLAUDE_ONLY: "Claudeだけ○",
             G_NO_DATA: "未記録"}
    st_rows = [f"<tr><td>{escape(x['stakeholder'])}</td>"
               + "".join(f"<td class='num'>{x['counts'][c]}</td>" for c in G_CATEGORIES)
               + f"<td class='num'>{x['total']}</td></tr>" for x in g["by_stakeholder"]]
    q_rows = []
    for q in g["questions"]:
        if q["category"] in (G_BOTH, G_NO_DATA):
            continue
        rank = "圏外" if q["g_best_rank"] is None else f"{q['g_best_rank']}位"
        url = escape(q["g_own_url"])
        url_html = f"<a href='{url}' target='_blank'>{url}</a>" if url else "－"
        cls = " class='bad'" if q["category"] == G_NOT_CONVEYED else ""
        q_rows.append(
            f"<tr><td{cls}>{escape(short[q['category']])}</td>"
            f"<td class='small'>{escape(q['question'][:70])}</td><td class='small'>{escape(q['stakeholder'])}</td>"
            f"<td class='num'>{q['claude_named']}/{q['runs']}</td>"
            f"<td>{'あり' if q['g_aio_own'] else 'なし'}</td><td class='num'>{rank}</td>"
            f"<td class='small'>{url_html}</td>"
            f"<td class='small'>{escape('、'.join(q['claude_top_comps']) or '－')}</td>"
            f"<td class='small'>{escape('、'.join(q['comps_also_in_google']) or '－')}</td></tr>")
    return (f"<div class='card'>{table(['分類', '質問数', '読み方'], sum_rows)}"
            f"<div class='note'>Google: {escape(g['month'])} の検索チェック（{g['terms']}件の検索語。設問文と観測キーワード）。"
            "Claude: 対象の回のうち1回でも自社の名前が出れば「出る」。Google: 設問文・観測キーワードのどれかで、"
            "AIによる概要に自社が引用されたか／上位10件に自社が入ったか。</div></div>"
            f"<div class='card' style='margin-top:16px'><b>立場別</b>"
            f"{table(['立場'] + [short[c] for c in G_CATEGORIES] + ['計'], st_rows)}</div>"
            f"<div class='card' style='margin-top:16px'><b>Claudeで名前が出ない・Claudeだけ出る質問</b>"
            f"{table(['分類', '質問', '立場', 'Claudeで出た回', 'AIによる概要に自社引用', '自社の最高順位', '自社URL（最高順位）', 'Claudeがよく挙げる会社', 'そのうちGoogleでも上位の会社'], q_rows)}"
            "<div class='note'>赤字（Google引用・Claude×）が、書き足しで効果が出やすい質問です。"
            "「Googleでも上位の会社」は、Claudeがよく挙げる会社のうち検索の上位10件にも入っていた会社。</div></div>")


# ================================================================== #
# 公開API / CLI
# ================================================================== #
def latest_runs(n: int) -> list:
    files = sorted(RESULTS_DIR.glob("results_*.csv"))
    return files[-n:] if n > 0 else files


def run(csv_paths: list, limit: int | None = None, dry_run: bool = False,
        log=print, cfg: dict | None = None) -> dict | None:
    cfg = cfg or load_cfg()
    judge = AnswerJudge(cfg, insight_report.load_competitors_cfg(), load_own_aliases(cfg))
    runs = [(p.stem.replace("results_", ""), insight_report.read_csv_rows(p)) for p in csv_paths]
    all_rows = [r for _, rows in runs for r in rows]
    if dry_run:
        keys = {judge.key(r.get("question", ""), r.get("answer", ""))
                for r in all_rows if needs_judge(r)}
        new = [k for k in keys if k not in judge.cache]
        log(f"[judge] 対象 {len(runs)}回分・回答 {len(keys)}件（重複を除く）。"
            f"新たに判定するのは {len(new)}件（1件あたり判定 {cfg['votes']}回）。")
        return None
    judge_rows(judge, all_rows, limit=limit, log=log)
    rep = build_report(runs, judge, cfg)
    stem = runs[-1][0] if runs else datetime.now().strftime("%Y%m%d_%H%M%S")
    render_html(rep, DATA_DIR / "judge_report.html")
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    (REPORTS_DIR / f"judge_{stem}.json").write_text(
        json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    return rep


def main(argv=None):
    cfg = load_cfg()
    ap = argparse.ArgumentParser(description="回答の読み取り判定（推薦の残り方・推される理由）")
    ap.add_argument("--csv", help="対象の results CSV（省略時は直近の回）")
    ap.add_argument("--runs", type=int, default=cfg["report_runs"],
                    help=f"対象にする直近の回数（既定 {cfg['report_runs']}）")
    ap.add_argument("--limit", type=int, help="新たに判定する件数の上限（お試し用）")
    ap.add_argument("--dry-run", action="store_true", help="判定せず、新たに判定する件数だけ表示")
    ap.add_argument("--open", action="store_true", help="作成後にブラウザで開く")
    args = ap.parse_args(argv)

    paths = [Path(args.csv)] if args.csv else latest_runs(args.runs)
    if not paths or not all(p.exists() for p in paths):
        print("[judge] results CSV が見つかりません。")
        return 1
    rep = run(paths, limit=args.limit, dry_run=args.dry_run, cfg=cfg)
    if rep is None:
        return 0
    s = rep["summary"]
    print(f"[judge] 判定済み {s['judged']}/{s['answers']}件 ／ 推薦の形 {s['rec']}件")
    print(f"[judge] 自社：名前が出たあと最後まで残った割合 {s['own_kept_rate']}%"
          f"（{s['own_kept']}/{s['own_listed']}）")
    out = DATA_DIR / "judge_report.html"
    print(f"[judge] HTML: {out}")
    if args.open:
        webbrowser.open(out.resolve().as_uri())
    return 0


if __name__ == "__main__":
    sys.exit(main())
