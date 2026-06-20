"""L0 PIT 面板 realtime 只读工具（轻量 SQLite 经 storage REST；毫秒级，委员会 SSE 可直调）。"""
import os

import httpx

EXECUTION_MODE = "realtime"
STORAGE_URL = os.getenv("STORAGE_URL", "http://storage-service:8003").rstrip("/")


def universe_from_rows(rows, lsy_filter="off"):
    """纯函数：对成分行套用 lsy 过滤（剔 ST；市值/次新过滤待面板接入增强）。"""
    if lsy_filter == "on":
        return [r for r in rows if "ST" not in (r.get("symbol") or "")]
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
