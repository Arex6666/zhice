"""api-gateway: 智策金融平台的唯一入口。

职责：托管金融仪表盘（finance.html）；把 /api/finance/* 转发到 agent-service；
聚合各服务健康状态于 /api/status；提供 /health 与 /metrics。
"""
import os

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

AGENT_URL = os.getenv("AGENT_URL", "http://agent-service:8001")
STORAGE_URL = os.getenv("STORAGE_URL", "http://storage-service:8003")
INGESTION_URL = os.getenv("INGESTION_URL", "http://ingestion-service:8004")
HERE = os.path.dirname(__file__)

app = FastAPI(title="zhice-api-gateway")
_metrics = {"requests": 0, "finance": 0}


@app.get("/health")
def health():
    return {"status": "ok", "service": "api-gateway"}


@app.get("/metrics")
def metrics():
    return JSONResponse(_metrics)


def _safe_json(r):
    """上游可能在错误时返回 HTML/纯文本；避免 r.json() 抛错导致网关 500。"""
    try:
        return r.json()
    except Exception:
        return {"error": "upstream non-JSON response",
                "status": r.status_code, "body": r.text[:500]}


@app.get("/api/finance/{path:path}")
async def finance_get(path: str, request: Request):
    _metrics["requests"] += 1
    async with httpx.AsyncClient(timeout=120) as c:
        r = await c.get(f"{AGENT_URL}/finance/{path}", params=dict(request.query_params))
        return JSONResponse(_safe_json(r), status_code=r.status_code)


@app.post("/api/finance/analyze")
async def finance_analyze(req: Request):
    _metrics["requests"] += 1
    _metrics["finance"] += 1
    body = await req.json()
    async with httpx.AsyncClient(timeout=180) as c:
        r = await c.post(f"{AGENT_URL}/finance/analyze", json=body)
        return JSONResponse(_safe_json(r), status_code=r.status_code)


@app.api_route("/api/watchlist", methods=["GET", "POST"])
async def watchlist_proxy(req: Request):
    """自选股读写转发到 storage（仪表盘组合管理用）。"""
    _metrics["requests"] += 1
    async with httpx.AsyncClient(timeout=20) as c:
        if req.method == "POST":
            r = await c.post(f"{STORAGE_URL}/watchlist", json=await req.json())
        else:
            r = await c.get(f"{STORAGE_URL}/watchlist")
        return JSONResponse(_safe_json(r), status_code=r.status_code)


@app.delete("/api/watchlist/{symbol:path}")
async def watchlist_delete_proxy(symbol: str):
    _metrics["requests"] += 1
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.delete(f"{STORAGE_URL}/watchlist/{symbol}")
        return JSONResponse(_safe_json(r), status_code=r.status_code)


@app.get("/api/status")
async def status():
    out = {"gateway": "ok"}
    async with httpx.AsyncClient(timeout=10) as c:
        for name, url in (("agent", AGENT_URL), ("storage", STORAGE_URL),
                          ("ingestion", INGESTION_URL)):
            try:
                rr = await c.get(f"{url}/health")
                out[name] = rr.json().get("status", "?")
            except Exception:
                out[name] = "down"
        try:
            out["ingestion_detail"] = (await c.get(f"{INGESTION_URL}/status")).json()
        except Exception:
            out["ingestion_detail"] = {}
    out["metrics"] = _metrics
    return JSONResponse(out)


@app.get("/")
@app.get("/finance")
def index():
    # 金融仪表盘为唯一首页
    return FileResponse(os.path.join(HERE, "static", "finance.html"))


app.mount("/static", StaticFiles(directory=os.path.join(HERE, "static")), name="static")
