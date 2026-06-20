# 智策 A股多因子选股系统 — 实现计划（基础阶段 M0+M1）

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans (inline) or subagent-driven-development. Steps use checkbox (`- [ ]`).
> 上游 spec：`docs/superpowers/specs/2026-06-21-zhice-quant-stock-selection-design.md`。本计划只覆盖 **M0 接口实测固化 + M1 L0 PIT 数据层**（spec §14 路线图的前两个里程碑）。M2–M7 在到达时各出独立计划。

**Goal:** 交付唯一可信的数据地基——带 `visible_date`/`announce_date` 戳的中证800 PIT 时点面板 + `universe(date)` + `asof()` 防前视查询，及其 realtime MCP 只读工具。

**Architecture:** 在既有 5 微服务上加法。storage-service 扩 7 张 PIT 表 + asof/universe 查询（纯 SQL，tmp_path 脱网单测）；ingestion-service 新增 `akfetch.py` 双粒度采集（防御式解析，离线 fixture 单测）+ `pit_snapshot.py` 定时 job；mcp-tool-service 新增 `pit_panel.py` realtime 只读工具。全程 TDD，守住现有 101 测试全绿。

**Tech Stack:** Python 3.11/3.12 · sqlite3(WAL) · akshare 1.18.64 · anyio · httpx · FastMCP · pytest（`importlib.util.spec_from_file_location` 脱网范式）。

## Global Constraints

- 三条诚实约束（spec §0）：①不冒充能力（数据不可得→显式标注+弃权，绝不用今日快照回填历史声称消偏）②弃权优先于给数（不足→`significant=None`/`abstain=True`）③诚实标签随值同行（`pit_status`/`caveat`/`survivorship_note` 全链路不剥离）。
- `abstain_reason` 强制四分类：`data_missing` / `model_load_failed` / `insufficient_history` / `statistical_abstain`，不得混淆。
- PIT 时点查询永远用 `visible_date`/`announce_date <= t`，**绝不**用 `ingest_ts` 查询（仅审计）。
- 可见日 `announce_date = min(法定截止日, 真预告/快报披露日)`；无披露日证据→回退法定日。
- akshare 无修订链(vintage) → 估值/财务因子 `pit_status='forward_pit_only'`，**绝不标 `true_pit`**。
- `index_stock_cons_csindex` 实测无 date 参 → 历史成分不可重建 → `universe_pit_status='today_snapshot_only'`，仪表盘强制披露幸存者偏差未消除。
- `stock_a_indicator_lg` 在 akshare 1.18.64 **不存在**；估值走 `stock_zh_valuation_baidu(symbol, indicator, period)`（单指标×period 笛卡尔）。
- 守住现有全绿基线：每个 commit 前 `python -m pytest tests/ -q` 必须全绿。

---

### Task M0: 接口实测固化脚本

**Files:**
- Create: `scripts/akshare_smoke.py`
- Test: `tests/test_akshare_contract.py`

**Interfaces:**
- Produces: `scripts/akshare_smoke.py` 可执行（联网时打印每接口 签名/是否存在/样本列）；`tests/test_akshare_contract.py::test_interface_existence` 离线断言关键接口存在性与失效项。

- [ ] **Step 1: 写失败测试**（离线，断言 `stock_a_indicator_lg` 缺失、`stock_zh_valuation_baidu` 含 indicator/period 形参、其余关键接口存在）

```python
# tests/test_akshare_contract.py
import inspect
import pytest
ak = pytest.importorskip("akshare")

EXIST = ["stock_zh_valuation_baidu", "stock_a_all_pb", "stock_zh_a_spot_em",
         "index_stock_cons_csindex", "stock_hsgt_hold_stock_em", "stock_yjyg_em",
         "stock_yjkb_em", "stock_zh_a_gdhs_detail_em", "index_option_300etf_qvix",
         "stock_board_industry_name_em", "stock_individual_info_em",
         "stock_financial_analysis_indicator", "stock_individual_fund_flow",
         "stock_gpzy_pledge_ratio_em", "stock_restricted_release_queue_em",
         "tool_trade_date_hist_sina"]

def test_dead_interface_absent():
    assert not hasattr(ak, "stock_a_indicator_lg")  # 决策书纸面接口, 实测失效

def test_required_interfaces_exist():
    missing = [f for f in EXIST if not hasattr(ak, f)]
    assert missing == [], f"missing akshare interfaces: {missing}"

def test_baidu_valuation_has_indicator_period():
    params = set(inspect.signature(ak.stock_zh_valuation_baidu).parameters)
    assert {"symbol", "indicator", "period"} <= params
```

