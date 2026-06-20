"""SQLite data-access layer for the storage-service.

智策金融平台的数据库：保存行情(quotes)、新闻(news)、研判(analysis)、异动告警(alerts)
与自选股(watchlist)，并支持研判复盘统计。所有函数都以数据库文件路径作为第一个参数，
便于测试时使用临时库。
"""
import json
import sqlite3
from datetime import datetime, timezone

DEFAULT_DB = "/data/zhice.db"


def _direction_correct(verdict, ret, thr=0.005):
    """单个方向研判相对真实收益是否兑现（与 ingestion 复盘口径一致）。"""
    v = (verdict or "").strip()
    if v == "偏多":
        return ret > thr
    if v == "偏空":
        return ret < -thr
    return abs(ret) <= thr  # 中性/缺失：波动在阈值内视为兑现


def _wilson_lower(hits, n, z=1.96):
    """命中率的 Wilson 95% 置信下界——小样本下比裸命中率更诚实。"""
    if n <= 0:
        return 0.0
    p = hits / n
    denom = 1 + z * z / n
    centre = p + z * z / (2 * n)
    margin = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5)
    return max(0.0, (centre - margin) / denom)


def _by_member(rows):
    """从每条已复盘研判的 committee_json 聚合逐委员（按 lens）方向命中率。

    非方向风险票（如 XGBoost 波动信号）不计入方向命中统计。
    """
    agg = {}  # lens -> [n, hits, sum_conf]
    for r in rows:
        cj = r["committee_json"]
        ret = r["ret_1d"]
        if not cj or ret is None:
            continue
        try:
            data = json.loads(cj)
        except (ValueError, TypeError):
            continue  # 截断/畸形 JSON：跳过该行而非崩溃
        for mem in (data.get("members") or []):
            if not isinstance(mem, dict):
                continue
            lens = mem.get("lens")
            if not lens or "风险信号" in str(lens):
                continue
            a = agg.setdefault(lens, [0, 0, 0.0])
            a[0] += 1
            if _direction_correct(mem.get("verdict"), ret):
                a[1] += 1
            mc = mem.get("confidence")
            if isinstance(mc, (int, float)):
                a[2] += mc
    out = {}
    for lens, (n, hits, sconf) in agg.items():
        out[lens] = {"n": n, "hits": hits,
                     "hit_rate": (hits / n) if n else None,
                     "wilson_low": round(_wilson_lower(hits, n), 3),
                     "avg_confidence": round(sconf / n, 3) if n else None}
    return out


def _conn(path):
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    return c


def init_db(path=DEFAULT_DB):
    with _conn(path) as c:
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
        # —— L0 PIT 面板 7 表（多因子选股；时点查询用 visible_date/announce_date，ingest_ts 仅审计）——
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA busy_timeout=5000")
        c.executescript("""
        CREATE TABLE IF NOT EXISTS panel_daily(
          symbol TEXT, date TEXT, field TEXT, value REAL, source TEXT,
          visible_date TEXT, ingest_ts TEXT,
          PRIMARY KEY(symbol,date,field,source));
        CREATE INDEX IF NOT EXISTS idx_panel_sfv ON panel_daily(symbol,field,visible_date);
        CREATE TABLE IF NOT EXISTS fundamentals_pit(
          symbol TEXT, period TEXT, announce_date TEXT, legal_deadline TEXT,
          disclosed_date TEXT, field TEXT, value REAL, source TEXT, pit_status TEXT, ingest_ts TEXT,
          PRIMARY KEY(symbol,period,field,source));
        CREATE INDEX IF NOT EXISTS idx_fund_sad ON fundamentals_pit(symbol,announce_date);
        CREATE TABLE IF NOT EXISTS index_membership(
          date TEXT, symbol TEXT, weight REAL, index_code TEXT, universe_pit_status TEXT,
          PRIMARY KEY(date,symbol,index_code));
        CREATE TABLE IF NOT EXISTS events(
          symbol TEXT, event_type TEXT, announce_date TEXT, payload_json TEXT,
          source TEXT, ingest_ts TEXT);
        CREATE INDEX IF NOT EXISTS idx_evt_sad ON events(symbol,announce_date);
        CREATE TABLE IF NOT EXISTS factor_meta(
          factor_name TEXT PRIMARY KEY, source TEXT, akshare_api TEXT, fetch_granularity TEXT,
          pit_status TEXT, baidu_indicator TEXT, baidu_period TEXT, compute_path TEXT,
          history_depth_days INTEGER, backtestable_from TEXT, survivorship_note TEXT,
          coverage REAL, direction TEXT, sw_industry_source TEXT, regime_breaks TEXT, caveat TEXT);
        CREATE TABLE IF NOT EXISTS factor_eval(
          factor_name TEXT, family TEXT, as_of TEXT, horizon INTEGER, n_quantiles INTEGER,
          neutralize_variant TEXT, rebalance INTEGER, universe_filter TEXT,
          mean_rank_ic REAL, icir REAL, ic_t_hac REAL, ic_block_boot_p REAL,
          monotonic_spearman REAL, long_only_excess REAL, long_only_block_boot_p REAL,
          ls_research_only_sharpe REAL, turnover REAL, ic_half_life REAL,
          bh_passed INTEGER, harvey_passed INTEGER, dsr_optimistic REAL, dsr_conservative REAL,
          n_trials INTEGER, var_sr_trials REAL, family_verdict TEXT, residual_incremental_ic REAL,
          significant INTEGER, abstain_reason TEXT, computed_at TEXT,
          PRIMARY KEY(factor_name,as_of,horizon,n_quantiles,neutralize_variant,rebalance,universe_filter));
        CREATE TABLE IF NOT EXISTS portfolios(
          portfolio_id TEXT, as_of TEXT, method TEXT, weights_json TEXT, beats_1overN INTEGER,
          excess_block_boot_p REAL, cov_method TEXT, cov_delta REAL, capacity_flag TEXT,
          fallback_reason TEXT, computed_at TEXT, PRIMARY KEY(portfolio_id,as_of));
        """)


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
        rows = c.execute(
            "SELECT confidence, correct, ret_1d, committee_json FROM analysis "
            "WHERE reviewed_at IS NOT NULL").fetchall()
    tot = len(rows)
    if not tot:
        return {"reviewed": 0, "hit_rate": None, "avg_confidence_when_wrong": None,
                "by_member": {}, "confidence_points": []}
    hits = sum(1 for r in rows if r["correct"] == 1)
    wrong_confs = [r["confidence"] for r in rows
                   if r["correct"] == 0 and r["confidence"] is not None]
    # (置信度, 是否命中) 样本对 → 供 agent-service 计算 Brier/ECE/可靠性图
    conf_points = [[r["confidence"], r["correct"]] for r in rows
                   if r["confidence"] is not None and r["correct"] is not None]
    return {"reviewed": tot, "hit_rate": hits / tot,
            "avg_confidence_when_wrong": (sum(wrong_confs) / len(wrong_confs)) if wrong_confs else None,
            "by_member": _by_member(rows),
            "confidence_points": conf_points}


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


