"""ingestion PIT 快照编排（依赖注入，失败隔离）。

job 逻辑(snapshot_*)对 fetch/post 依赖注入 → 离线可测；真实运行由 run_* 包装 akfetch+httpx。
单标的失败只计数、绝不让 job 抛异常（沿用 scheduler 范式）。membership 统一标 today_snapshot_only。
"""
import os

import httpx

STORAGE_URL = os.getenv("STORAGE_URL", "http://storage-service:8003").rstrip("/")
_TIMEOUT = httpx.Timeout(15.0, connect=5.0)


async def snapshot_universe(fetch_cons, post_membership, index_code="000906", as_of=""):
    """拉中证成分 → 逐条 POST /pit/membership（带 as_of 日期）。fetch_cons/post 注入。"""
    posted, failures = 0, 0
    rows = await fetch_cons(index_code)
    for r in rows:
        try:
            await post_membership({**r, "date": as_of})
            posted += 1
        except Exception:  # noqa: BLE001 - 单条失败隔离
            failures += 1
    return {"posted": posted, "failures": failures, "index_code": index_code, "as_of": as_of}


async def snapshot_valuation(fetch_val, post_panel, symbols, indicator="市盈率(动)",
                             period="近一年"):
    """逐标的拉百度估值单指标 → 取最新一条 POST /pit/panel（visible_date=该日）。"""
    posted, failures = 0, 0
    for sym in symbols:
        try:
            series = await fetch_val(sym, indicator, period)
            if series:
                last = series[-1]
                await post_panel({"symbol": sym, "date": last["date"], "field": indicator,
                                  "value": last["value"], "source": "baidu",
                                  "visible_date": last["date"]})
                posted += 1
        except Exception:  # noqa: BLE001 - 单标的失败隔离
            failures += 1
    return {"posted": posted, "failures": failures}


async def snapshot_earnings(fetch_disclosure, post_fundamental, periods):
    """业绩预告/快报真披露日 → POST /pit/fundamental（disclosed_date 作可见日下界，storage 取 min(法定,披露)）。

    使质量/价值因子的可见日提前到真披露日（A 股大量公司远早于法定 4/30 披露），fetch/post 注入可测。
    """
    posted, failures = 0, 0
    for period in periods:
        try:
            rows = await fetch_disclosure(period)
        except Exception:  # noqa: BLE001 - 单期取数失败隔离
            failures += 1
            continue
        for r in rows:
            try:
                await post_fundamental({
                    "symbol": r["symbol"], "period": period, "field": "earnings_disclosed",
                    "value": 1.0, "legal_deadline": r.get("legal_deadline"),
                    "disclosed_date": r.get("disclosed_date"), "source": "eastmoney",
                    "pit_status": r.get("pit_status")})
                posted += 1
            except Exception:  # noqa: BLE001 - 单条失败隔离
                failures += 1
    return {"posted": posted, "failures": failures}


async def snapshot_factor_eval(eval_fn, post_fn, factors, as_of, universe_filter="lsy"):
    """L2 离线批写侧：逐因子计算评估(eval_fn)并 POST /pit/factor_eval(读侧供委员会)。失败隔离。"""
    posted, failures = 0, 0
    for f in factors:
        try:
            rep = await eval_fn(f)
            row = {"factor_name": f, "as_of": as_of, "universe_filter": universe_filter,
                   "computed_at": as_of, **(rep or {})}
            await post_fn(row)
            posted += 1
        except Exception:  # noqa: BLE001 - 单因子失败隔离
            failures += 1
    return {"posted": posted, "failures": failures}


# ---------------------------------------------------------------- 真实网络包装(薄, 由 scheduler 直调)
def _real_fetch_cons(client):
    async def f(index_code):
        import akshare as ak
        import anyio
        import akfetch
        df = await anyio.to_thread.run_sync(lambda: ak.index_stock_cons_csindex(symbol=index_code))
        return akfetch.parse_csindex_cons(df, index_code)
    return f


def _real_post(client, path):
    async def p(payload):
        r = await client.post(f"{STORAGE_URL}{path}", json=payload)
        r.raise_for_status()
    return p


def _real_fetch_val(client):
    async def f(sym, indicator, period):
        import akshare as ak
        import anyio
        import akfetch  # noqa: F401 - lazy (与 _real_fetch_cons 一致, 真实路径才需)
        df = await anyio.to_thread.run_sync(
            lambda: ak.stock_zh_valuation_baidu(symbol=sym, indicator=indicator, period=period))
        return akfetch.parse_baidu_valuation(df)
    return f


_Q_END = {"Q1": "0331", "Q2": "0630", "Q3": "0930", "Q4": "1231"}


def _ak_report_date(period):
    """'2023Q4' → akshare 的报告期 date 参 '20231231'。"""
    return period[:4] + _Q_END.get(period[-2:], "1231")


def recent_periods(as_of):
    """由 as_of(YYYY-MM-DD) 推近 4 个已应披露的报告期(去年Q4 + 今年已过季)。"""
    y = int(as_of[:4])
    return [f"{y - 1}Q4", f"{y}Q1", f"{y}Q2", f"{y}Q3"]


def _real_fetch_earnings(client):
    async def f(period):
        import anyio
        import akshare as ak
        import akfetch
        rows = []
        for fn in (ak.stock_yjyg_em, ak.stock_yjkb_em):
            try:
                df = await anyio.to_thread.run_sync(
                    lambda fn=fn: fn(date=_ak_report_date(period)))
                rows += akfetch.parse_earnings_disclosure(df, period)
            except Exception:  # noqa: BLE001 - 预告/快报任一源失败不影响另一
                pass
        best = {}                               # 每标的取最早可见日(最早披露)
        for r in rows:
            s = r["symbol"]
            if s not in best or (r["announce_date"] or "9") < (best[s]["announce_date"] or "9"):
                best[s] = r
        return list(best.values())
    return f


async def run_snapshots(as_of, symbols, index_code="000906", periods=None):
    """真实快照入口（scheduler 直调）：拉成分 + 估值 + 业绩真披露日 → POST storage。"""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        u = await snapshot_universe(_real_fetch_cons(client), _real_post(client, "/pit/membership"),
                                    index_code=index_code, as_of=as_of)
        v = await snapshot_valuation(_real_fetch_val(client), _real_post(client, "/pit/panel"), symbols)
        e = await snapshot_earnings(_real_fetch_earnings(client), _real_post(client, "/pit/fundamental"),
                                    periods or recent_periods(as_of))
        return {"universe": u, "valuation": v, "earnings": e}
