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


async def run_snapshots(as_of, symbols, index_code="000906"):
    """真实快照入口（scheduler 直调）：拉成分 + 估值 → POST storage。"""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        u = await snapshot_universe(_real_fetch_cons(client), _real_post(client, "/pit/membership"),
                                    index_code=index_code, as_of=as_of)
        v = await snapshot_valuation(_real_fetch_val(client), _real_post(client, "/pit/panel"), symbols)
        return {"universe": u, "valuation": v}
