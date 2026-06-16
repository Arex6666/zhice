"""SQLite data-access layer for the storage-service.

智阅平台的"记忆库"：保存智能体抓取过的网页文档，并支持按关键词检索。
所有函数都以数据库文件路径作为第一个参数，便于测试时使用临时库。
"""
import sqlite3
from datetime import datetime, timezone

DEFAULT_DB = "/data/zhiyue.db"


def _conn(path):
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    return c


def init_db(path=DEFAULT_DB):
    with _conn(path) as c:
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT NOT NULL,
                title TEXT,
                content TEXT,
                content_length INTEGER,
                created_at TEXT NOT NULL
            )
            """
        )


def add_document(path, url, title, content):
    now = datetime.now(timezone.utc).isoformat()
    with _conn(path) as c:
        cur = c.execute(
            "INSERT INTO documents(url,title,content,content_length,created_at) "
            "VALUES(?,?,?,?,?)",
            (url, title, content, len(content or ""), now),
        )
        return cur.lastrowid


def get_document(path, doc_id):
    with _conn(path) as c:
        row = c.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
        return dict(row) if row else None


def search_documents(path, query, limit=5):
    like = f"%{query}%"
    with _conn(path) as c:
        rows = c.execute(
            "SELECT * FROM documents WHERE content LIKE ? OR title LIKE ? OR url LIKE ? "
            "ORDER BY id DESC LIMIT ?",
            (like, like, like, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def stats(path):
    with _conn(path) as c:
        row = c.execute(
            "SELECT COUNT(*) n, MAX(created_at) last FROM documents"
        ).fetchone()
        return {"count": row["n"], "last_crawled_at": row["last"]}