- [ ] **Step 2: 跑测试看失败/通过**

Run: `python -m pytest tests/test_akshare_contract.py -q`
Expected: 全绿（akshare 已装；这些事实已实测）。若 `test_required_interfaces_exist` 红，记录缺失项并据此修订 factor_meta 接口列。

- [ ] **Step 3: 写 smoke 脚本**

```python
# scripts/akshare_smoke.py
"""M0 接口实测：联网逐接口验证签名/返回形态。失败接口打印后继续, 不抛。"""
import inspect, akshare as ak
IFACES = {
  "index_stock_cons_csindex": dict(symbol="000906"),      # 中证800
  "stock_zh_a_spot_em": {},
  "stock_zh_valuation_baidu": dict(symbol="600519", indicator="市盈率(动)", period="近一年"),
  "stock_yjyg_em": dict(date="20240331"),
  "stock_hsgt_hold_stock_em": dict(market="北向", indicator="今日排行"),
  "stock_zh_a_gdhs_detail_em": dict(symbol="600519"),
  "stock_individual_info_em": dict(symbol="600519"),
  "stock_board_industry_name_em": {},
}
def main():
    for fn, kw in IFACES.items():
        f = getattr(ak, fn, None)
        if f is None:
            print(f"[MISS] {fn}"); continue
        try:
            df = f(**kw)
            cols = list(df.columns) if hasattr(df, "columns") else type(df).__name__
            print(f"[OK]   {fn} rows={len(df) if hasattr(df,'__len__') else '?'} cols={cols}")
        except Exception as e:
            print(f"[ERR]  {fn}: {type(e).__name__}: {str(e)[:80]}")
if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 提交**

```bash
git add scripts/akshare_smoke.py tests/test_akshare_contract.py
git commit -m "feat(quant-M0): akshare interface contract test + smoke script"
```

---

### Task M1.1: storage PIT schema（7 表 + WAL）

**Files:**
- Modify: `services/storage-service/db.py`
- Test: `tests/test_pit_db.py`

**Interfaces:**
- Produces: `init_pit_tables(path)` 建 7 表幂等；`init_db` 调用它；WAL 开启。后续任务消费这些表。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_pit_db.py
import importlib.util
def _db():
    s = importlib.util.spec_from_file_location("zdb_pit", "services/storage-service/db.py")
    m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m

def test_pit_tables_created(tmp_path):
    db = _db(); p = str(tmp_path/"pit.db"); db.init_db(p)
    import sqlite3
    c = sqlite3.connect(p)
    names = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for t in ["panel_daily","fundamentals_pit","index_membership","events",
              "factor_meta","factor_eval","portfolios"]:
        assert t in names, t
    db.init_db(p)  # 幂等
```

- [ ] **Step 2: 跑测试看失败**

Run: `python -m pytest tests/test_pit_db.py::test_pit_tables_created -q`
Expected: FAIL（表未建）。

- [ ] **Step 3: 实现**（在 db.py `init_db` 内追加，schema 见 spec §4 L0；此处给最小可跑骨架，字段按 spec）

```python
# services/storage-service/db.py — 在 init_db(path) 的 with _conn(path) as c: 块末尾追加
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
```

- [ ] **Step 4: 跑测试看通过 + 全量回归**

Run: `python -m pytest tests/test_pit_db.py tests/test_storage.py -q`
Expected: PASS（含既有 storage 测试不回归）。

- [ ] **Step 5: 提交**

```bash
git add services/storage-service/db.py tests/test_pit_db.py
git commit -m "feat(quant-M1): storage PIT schema (7 tables + WAL)"
```

---

### Task M1.2: 可见日对齐 + asof() 防前视查询（keystone）

**Files:**
- Modify: `services/storage-service/db.py`
- Test: `tests/test_pit_db.py`