def remove_watchlist(path, symbol):
    with _conn(path) as c:
        cur = c.execute("DELETE FROM watchlist WHERE symbol=?", (symbol,))
        return cur.rowcount


# ---------------------------------------------------------------- L0 PIT 面板
def visible_date(legal_deadline, disclosed_date):
    """可见日 = min(法定截止日, 真披露日)；None 安全，取较早的非空者。"""
    cands = [d for d in (legal_deadline, disclosed_date) if d]
    return min(cands) if cands else None


def add_fundamental(path, symbol, period, field, value, legal_deadline,
                    disclosed_date, source, pit_status):
    ad = visible_date(legal_deadline, disclosed_date)
    with _conn(path) as c:
        c.execute(
            "INSERT OR REPLACE INTO fundamentals_pit"
            "(symbol,period,announce_date,legal_deadline,disclosed_date,field,value,source,pit_status,ingest_ts)"
            " VALUES(?,?,?,?,?,?,?,?,?,?)",
            (symbol, period, ad, legal_deadline, disclosed_date, field, value, source, pit_status, _now()))


def asof_fundamental(path, symbol, field, as_of):
    """防前视：返回 announce_date<=as_of 的最近一条财务值（含 pit_status）。"""
    with _conn(path) as c:
        r = c.execute(
            "SELECT * FROM fundamentals_pit WHERE symbol=? AND field=? AND announce_date<=? "
            "ORDER BY announce_date DESC LIMIT 1", (symbol, field, as_of)).fetchone()
        return dict(r) if r else None


def add_panel(path, symbol, date, field, value, source, visible_date):
    with _conn(path) as c:
        c.execute(
            "INSERT OR REPLACE INTO panel_daily(symbol,date,field,value,source,visible_date,ingest_ts)"
            " VALUES(?,?,?,?,?,?,?)", (symbol, date, field, value, source, visible_date, _now()))


def asof_panel(path, symbol, field, as_of):
    """防前视：返回 visible_date<=as_of 的最近一条面板值。"""
    with _conn(path) as c:
        r = c.execute(
            "SELECT * FROM panel_daily WHERE symbol=? AND field=? AND visible_date<=? "
            "ORDER BY visible_date DESC LIMIT 1", (symbol, field, as_of)).fetchone()
        return dict(r) if r else None


def add_membership(path, date, symbol, weight, index_code, universe_pit_status):
    with _conn(path) as c:
        c.execute(
            "INSERT OR REPLACE INTO index_membership(date,symbol,weight,index_code,universe_pit_status)"
            " VALUES(?,?,?,?,?)", (date, symbol, weight, index_code, universe_pit_status))


def universe(path, date, lsy_filter="off"):
    """时点成分：date<=t 最近快照的成分股；lsy_filter=on 时剔 ST（市值/次新过滤待面板接入增强）。"""
    with _conn(path) as c:
        snap = c.execute("SELECT MAX(date) d FROM index_membership WHERE date<=?", (date,)).fetchone()["d"]
        if not snap:
            return []
        rows = [dict(r) for r in c.execute(
            "SELECT * FROM index_membership WHERE date=?", (snap,)).fetchall()]
    if lsy_filter == "on":
        rows = [r for r in rows if "ST" not in (r["symbol"] or "")]
    return rows
