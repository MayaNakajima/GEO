"""
スケジュール判定 / 日付ロジック
────────────────────────────────────────────────
自動実行の「実行頻度ルール」を評価し、次回の実行タイミングを算出する。

対応する頻度ルール(kind):
  every_n_days       … N日おき（毎日=N:1）           {"n":3,  "time":"09:00"}
  weekly             … 毎週 / 毎〇曜日（複数曜日可）   {"weekdays":[0,3], "time":"09:00"}
  biweekly           … 隔週                          {"weekdays":[0], "time":"09:00"}
  monthly_day        … 毎月○日                       {"day":15, "time":"09:00"}
  nth_weekday        … 第◆曜日（nth:-1で最終）        {"nth":2, "weekday":1, "time":"09:00"}
  nth_business_day   … 毎月 第N営業日                 {"nth":5, "time":"09:00"}
  first_business_day … 月初 第1営業日                 {"time":"09:00"}
  last_business_day  … 月末 最終営業日                {"time":"09:00"}

weekday は Python 準拠（月=0, 火=1, … 日=6）。

「営業日」= 平日（月〜金）かつ日本の祝日でない日。
jpholiday がインストールされていれば祝日も除外、なければ土日のみ除外にフォールバックする。
────────────────────────────────────────────────
"""

from calendar import monthrange
from datetime import date, datetime, time, timedelta

# ---- 祝日判定（jpholiday があれば使用、なければ土日のみ） ---------------- #
try:
    import jpholiday  # type: ignore
    _HAS_JPHOLIDAY = True
except Exception:
    jpholiday = None
    _HAS_JPHOLIDAY = False


def has_jpholiday() -> bool:
    return _HAS_JPHOLIDAY


def is_holiday(d: date) -> bool:
    """日本の祝日か？（jpholiday 未導入時は常に False）"""
    if _HAS_JPHOLIDAY:
        try:
            return jpholiday.is_holiday(d)
        except Exception:
            return False
    return False


def is_business_day(d: date) -> bool:
    """平日かつ祝日でない = 営業日。"""
    if d.weekday() >= 5:      # 土(5)・日(6)
        return False
    if is_holiday(d):
        return False
    return True


def business_days_in_month(year: int, month: int) -> list:
    """その月の営業日（date）を昇順で返す。"""
    days = monthrange(year, month)[1]
    return [date(year, month, dd) for dd in range(1, days + 1)
            if is_business_day(date(year, month, dd))]


def nth_business_day(year: int, month: int, nth: int):
    """月の第 nth 営業日（nth=-1 で最終営業日）。存在しなければ None。"""
    bdays = business_days_in_month(year, month)
    if not bdays:
        return None
    if nth == -1:
        return bdays[-1]
    if 1 <= nth <= len(bdays):
        return bdays[nth - 1]
    return None


def last_business_day(year: int, month: int):
    return nth_business_day(year, month, -1)


def nth_weekday(year: int, month: int, nth: int, weekday: int):
    """
    月の 第nth weekday（例: 第2火曜）。nth=-1 で最終。存在しなければ None。
    weekday: 月=0 … 日=6
    """
    days = monthrange(year, month)[1]
    matches = [date(year, month, dd) for dd in range(1, days + 1)
               if date(year, month, dd).weekday() == weekday]
    if not matches:
        return None
    if nth == -1:
        return matches[-1]
    if 1 <= nth <= len(matches):
        return matches[nth - 1]
    return None


def _parse_time(s: str) -> time:
    try:
        hh, mm = str(s).split(":")
        return time(int(hh), int(mm))
    except Exception:
        return time(9, 0)


def _monday_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


# ------------------------------------------------------------------ #
# ルール判定
# ------------------------------------------------------------------ #
def rule_matches(rule: dict, d: date, anchor: date) -> bool:
    """日付 d が頻度ルールに該当するか。anchor は開始基準日。"""
    kind = rule.get("kind")

    if kind == "every_n_days":
        n = max(1, int(rule.get("n", 1)))
        if d < anchor:
            return False
        return (d.toordinal() - anchor.toordinal()) % n == 0

    if kind == "weekly":
        return d.weekday() in [int(w) for w in rule.get("weekdays", [])]

    if kind == "biweekly":
        if d.weekday() not in [int(w) for w in rule.get("weekdays", [])]:
            return False
        weeks = (_monday_of(d).toordinal() - _monday_of(anchor).toordinal()) // 7
        return weeks % 2 == 0

    if kind == "monthly_day":
        day = int(rule.get("day", 1))
        last = monthrange(d.year, d.month)[1]
        return d.day == min(day, last)      # 31日指定など月末に丸める

    if kind == "nth_weekday":
        target = nth_weekday(d.year, d.month,
                             int(rule.get("nth", 1)), int(rule.get("weekday", 0)))
        return target is not None and d == target

    if kind == "nth_business_day":
        target = nth_business_day(d.year, d.month, int(rule.get("nth", 1)))
        return target is not None and d == target

    if kind == "first_business_day":
        target = nth_business_day(d.year, d.month, 1)
        return target is not None and d == target

    if kind == "last_business_day":
        target = last_business_day(d.year, d.month)
        return target is not None and d == target

    return False


def next_timing(rule: dict, after: datetime, anchor: date,
                horizon_days: int = 800):
    """
    after より後（厳密に大きい）の直近の実行タイミング datetime を返す。
    見つからなければ None。
    """
    t = _parse_time(rule.get("time", "09:00"))
    start = min(after.date(), anchor)
    for offset in range((after.date() - start).days, horizon_days):
        d = start + timedelta(days=offset)
        if d < anchor:
            continue
        if rule_matches(rule, d, anchor):
            dt = datetime.combine(d, t)
            if dt > after:
                return dt
    return None


# ------------------------------------------------------------------ #
# 人間可読の説明（GUI / ログ用）
# ------------------------------------------------------------------ #
_WD = ["月", "火", "水", "木", "金", "土", "日"]


def describe_rule(rule: dict) -> str:
    kind = rule.get("kind")
    t = rule.get("time", "09:00")
    if kind == "every_n_days":
        n = int(rule.get("n", 1))
        return f"毎日 {t}" if n == 1 else f"{n}日おき {t}"
    if kind == "weekly":
        wds = "・".join(_WD[int(w)] for w in rule.get("weekdays", []))
        return f"毎週 {wds}曜 {t}"
    if kind == "biweekly":
        wds = "・".join(_WD[int(w)] for w in rule.get("weekdays", []))
        return f"隔週 {wds}曜 {t}"
    if kind == "monthly_day":
        return f"毎月{int(rule.get('day', 1))}日 {t}"
    if kind == "nth_weekday":
        nth = int(rule.get("nth", 1))
        nth_s = "最終" if nth == -1 else f"第{nth}"
        return f"{nth_s}{_WD[int(rule.get('weekday', 0))]}曜 {t}"
    if kind == "nth_business_day":
        return f"毎月 第{int(rule.get('nth', 1))}営業日 {t}"
    if kind == "first_business_day":
        return f"月初 第1営業日 {t}"
    if kind == "last_business_day":
        return f"月末 最終営業日 {t}"
    return "不明なルール"