**Interfaces:**
- Produces:
  - `visible_date(legal_deadline, disclosed_date) -> str`（纯函数：`min` 语义，None 安全）
  - `add_fundamental(path, symbol, period, field, value, legal_deadline, disclosed_date, source, pit_status)`
  - `asof_fundamental(path, symbol, field, as_of) -> dict|None`（返回 `announce_date<=as_of` 最近一条 + pit_status）

- [ ] **Step 1: 写失败测试**

```python
# 追加到 tests/test_pit_db.py
def test_visible_date_min_semantics():
    db = _db()
    assert db.visible_date("2024-04-30", "2024-01-31") == "2024-01-31"  # 真披露日提前
    assert db.visible_date("2024-04-30", None) == "2024-04-30"          # 无披露日回退法定
    assert db.visible_date(None, "2024-01-31") == "2024-01-31"

def test_asof_returns_visible_version_only(tmp_path):
    db = _db(); p = str(tmp_path/"asof.db"); db.init_db(p)
    # 两个版本: 早版本 announce 2024-01-31, 晚版本 2024-04-30
    db.add_fundamental(p, "600519", "2023Q4", "roe", 0.20, "2024-04-30", "2024-01-31", "x", "lagged_disclosed")
    db.add_fundamental(p, "600519", "2024Q1", "roe", 0.22, "2024-04-30", None,         "x", "lagged_legal_deadline")
    # as_of=2024-02-15: 只能看到早披露的 2023Q4 版
    r = db.asof_fundamental(p, "600519", "roe", "2024-02-15")
    assert r is not None and r["value"] == 0.20 and r["announce_date"] == "2024-01-31"
    # as_of=2024-01-01: 都不可见
    assert db.asof_fundamental(p, "600519", "roe", "2024-01-01") is None
```

- [ ] **Step 2: 跑测试看失败**

Run: `python -m pytest tests/test_pit_db.py -k "visible_date or asof_returns" -q`
Expected: FAIL（函数未定义）。

- [ ] **Step 3: 实现**

```python
# services/storage-service/db.py
def visible_date(legal_deadline, disclosed_date):
    """可见日 = min(法定截止日, 真披露日); None 安全, 取较早的非空者。"""
    cands = [d for d in (legal_deadline, disclosed_date) if d]
    return min(cands) if cands else None

def add_fundamental(path, symbol, period, field, value, legal_deadline,
                    disclosed_date, source, pit_status):
    ad = visible_date(legal_deadline, disclosed_date)
    with _conn(path) as c:
        c.execute("INSERT OR REPLACE INTO fundamentals_pit"
                  "(symbol,period,announce_date,legal_deadline,disclosed_date,field,value,source,pit_status,ingest_ts)"
                  " VALUES(?,?,?,?,?,?,?,?,?,?)",
                  (symbol, period, ad, legal_deadline, disclosed_date, field, value, source, pit_status, _now()))

def asof_fundamental(path, symbol, field, as_of):
    with _conn(path) as c:
        r = c.execute("SELECT * FROM fundamentals_pit WHERE symbol=? AND field=? AND announce_date<=? "
                      "ORDER BY announce_date DESC LIMIT 1", (symbol, field, as_of)).fetchone()
        return dict(r) if r else None
```

- [ ] **Step 4: 跑测试看通过**

Run: `python -m pytest tests/test_pit_db.py -q`
Expected: PASS（防前视：未来披露不泄漏；提前披露提前可见）。

- [ ] **Step 5: 提交**

```bash
git add services/storage-service/db.py tests/test_pit_db.py
git commit -m "feat(quant-M1): visible-date alignment + asof() look-ahead-safe query"
```

---

### Task M1.3: panel_daily 写入/asof + universe(date, lsy_filter)

**Files:**
- Modify: `services/storage-service/db.py`
- Test: `tests/test_pit_db.py`

**Interfaces:**
- Produces:
  - `add_panel(path, symbol, date, field, value, source, visible_date)`
  - `asof_panel(path, symbol, field, as_of) -> dict|None`（`visible_date<=as_of` 最近）
  - `add_membership(path, date, symbol, weight, index_code, universe_pit_status)`
  - `universe(path, date, lsy_filter='off') -> list[dict]`（`date<=t` 最近快照的成分；lsy 档剔 ST/名称含 ST，市值过滤留待面板接入后增强）

