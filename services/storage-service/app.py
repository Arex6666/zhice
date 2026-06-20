"""storage-service: 智策金融数据持久化 API (FastAPI + SQLite)。

对外提供 REST 接口：行情(/quotes)、新闻(/news)、研判与复盘(/analysis*)、
异动告警(/alerts)、自选股(/watchlist)；被 agent-service / ingestion-service 调用。
"""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from pydantic import BaseModel

import db

DB_PATH = os.getenv("DB_PATH", db.DEFAULT_DB)


@asynccontextmanager
async def lifespan(app: FastAPI):
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    db.init_db(DB_PATH)
    yield


app = FastAPI(title="zhice-storage-service", lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ok", "service": "storage-service"}


# ---------------------------------------------------------------- finance
class QuoteIn(BaseModel):
    symbol: str
    price: float | None = None
    change_pct: float | None = None
    ts: str = ""
    data_status: str = ""
    source: str = ""
    raw_json: str = ""


class NewsIn(BaseModel):
    symbol: str
    title: str = ""
    url: str = ""
    source: str = ""
    ts: str = ""
    sentiment: str = ""
    summary: str = ""


class AnalysisIn(BaseModel):
    symbol: str
    mode: str = "deep"
    verdict: str = ""
    confidence: float = 0.0
    committee_json: str = "{}"
    price_at_analysis: float | None = None


@app.post("/quotes")
def create_quote(q: QuoteIn):
    rid = db.add_quote(DB_PATH, q.symbol, q.price, q.change_pct, q.ts, q.data_status,
                       q.source, q.raw_json)
    return {"id": rid}


@app.get("/quotes")
def list_quotes(symbol: str, limit: int = 50):
    return db.get_quotes(DB_PATH, symbol, max(1, min(limit, 500)))


@app.post("/news")
def create_news(n: NewsIn):
    return {"id": db.add_news(DB_PATH, n.symbol, n.title, n.url, n.source, n.ts,
                              n.sentiment, n.summary)}


@app.get("/news")
def list_news(symbol: str, limit: int = 20):
    return db.get_news(DB_PATH, symbol, max(1, min(limit, 200)))


@app.post("/analysis")
def create_analysis(a: AnalysisIn):
    return {"id": db.add_analysis(DB_PATH, a.symbol, a.mode, a.verdict, a.confidence,
                                  a.committee_json, a.price_at_analysis)}


@app.get("/analysis/review")
def analysis_review():
    return db.review_stats(DB_PATH)


@app.get("/analysis/pending")
def analysis_pending():
    return db.pending_reviews(DB_PATH)


@app.post("/analysis/{aid}/review")
def analysis_fill(aid: int, ret_1d: float = 0.0, ret_3d: float = 0.0,
                  ret_5d: float = 0.0, correct: bool = False):
    db.fill_review(DB_PATH, aid, ret_1d, ret_3d, ret_5d, correct)
    return {"ok": True}


@app.get("/alerts")
def list_alerts(limit: int = 50):
    return db.get_alerts(DB_PATH, max(1, min(limit, 200)))


@app.post("/alerts")
def create_alert(symbol: str, type: str, detail: str = ""):
    return {"id": db.add_alert(DB_PATH, symbol, type, detail)}


@app.get("/watchlist")
def watchlist():
    return db.get_watchlist(DB_PATH)
