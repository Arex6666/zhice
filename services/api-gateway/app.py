"""api-gateway: 系统唯一入口。

职责：托管 Web 聊天界面；把 /api/chat 转发到 agent-service；把 /api/documents
转发到 storage-service（历史浏览）；提供 /health 与 /metrics。
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

app = FastAPI(title="zhiyue-api-gateway")
_metrics = {"requests": 0, "chat": 0}


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


@app.post("/api/chat")
async def chat(req: Request):
    _metrics["requests"] += 1
    _metrics["chat"] += 1
    body = await req.json()
    async with httpx.AsyncClient(timeout=120) as c:
        r = await c.post(f"{AGENT_URL}/chat", json=body)
        return JSONResponse(_safe_json(r), status_code=r.status_code)


@app.get("/api/documents")
async def documents(q: str = "", limit: int = 10):
    _metrics["requests"] += 1
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(f"{STORAGE_URL}/documents", params={"q": q, "limit": limit})
        return JSONResponse(_safe_json(r), status_code=r.status_code)


@app.get("/api/finance/{path:path}")
async def finance_get(path: str, request: Request):
    _metrics["requests"] += 1
    async with httpx.AsyncClient(timeout=120) as c:
        r = await c.get(f"{AGENT_URL}/finance/{path}", params=dict(request.query_params))
        return JSONResponse(_safe_json(r), status_code=r.status_code)


@app.post("/api/finance/analyze")
async def finance_analyze(req: Request):
    _metrics["requests"] += 1
    body = await req.json()
    async with httpx.AsyncClient(timeout=180) as c:
        r = await c.post(f"{AGENT_URL}/finance/analyze", json=body)
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


@app.get("/finance")
def finance_page():
    return FileResponse(os.path.join(HERE, "static", "finance.html"))


@app.get("/")
def index():
    return FileResponse(os.path.join(HERE, "static", "index.html"))


app.mount("/static", StaticFiles(directory=os.path.join(HERE, "static")), name="static")