- [ ] **Step 1: 写失败测试**

```python
# 追加到 tests/test_pit_db.py
def test_asof_panel(tmp_path):
    db = _db(); p = str(tmp_path/"pn.db"); db.init_db(p)
    db.add_panel(p, "600519", "2024-01-10", "pe", 30.0, "baidu", "2024-01-10")
    db.add_panel(p, "600519", "2024-01-20", "pe", 28.0, "baidu", "2024-01-20")
    assert db.asof_panel(p, "600519", "pe", "2024-01-15")["value"] == 30.0
    assert db.asof_panel(p, "600519", "pe", "2024-01-25")["value"] == 28.0

def test_universe_membership_and_lsy(tmp_path):
    db = _db(); p = str(tmp_path/"u.db"); db.init_db(p)
    db.add_membership(p, "2024-01-01", "600519", 1.0, "000906", "today_snapshot_only")
    db.add_membership(p, "2024-01-01", "ST康美", 0.1, "000906", "today_snapshot_only")
    allu = db.universe(p, "2024-06-01")
    assert {x["symbol"] for x in allu} == {"600519", "ST康美"}
    lsy = db.universe(p, "2024-06-01", lsy_filter="on")
    assert "ST康美" not in {x["symbol"] for x in lsy}  # ST 剔除
```

- [ ] **Step 2: 跑测试看失败**

Run: `python -m pytest tests/test_pit_db.py -k "asof_panel or universe_membership" -q`
Expected: FAIL.

- [ ] **Step 3: 实现**

```python
# services/storage-service/db.py
def add_panel(path, symbol, date, field, value, source, visible_date):
    with _conn(path) as c:
        c.execute("INSERT OR REPLACE INTO panel_daily(symbol,date,field,value,source,visible_date,ingest_ts)"
                  " VALUES(?,?,?,?,?,?,?)", (symbol, date, field, value, source, visible_date, _now()))

def asof_panel(path, symbol, field, as_of):
    with _conn(path) as c:
        r = c.execute("SELECT * FROM panel_daily WHERE symbol=? AND field=? AND visible_date<=? "
                      "ORDER BY visible_date DESC LIMIT 1", (symbol, field, as_of)).fetchone()
        return dict(r) if r else None

def add_membership(path, date, symbol, weight, index_code, universe_pit_status):
    with _conn(path) as c:
        c.execute("INSERT OR REPLACE INTO index_membership(date,symbol,weight,index_code,universe_pit_status)"
                  " VALUES(?,?,?,?,?)", (date, symbol, weight, index_code, universe_pit_status))

def universe(path, date, lsy_filter="off"):
    with _conn(path) as c:
        snap = c.execute("SELECT MAX(date) d FROM index_membership WHERE date<=?", (date,)).fetchone()["d"]
        if not snap:
            return []
        rows = [dict(r) for r in c.execute(
            "SELECT * FROM index_membership WHERE date=?", (snap,)).fetchall()]
    if lsy_filter == "on":
        rows = [r for r in rows if "ST" not in (r["symbol"] or "")]  # 市值/次新过滤待面板接入增强
    return rows
```

- [ ] **Step 4: 跑测试看通过 + 全量回归**

Run: `python -m pytest tests/ -q`
Expected: PASS（全绿）。

- [ ] **Step 5: 提交**

```bash
git add services/storage-service/db.py tests/test_pit_db.py
git commit -m "feat(quant-M1): panel asof + universe(date,lsy_filter)"
```

---

### Task M1.4: storage PIT REST 端点

**Files:**
- Modify: `services/storage-service/app.py`
- Test: `tests/test_storage.py`

**Interfaces:**
- Produces: `POST /pit/fundamental`, `POST /pit/panel`, `POST /pit/membership`, `GET /pit/universe?date&lsy_filter`, `GET /pit/asof?symbol&field&date&kind`（kind∈{panel,fundamental}）。

- [ ] **Step 1: 写失败测试**（TestClient，沿用既有 test_finance_api reload 范式）

