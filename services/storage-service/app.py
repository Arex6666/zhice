"""storage-service: 文档持久化与检索 API (FastAPI + SQLite)。

对外提供 REST 接口；被 mcp-tool-service 的 save_document / search_documents
工具调用，也被 api-gateway 的"历史浏览"面板只读查询。
"""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

import db

DB_PATH = os.getenv("DB_PATH", db.DEFAULT_DB)


@asynccontextmanager
async def lifespan(app: FastAPI):
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    db.init_db(DB_PATH)
    yield


app = FastAPI(title="zhiyue-storage-service", lifespan=lifespan)


class DocIn(BaseModel):
    url: str
    title: str = ""
    content: str = ""


@app.get("/health")
def health():
    return {"status": "ok", "service": "storage-service"}


@app.post("/documents")
def create(doc: DocIn):
    rid = db.add_document(DB_PATH, doc.url, doc.title, doc.content)
    return db.get_document(DB_PATH, rid)


@app.get("/documents")
def search(q: str = "", limit: int = 5):
    return db.search_documents(DB_PATH, q, limit)


@app.get("/documents/{doc_id}")
def get_one(doc_id: int):
    d = db.get_document(DB_PATH, doc_id)
    if not d:
        raise HTTPException(404, "not found")
    return d


@app.get("/stats")
def stats():
    return db.stats(DB_PATH)
