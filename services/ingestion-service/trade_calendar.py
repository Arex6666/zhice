"""交易日历（spec §4 L0 calendar.py）。

设计：
- **纯函数核心**（5 个）接收一个**升序交易日字符串列表** days（'YYYY-MM-DD'），脱网可单测；
  全部用 bisect 做 O(log n) 定位，边界（早于/晚于全表、d 非交易日、空表）一律安全返回。
- `load_calendar(fetch_fn=None, _cache={})`：默认经 akshare `tool_trade_date_hist_sina`
  取一次 + module 级长 TTL 缓存（_cache 默认参数即缓存槽）；失败回退"工作日启发式"
  并标 `fallback=True` + caveat；命中真源 `fallback=False`。fetch_fn 注入以脱网测。

诚实约束：网络/历史不足绝不编造——回退产物显式标 fallback + caveat，调用方据此降级。
"""
import bisect
from datetime import date, timedelta

# module 级长 TTL 缓存（秒）：交易日历日内基本不变，启动拉一次即可。
CALENDAR_TTL_SECONDS = 24 * 3600


# ----------------------------------------------------------------------------
# 纯函数核心：接收升序 days 列表（不做任何网络/IO）
# ----------------------------------------------------------------------------
def is_trading_day(d, days):
    """d 是否为交易日。早于/晚于全表、空表均 → False。"""
    if not days:
        return False
    i = bisect.bisect_left(days, d)
    return i < len(days) and days[i] == d


def next_trading_day(d, days):
    """严格晚于 d 的第一个交易日；无后继（含末端/晚于全表/空表）→ None。

    d 非交易日时返回其后最近交易日；早于全表 → 第一个交易日。
    """
    if not days:
        return None
    i = bisect.bisect_right(days, d)   # 第一个 > d 的下标
    return days[i] if i < len(days) else None


def prev_trading_day(d, days):
    """严格早于 d 的最后一个交易日；无前驱（含首端/早于全表/空表）→ None。

    d 非交易日时返回其前最近交易日；晚于全表 → 最后一个交易日。
    """
    if not days:
        return None
    i = bisect.bisect_left(days, d) - 1   # 最后一个 < d 的下标
    return days[i] if i >= 0 else None


def n_trading_days_ago(d, n, days):
    """以 <= d 的最近交易日为锚, 回退 n 个交易日; 历史不足/越界/非法 → None。

    n=0 即锚日本身。d 早于全表（无 <=d 的交易日）→ None。负 n 视作非法 → None。
    """
    if not days or n is None or n < 0:
        return None
    anchor = bisect.bisect_right(days, d) - 1   # <= d 的最近交易日下标
    if anchor < 0:
        return None
    j = anchor - n
    return days[j] if j >= 0 else None


def trading_days_between(a, b, days):
    """闭区间 [a, b] 内交易日计数（含端点若为交易日）。a>b 逆序或空表 → 0。

    端点落非交易日时按区间内实际交易日计；区间覆盖全表外延则计满全表。
    """
    if not days or a > b:
        return 0
    lo = bisect.bisect_left(days, a)     # 第一个 >= a
    hi = bisect.bisect_right(days, b)    # 第一个 > b
    return max(0, hi - lo)


# ----------------------------------------------------------------------------
# 工作日启发式（末端兜底）：生成 [start, end] 内的 Mon-Fri 日期串（无法剔节假日）
# ----------------------------------------------------------------------------
def _weekday_heuristic(start, end):
    out = []
    cur = start
    one = timedelta(days=1)
    while cur <= end:
        if cur.weekday() < 5:   # 0=周一 .. 4=周五
            out.append(cur.isoformat())
        cur += one
    return out


def _clean_days(raw):
    """原始日期序列 → 去 None/去重/升序 的 'YYYY-MM-DD' 列表。"""
    seen = set()
    for x in raw:
        if x is None:
            continue
        s = str(x)[:10].strip()
        if len(s) == 10 and s[4] == "-" and s[7] == "-":
            seen.add(s)
    return sorted(seen)


def _extract_trade_dates(obj):
    """从 fetch_fn 产物提取交易日序列：兼容 DataFrame(trade_date 列) / list。"""
    # pandas DataFrame：取 trade_date 列（无则取首列）
    cols = getattr(obj, "columns", None)
    if cols is not None:
        col = "trade_date" if "trade_date" in list(cols) else list(cols)[0]
        return list(obj[col])
    return list(obj)


def _default_fetch():
    """默认真源：akshare tool_trade_date_hist_sina（同步, 由调用侧经 to_thread 卸载）。"""
    import akshare as ak
    return ak.tool_trade_date_hist_sina()


def load_calendar(fetch_fn=None, _cache={}):
    """加载交易日历，module 级长 TTL 缓存。

    - 成功命中真源 → {'days': [...升序...], 'fallback': False, 'caveat': None}
    - fetch 抛错/产物为空 → 回退工作日启发式 → {'days': [...], 'fallback': True, 'caveat': ...}
    - fetch_fn 可注入以脱网测试；_cache 默认参数即 module 级缓存槽。
    """
    import time
    now = time.time()
    cached = _cache.get("calendar")
    if cached is not None and (now - cached["_ts"]) < CALENDAR_TTL_SECONDS:
        return cached["result"]

    fn = fetch_fn or _default_fetch
    result = None
    try:
        raw = fn()
        days = _clean_days(_extract_trade_dates(raw))
        if days:
            result = {"days": days, "fallback": False, "caveat": None}
    except Exception as e:   # noqa: BLE001 — 任何真源失败都回退, 但显式标 fallback+caveat(不静默伪装)
        result = {"days": _weekday_heuristic(date(2010, 1, 1), date.today()),
                  "fallback": True,
                  "caveat": f"交易日历真源不可得({type(e).__name__}: {e})，回退工作日启发式；"
                            f"未剔除法定节假日，下游交易日判定可能含假日噪声。"}

    if result is None:   # fetch 成功但产物为空 → 同样回退
        result = {"days": _weekday_heuristic(date(2010, 1, 1), date.today()),
                  "fallback": True,
                  "caveat": "交易日历真源返回空，回退工作日启发式；未剔除法定节假日。"}

    _cache["calendar"] = {"_ts": now, "result": result}
    return result