```python
# 追加到 tests/test_storage.py
def test_pit_endpoints(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path/"pit_api.db"))
    import importlib, sys
    sys.path.insert(0, "services/storage-service")
    app_mod = importlib.import_module("app"); importlib.reload(app_mod)
    from fastapi.testclient import TestClient
    with TestClient(app_mod.app) as cli:
        assert cli.post("/pit/membership", json={"date":"2024-01-01","symbol":"600519",
            "weight":1.0,"index_code":"000906","universe_pit_status":"today_snapshot_only"}).status_code==200
        u = cli.get("/pit/universe", params={"date":"2024-06-01"}).json()
        assert any(x["symbol"]=="600519" for x in u)
        assert cli.post("/pit/fundamental", json={"symbol":"600519","period":"2023Q4","field":"roe",
            "value":0.2,"legal_deadline":"2024-04-30","disclosed_date":"2024-01-31",
            "source":"x","pit_status":"lagged_disclosed"}).status_code==200
        r = cli.get("/pit/asof", params={"symbol":"600519","field":"roe","date":"2024-02-15","kind":"fundamental"}).json()
        assert r["value"]==0.2
```

- [ ] **Step 2: 跑测试看失败**

Run: `python -m pytest tests/test_storage.py::test_pit_endpoints -q`
Expected: FAIL（404/405）。

- [ ] **Step 3: 实现**（在 app.py 追加端点 + pydantic 模型）

```python
# services/storage-service/app.py
class FundamentalIn(BaseModel):
    symbol: str; period: str; field: str; value: float | None = None
    legal_deadline: str | None = None; disclosed_date: str | None = None
    source: str = ""; pit_status: str = ""
class PanelIn(BaseModel):
    symbol: str; date: str; field: str; value: float | None = None
    source: str = ""; visible_date: str = ""
class MembershipIn(BaseModel):
    date: str; symbol: str; weight: float = 0.0; index_code: str = "000906"
    universe_pit_status: str = "today_snapshot_only"

@app.post("/pit/fundamental")
def pit_add_fundamental(f: FundamentalIn):
    db.add_fundamental(DB_PATH, f.symbol, f.period, f.field, f.value, f.legal_deadline,
                       f.disclosed_date, f.source, f.pit_status); return {"ok": True}
@app.post("/pit/panel")
def pit_add_panel(p: PanelIn):
    db.add_panel(DB_PATH, p.symbol, p.date, p.field, p.value, p.source, p.visible_date); return {"ok": True}
@app.post("/pit/membership")
def pit_add_membership(m: MembershipIn):
    db.add_membership(DB_PATH, m.date, m.symbol, m.weight, m.index_code, m.universe_pit_status); return {"ok": True}
@app.get("/pit/universe")
def pit_universe(date: str, lsy_filter: str = "off"):
    return db.universe(DB_PATH, date, lsy_filter)
@app.get("/pit/asof")
def pit_asof(symbol: str, field: str, date: str, kind: str = "panel"):
    r = db.asof_fundamental(DB_PATH, symbol, field, date) if kind == "fundamental" \
        else db.asof_panel(DB_PATH, symbol, field, date)
    return r or {"value": None, "abstain_reason": "data_missing"}
```

- [ ] **Step 4: 跑测试看通过 + 全量回归**

Run: `python -m pytest tests/ -q`
Expected: PASS.

- [ ] **Step 5: 提交**

```bash
git add services/storage-service/app.py tests/test_storage.py
git commit -m "feat(quant-M1): storage PIT REST endpoints"
```

---

### Task M1.5: ingestion akfetch 解析器（双粒度，离线可测）

**Files:**
- Create: `services/ingestion-service/akfetch.py`
- Test: `tests/test_akfetch.py`

**Interfaces:**
- Produces:
  - `CROSS_SECTION_APIS`, `PER_SYMBOL_APIS`（dict 元数据）
  - `parse_baidu_valuation(df_like) -> list[dict]`（单指标×period→[{date,value}]）
  - `parse_csindex_cons(df_like, index_code) -> list[dict]`（成分→membership 行，标 today_snapshot_only）
  - `legal_deadline_for(period) -> str`（报告期→法定截止日）

- [ ] **Step 1: 写失败测试**（离线，构造 DataFrame fixture）

