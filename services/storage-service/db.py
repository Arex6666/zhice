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
        c.execute("""CREATE TABLE IF NOT EXISTS quotes(
            id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, price REAL, change_pct REAL,
            ts TEXT, data_status TEXT, source TEXT, raw_json TEXT)""")
        c.execute("""CREATE TABLE IF NOT EXISTS news(
            id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, title TEXT, url TEXT,
            source TEXT, ts TEXT, sentiment TEXT, summary TEXT)""")
        c.execute("""CREATE TABLE IF NOT EXISTS analysis(
            id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, mode TEXT, verdict TEXT,
            confidence REAL, committee_json TEXT, price_at_analysis REAL, created_at TEXT,
            ret_1d REAL, ret_3d REAL, ret_5d REAL, correct INTEGER, reviewed_at TEXT)""")
        c.execute("""CREATE TABLE IF NOT EXISTS alerts(
            id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, type TEXT, detail TEXT, ts TEXT)""")
        c.execute("""CREATE TABLE IF NOT EXISTS watchlist(
            symbol TEXT PRIMARY KEY, market TEXT)""")


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


# ---------------------------------------------------------------- finance
def _now():
    return datetime.now(timezone.utc).isoformat()


def add_quote(path, symbol, price, change_pct, ts, data_status, source, raw_json=""):
    with _conn(path) as c:
        cur = c.execute(
            "INSERT INTO quotes(symbol,price,change_pct,ts,data_status,source,raw_json) "
            "VALUES(?,?,?,?,?,?,?)", (symbol, price, change_pct, ts, data_status, source, raw_json))
        return cur.lastrowid


def get_quotes(path, symbol, limit=50):
    with _conn(path) as c:
        rows = c.execute("SELECT * FROM quotes WHERE symbol=? ORDER BY id DESC LIMIT ?",
                         (symbol, limit)).fetchall()
        return [dict(r) for r in rows]


def add_news(path, symbol, title, url, source, ts, sentiment="", summary=""):
    with _conn(path) as c:
        cur = c.execute(
            "INSERT INTO news(symbol,title,url,source,ts,sentiment,summary) VALUES(?,?,?,?,?,?,?)",
            (symbol, title, url, source, ts, sentiment, summary))
        return cur.lastrowid


def get_news(path, symbol, limit=20):
    with _conn(path) as c:
        rows = c.execute("SELECT * FROM news WHERE symbol=? ORDER BY id DESC LIMIT ?",
                         (symbol, limit)).fetchall()
        return [dict(r) for r in rows]


def add_analysis(path, symbol, mode, verdict, confidence, committee_json, price_at_analysis):
    with _conn(path) as c:
        cur = c.execute(
            "INSERT INTO analysis(symbol,mode,verdict,confidence,committee_json,"
            "price_at_analysis,created_at) VALUES(?,?,?,?,?,?,?)",
            (symbol, mode, verdict, confidence, committee_json, price_at_analysis, _now()))
        return cur.lastrowid


def pending_reviews(path):
    """未回填收益的研判（供 ingestion 复盘）。"""
    with _conn(path) as c:
        rows = c.execute("SELECT * FROM analysis WHERE reviewed_at IS NULL").fetchall()
        return [dict(r) for r in rows]


def fill_review(path, analysis_id, ret_1d, ret_3d, ret_5d, correct):
    with _conn(path) as c:
        c.execute("UPDATE analysis SET ret_1d=?,ret_3d=?,ret_5d=?,correct=?,reviewed_at=? WHERE id=?",
                  (ret_1d, ret_3d, ret_5d, 1 if correct else 0, _now(), analysis_id))


def review_stats(path):
    with _conn(path) as c:
        tot = c.execute("SELECT COUNT(*) n FROM analysis WHERE reviewed_at IS NOT NULL").fetchone()["n"]
        if not tot:
            return {"reviewed": 0, "hit_rate": None, "avg_confidence_when_wrong": None, "by_member": {}}
        hits = c.execute("SELECT COUNT(*) n FROM analysis WHERE correct=1").fetchone()["n"]
        wrongc = c.execute(
            "SELECT AVG(confidence) a FROM analysis WHERE reviewed_at IS NOT NULL AND correct=0").fetchone()["a"]
        return {"reviewed": tot, "hit_rate": hits / tot,
                "avg_confidence_when_wrong": wrongc, "by_member": {}}


def add_alert(path, symbol, type_, detail):
    with _conn(path) as c:
        cur = c.execute("INSERT INTO alerts(symbol,type,detail,ts) VALUES(?,?,?,?)",
                        (symbol, type_, detail, _now()))
        return cur.lastrowid


def get_alerts(path, limit=50):
    with _conn(path) as c:
        rows = c.execute("SELECT * FROM alerts ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]


def set_watchlist(path, items):
    with _conn(path) as c:
        for it in items:
            c.execute("INSERT OR REPLACE INTO watchlist(symbol,market) VALUES(?,?)",
                      (it["symbol"], it.get("market", "")))


def get_watchlist(path):
    with _conn(path) as c:
        return [dict(r) for r in c.execute("SELECT * FROM watchlist").fetchall()]
