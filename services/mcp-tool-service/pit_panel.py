"""L0 PIT 面板 realtime 只读工具（轻量 SQLite 经 storage REST；毫秒级，委员会 SSE 可直调）。"""
import os

import httpx

EXECUTION_MODE = "realtime"
STORAGE_URL = os.getenv("STORAGE_URL", "http://storage-service:8003").rstrip("/")


def universe_from_rows(rows, lsy_filter="off"):
    """纯函数：对成分行套用 lsy 过滤（按**名称**剔 ST/*ST；市值/次新过滤待面板接入增强）。"""
    if lsy_filter == "on":
        return [r for r in rows if "ST" not in (r.get("name") or "")]
    return list(rows)


async def fetch_universe(date, lsy_filter="off"):
    async with httpx.AsyncClient(timeout=8) as c:
        r = await c.get(f"{STORAGE_URL}/pit/universe", params={"date": date, "lsy_filter": lsy_filter})
        r.raise_for_status()
        return {"date": date, "lsy_filter": lsy_filter, "universe": r.json(),
                "execution_mode": EXECUTION_MODE}


async def fetch_asof(symbol, field, date, kind="panel"):
    async with httpx.AsyncClient(timeout=8) as c:
        r = await c.get(f"{STORAGE_URL}/pit/asof",
                        params={"symbol": symbol, "field": field, "date": date, "kind": kind})
        r.raise_for_status()
        return {**r.json(), "execution_mode": EXECUTION_MODE}


async def fetch_factor_eval(factor_name, as_of=None, universe_filter="lsy"):
    """委员会只读 L2 离线落库的因子评估（realtime, 毫秒级 SQLite 查询）。"""
    params = {"factor_name": factor_name, "universe_filter": universe_filter}
    if as_of:
        params["as_of"] = as_of
    async with httpx.AsyncClient(timeout=8) as c:
        r = await c.get(f"{STORAGE_URL}/pit/factor_eval", params=params)
        r.raise_for_status()
        return {**r.json(), "execution_mode": EXECUTION_MODE}


async def fetch_panel(date, fields=None):
    params = {"date": date}
    if fields:
        params["fields"] = ",".join(fields)
    async with httpx.AsyncClient(timeout=8) as c:
        r = await c.get(f"{STORAGE_URL}/pit/panel", params=params)
        r.raise_for_status()
        return {"date": date, "panel": r.json(), "execution_mode": EXECUTION_MODE}


async def fetch_coverage(date):
    async with httpx.AsyncClient(timeout=8) as c:
        r = await c.get(f"{STORAGE_URL}/pit/coverage", params={"date": date})
        r.raise_for_status()
        return {**r.json(), "execution_mode": EXECUTION_MODE}


async def fetch_data_health():
    async with httpx.AsyncClient(timeout=8) as c:
        r = await c.get(f"{STORAGE_URL}/pit/data_health")
        r.raise_for_status()
        return {**r.json(), "execution_mode": EXECUTION_MODE}


async def fetch_factor_meta(factor_name=None):
    params = {"factor_name": factor_name} if factor_name else {}
    async with httpx.AsyncClient(timeout=8) as c:
        r = await c.get(f"{STORAGE_URL}/pit/factor_meta", params=params)
        r.raise_for_status()
        return {"factor_meta": r.json(), "execution_mode": EXECUTION_MODE}


async def fetch_portfolio(portfolio_id, as_of=None):
    params = {"portfolio_id": portfolio_id}
    if as_of:
        params["as_of"] = as_of
    async with httpx.AsyncClient(timeout=8) as c:
        r = await c.get(f"{STORAGE_URL}/pit/portfolio", params=params)
        r.raise_for_status()
        return {**r.json(), "execution_mode": EXECUTION_MODE}