```python
# tests/test_akfetch.py
import importlib.util
import pandas as pd
def _af():
    s = importlib.util.spec_from_file_location("af", "services/ingestion-service/akfetch.py")
    m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m

def test_legal_deadline():
    af = _af()
    assert af.legal_deadline_for("2023Q4") == "2024-04-30"   # 年报
    assert af.legal_deadline_for("2024Q1") == "2024-04-30"
    assert af.legal_deadline_for("2024Q2") == "2024-08-31"
    assert af.legal_deadline_for("2024Q3") == "2024-10-31"

def test_parse_baidu_valuation():
    af = _af()
    df = pd.DataFrame({"date": ["2024-01-02","2024-01-03"], "value": ["30.5","28.1"]})
    out = af.parse_baidu_valuation(df)
    assert out == [{"date":"2024-01-02","value":30.5}, {"date":"2024-01-03","value":28.1}]

def test_parse_csindex_cons():
    af = _af()
    df = pd.DataFrame({"品种代码": ["600519","000001"], "品种名称": ["贵州茅台","平安银行"], "权重": [1.2, 0.8]})
    out = af.parse_csindex_cons(df, "000906")
    assert len(out) == 2 and out[0]["symbol"] == "600519"
    assert all(r["universe_pit_status"] == "today_snapshot_only" for r in out)
```

- [ ] **Step 2: 跑测试看失败**

Run: `python -m pytest tests/test_akfetch.py -q`
Expected: FAIL（模块缺失）。

- [ ] **Step 3: 实现**（防御式解析；网络调用单独函数，解析纯函数可测）

```python
# services/ingestion-service/akfetch.py
"""akshare 采集适配层(双粒度)。解析为纯函数(离线可测); 网络调用经 anyio.to_thread 卸载。"""
CROSS_SECTION_APIS = {
  "index_stock_cons_csindex": "symbol=指数代码, 无 date 参 → 今日成分快照",
  "stock_zh_a_spot_em": "全市场快照(动态PE/PB/总市值/换手/量比)",
  "stock_yjyg_em": "date=报告期 → 全市场业绩预告(真披露日)",
  "stock_yjkb_em": "date=报告期 → 全市场业绩快报(真披露日)",
  "stock_hsgt_hold_stock_em": "market+indicator → 全市场北向排名快照",
  "stock_board_industry_name_em": "全市场一级行业列表",
}
PER_SYMBOL_APIS = {
  "stock_zh_valuation_baidu": "symbol+indicator+period → 单指标 date+value 时序",
  "stock_financial_analysis_indicator": "symbol → 多年财务(报告期末索引)",
  "stock_individual_info_em": "symbol → 个股行业归属",
  "stock_zh_a_gdhs_detail_em": "symbol → 股东户数明细",
  "stock_individual_fund_flow": "symbol → 资金流",
}
_LEGAL = {"Q1": ("04","30"), "Q2": ("08","31"), "Q3": ("10","31"), "Q4": ("04","30")}

def legal_deadline_for(period):
    """报告期 '2023Q4' → 法定截止日; 年报(Q4)落次年4/30。"""
    yr = int(period[:4]); q = period[-2:]
    mm, dd = _LEGAL[q]
    if q == "Q4":
        yr += 1
    return f"{yr}-{mm}-{dd}"

def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None

def parse_baidu_valuation(df):
    rows = df.to_dict("records") if hasattr(df, "to_dict") else list(df)
    out = []
    for r in rows:
        d = r.get("date"); v = _num(r.get("value"))
        if d and v is not None:
            out.append({"date": str(d)[:10], "value": v})
    return out

def parse_csindex_cons(df, index_code):
    rows = df.to_dict("records") if hasattr(df, "to_dict") else list(df)
    out = []
    for r in rows:
        sym = r.get("品种代码") or r.get("成分券代码") or r.get("symbol")
        if not sym:
            continue
        out.append({"date": None, "symbol": str(sym), "weight": _num(r.get("权重")) or 0.0,
                    "index_code": index_code, "universe_pit_status": "today_snapshot_only"})
    return out
```

- [ ] **Step 4: 跑测试看通过**

Run: `python -m pytest tests/test_akfetch.py -q`
Expected: PASS.

- [ ] **Step 5: 提交**

```bash
git add services/ingestion-service/akfetch.py tests/test_akfetch.py
git commit -m "feat(quant-M1): akfetch dual-granularity parsers (baidu valuation/csindex/legal-deadline)"
```

---

### Task M1.6: mcp-tool pit_panel realtime 只读工具

**Files:**
- Create: `services/mcp-tool-service/pit_panel.py`
- Modify: `services/mcp-tool-service/mcp_server.py`
- Test: `tests/test_pit_panel.py`

**Interfaces:**
- Produces: `pit_panel.universe_from_rows(rows, lsy_filter)`（纯函数, 供 MCP 工具与测试）；mcp_server 注册 realtime 工具 `get_universe`/`asof_value`（经 httpx 读 storage `/pit/*`）。
- Consumes: storage `/pit/universe`, `/pit/asof`.

- [ ] **Step 1: 写失败测试**（纯函数层离线可测；MCP I/O 层标 execution_mode）

```python
# tests/test_pit_panel.py
import importlib.util
def _pp():
    s = importlib.util.spec_from_file_location("pp", "services/mcp-tool-service/pit_panel.py")
    m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m

def test_universe_from_rows_lsy():
    pp = _pp()
    rows = [{"symbol":"600519"}, {"symbol":"ST康美"}]
    assert {r["symbol"] for r in pp.universe_from_rows(rows, "on")} == {"600519"}
    assert {r["symbol"] for r in pp.universe_from_rows(rows, "off")} == {"600519","ST康美"}

def test_execution_mode_realtime():
    pp = _pp()
    assert pp.EXECUTION_MODE == "realtime"
```

- [ ] **Step 2: 跑测试看失败**

Run: `python -m pytest tests/test_pit_panel.py -q`
Expected: FAIL.

- [ ] **Step 3: 实现**（pit_panel.py 纯函数 + storage 读取；mcp_server 注册工具）

```python
# services/mcp-tool-service/pit_panel.py
"""L0 PIT 面板 realtime 只读工具(轻量 SQLite 经 storage REST; 毫秒级)。"""
import os
import httpx
EXECUTION_MODE = "realtime"
STORAGE_URL = os.getenv("STORAGE_URL", "http://storage-service:8003").rstrip("/")

def universe_from_rows(rows, lsy_filter="off"):
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
```

```python
# services/mcp-tool-service/mcp_server.py — 追加
import pit_panel

@mcp.tool()
async def get_universe(date: str, lsy_filter: str = "off") -> dict:
    """[realtime] 中证800 时点成分(date<=t 最近快照; lsy_filter=on 剔ST/小票)。"""
    return await pit_panel.fetch_universe(date, lsy_filter)

@mcp.tool()
async def asof_value(symbol: str, field: str, date: str, kind: str = "panel") -> dict:
    """[realtime] 防前视时点取值(visible_date<=date 最近)。kind∈{panel,fundamental}。"""
    return await pit_panel.fetch_asof(symbol, field, date, kind)
```

- [ ] **Step 4: 跑测试看通过 + 全量回归 + import 健全**

Run: `python -m pytest tests/ -q && python -c "import sys; sys.path.insert(0,'services/mcp-tool-service'); import mcp_server; print('mcp OK')"`
Expected: PASS + `mcp OK`.

- [ ] **Step 5: 提交**

```bash
git add services/mcp-tool-service/pit_panel.py services/mcp-tool-service/mcp_server.py tests/test_pit_panel.py
git commit -m "feat(quant-M1): pit_panel realtime MCP read tools (get_universe/asof_value)"
```

---

## 后续里程碑（到达时各出独立计划，依 spec §14）

- **M2** L1+L2 核心（factor_dsl/preprocess/style_base/factor_eval/panel_cv/multi_test）— 纯算法、TDD 最密集、价值最高。
- **M3** L4 稳健档（portfolio.py HRP/ERC + LedoitWolf + vs 1/N；scipy/sklearn/cvxpy 入 requirements）。
- **M4** L3 横截面 ML（train_xsec promote-then-prove + 工件契约 + 跨容器 round-trip，agent-service py3.12）。
- **M5** 另类因子 + MVO + L5/L6 + governance R10–R13（两段式验收）。
- **M6** 委员会 4 新角色 + §10.3 个股映射 + 仪表盘。
- **M7** L7 LLM 证伪流水线（可选）。

每里程碑独立 TDD 全绿、可演示、可回退；forward_pit_only 因子受 §14.2 PIT 成熟度门约束。
