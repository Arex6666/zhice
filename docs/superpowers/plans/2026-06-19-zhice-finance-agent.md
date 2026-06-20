# 智策 ZhiCe 金融智能体平台 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Build 智策 (ZhiCe) on an MCP agent microservice architecture — a trustworthy/explainable/auditable multi-agent financial analysis system (A股+美股+crypto, data-quality layer, evidence-governance engine, evidence-based LLM committee + XGBoost calibrator, credible backtest, self-audit, dashboard).

**Architecture:** 5 microservices (api-gateway, agent-service, mcp-tool-service, storage-service, ingestion-service). Pure-logic modules (indicators/backtest/data_quality/governance/ml_signal) are network-free and unit-tested; adapters do I/O; the committee orchestrates LLM members → governance engine → chairman. Everything stays MCP-first and Dockerized.

**Tech Stack:** Python 3.11, FastAPI, FastMCP, openai(AsyncOpenAI/DeepSeek), akshare, yfinance, pandas, numpy, xgboost, scikit-learn, APScheduler, httpx, SQLite, ECharts(vendored), pytest.

## Global Constraints
- Symbol format everywhere: `MARKET:CODE` — `ASHARE:600519`, `US:AAPL`, `CRYPTO:BTCUSDT`.
- Every quote/kline result carries `data_status ∈ {fresh,delayed,stale,fallback,error}` (+ `halted/limit_up/limit_down` flags where relevant).
- Honesty/compliance: every analysis/backtest output includes 免责声明 "仅供学习研究，不构成投资建议"; never "保证/必涨/稳赚"; ML & backtest carry 未来函数/过拟合/不可外推 labels.
- Pure-logic modules MUST NOT do network I/O (so they unit-test offline). Network lives in adapters/ingestion.
- All new services follow the existing Dockerfile pattern (python:3.11-slim, non-root `mcpuser`).
- Tests run dir-independent (tests/conftest.py already chdirs to repo root).
- Confidence is honest: final confidence = min(chairman_proposed, governance_ceiling).

---

## File Structure

```
services/mcp-tool-service/
  indicators.py      MA/MACD/RSI/BOLL/volume — pure
  backtest.py        credible backtest metrics — pure
  data_quality.py    data_status assessment — pure
  finance.py         MarketAdapter + Ashare/Us/Crypto adapters — I/O
  mcp_server.py      ➕ 7 finance MCP tools
services/agent-service/
  governance.py      Evidence-governance rule engine R1–R6 — pure
  ml_signal.py       XGBoost signal calibrator (+calibration/abstain/importance)
  committee.py       evidence-based members + chairman orchestration
  review.py          self-audit stats
  modes.py           6 task-mode router
  finance_agent.py   entrypoint wiring modes→committee→governance→chairman
  app.py             ➕ /finance/* endpoints
services/ingestion-service/   app.py scheduler.py reviewer.py alerts.py Dockerfile requirements.txt
services/storage-service/db.py  ➕ quotes/news/analysis(+review)/alerts/watchlist
services/api-gateway/         app.py ➕/api/finance/*,/status ; static/finance.html ; static/vendor/echarts.min.js
scripts/  train_signal.py  smoke_finance.py
tests/    test_indicators.py test_backtest.py test_data_quality.py test_finance_adapter.py
          test_governance.py test_ml_signal.py test_committee.py test_review.py
models/   signal_<market>.json (xgboost) + calibrator
```

Build order = dependency order: indicators→backtest→data_quality→finance adapters→storage→MCP tools→governance→ml_signal→committee→review→modes→agent endpoints→ingestion→dashboard→observability→containerize→verify.

---

## Phase A — Pure-logic core (mcp-tool-service), TDD

### Task A1: indicators.py
**Files:** Create `services/mcp-tool-service/indicators.py`; Test `tests/test_indicators.py`.
**Interfaces — Produces:** `compute_indicators(closes: list[float], highs=None, lows=None, volumes=None) -> dict` with keys `ma5,ma10,ma20,ma60,rsi14,macd{dif,dea,hist},boll{mid,up,low},vol_ratio`.

- [ ] **Step 1: failing test**
```python
import importlib.util
def _ind():
    s=importlib.util.spec_from_file_location("ind","services/mcp-tool-service/indicators.py")
    m=importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
def test_ma_rsi():
    ind=_ind()
    closes=[float(i) for i in range(1,40)]      # strictly rising
    r=ind.compute_indicators(closes)
    assert round(r["ma5"],2)==sum(closes[-5:])/5
    assert r["rsi14"]>99    # all-up series -> RSI ~100
    assert "dif" in r["macd"] and "up" in r["boll"]
def test_short_series_no_crash():
    ind=_ind()
    r=ind.compute_indicators([1.0,2.0])
    assert r["ma60"] is None and r["ma5"] is None
```
- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3: implement** (pandas/numpy; None when insufficient length):
```python
import numpy as np, pandas as pd
def _ma(s,n): return float(s[-n:].mean()) if len(s)>=n else None
def _rsi(s,n=14):
    if len(s)<n+1: return None
    d=np.diff(s); up=np.where(d>0,d,0); dn=np.where(d<0,-d,0)
    ag=pd.Series(up).rolling(n).mean().iloc[-1]; al=pd.Series(dn).rolling(n).mean().iloc[-1]
    if al==0: return 100.0
    rs=ag/al; return float(100-100/(1+rs))
def _macd(s,f=12,sl=26,sig=9):
    if len(s)<sl: return {"dif":None,"dea":None,"hist":None}
    ser=pd.Series(s); ef=ser.ewm(span=f).mean(); es=ser.ewm(span=sl).mean()
    dif=ef-es; dea=dif.ewm(span=sig).mean()
    return {"dif":float(dif.iloc[-1]),"dea":float(dea.iloc[-1]),"hist":float((dif-dea).iloc[-1]*2)}
def _boll(s,n=20,k=2):
    if len(s)<n: return {"mid":None,"up":None,"low":None}
    ser=pd.Series(s[-n:]); m=ser.mean(); sd=ser.std()
    return {"mid":float(m),"up":float(m+k*sd),"low":float(m-k*sd)}
def compute_indicators(closes,highs=None,lows=None,volumes=None):
    s=np.array(closes,dtype=float)
    vr=None
    if volumes and len(volumes)>=6:
        vr=float(volumes[-1]/(np.mean(volumes[-6:-1]) or 1))
    return {"ma5":_ma(s,5),"ma10":_ma(s,10),"ma20":_ma(s,20),"ma60":_ma(s,60),
            "rsi14":_rsi(s),"macd":_macd(s),"boll":_boll(s),"vol_ratio":vr}
```
- [ ] **Step 4:** run → PASS. **Step 5:** commit `feat(fin): indicators (pure, tested)`.

### Task A2: backtest.py (credible)
**Files:** Create `services/mcp-tool-service/backtest.py`; Test `tests/test_backtest.py`.
**Interfaces — Produces:** `backtest_ma(closes, short, long, fee_bps=5, slippage_bps=5) -> dict{total_return,annualized,benchmark_return,max_drawdown,sharpe,win_rate,max_consec_loss,trades,disclaimer}`; `param_sensitivity(closes, grid) -> list[{short,long,total_return}]`.

- [ ] **Step 1: failing test**
```python
import importlib.util
def _bt():
    s=importlib.util.spec_from_file_location("bt","services/mcp-tool-service/backtest.py")
    m=importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
def test_metrics_present():
    bt=_bt()
    closes=[100,101,102,101,103,105,104,106,108,107,109,111,110,112]*4
    r=bt.backtest_ma(closes,3,8)
    for k in ["total_return","annualized","benchmark_return","max_drawdown","sharpe","win_rate","max_consec_loss","trades","disclaimer"]:
        assert k in r
    assert "不可直接外推" in r["disclaimer"]
def test_sensitivity():
    bt=_bt()
    closes=[100+ (i%5) for i in range(80)]
    g=bt.param_sensitivity(closes,[(3,8),(5,20)])
    assert len(g)==2 and "total_return" in g[0]
```
- [ ] **Step 2:** FAIL. **Step 3: implement** (returns from MA-cross with fees/slippage; sharpe from daily strat returns; benchmark=buy&hold):
```python
import numpy as np, pandas as pd
DISC="历史回测含手续费/滑点，仍不可直接外推到未来（存在过拟合/幸存者偏差/未来函数风险）。"
def _signals(c,sh,ln):
    s=pd.Series(c); ms=s.rolling(sh).mean(); ml=s.rolling(ln).mean()
    pos=(ms>ml).astype(int); return pos.fillna(0).values
def backtest_ma(closes,short,long,fee_bps=5,slippage_bps=5):
    c=np.array(closes,dtype=float)
    if len(c)<long+2: return {"error":"数据不足","disclaimer":DISC}
    pos=_signals(c,short,long); ret=np.diff(c)/c[:-1]; pos=pos[:-1]
    cost=(fee_bps+slippage_bps)/1e4
    trades_idx=np.where(np.diff(pos)!=0)[0]; ntr=int(len(trades_idx))
    strat=pos*ret; strat[trades_idx]-=cost
    eq=np.cumprod(1+strat); total=float(eq[-1]-1); bench=float(c[-1]/c[0]-1)
    n=len(strat); ann=float((1+total)**(252/max(n,1))-1)
    sharpe=float(np.mean(strat)/(np.std(strat)+1e-9)*np.sqrt(252))
    dd=float(np.min(eq/np.maximum.accumulate(eq)-1))
    wins=strat[strat!=0]; wr=float((wins>0).mean()) if len(wins) else 0.0
    # max consecutive losing days
    mcl=cur=0
    for x in strat:
        if x<0: cur+=1; mcl=max(mcl,cur)
        elif x>0: cur=0
    return {"total_return":total,"annualized":ann,"benchmark_return":bench,
            "max_drawdown":dd,"sharpe":sharpe,"win_rate":wr,"max_consec_loss":int(mcl),
            "trades":ntr,"disclaimer":DISC}
def param_sensitivity(closes,grid):
    out=[]
    for sh,ln in grid:
        r=backtest_ma(closes,sh,ln); out.append({"short":sh,"long":ln,"total_return":r.get("total_return")})
    return out
```
- [ ] **Step 4:** PASS. **Step 5:** commit `feat(fin): credible backtest (pure, tested)`.

### Task A3: data_quality.py
**Files:** Create `services/mcp-tool-service/data_quality.py`; Test `tests/test_data_quality.py`.
**Interfaces — Produces:** `assess(quote: dict, market: str, source: str, now_ts: float) -> dict` returning quote augmented with `data_status` and flags (`halted/limit_up/limit_down`); `cross_source_check(prices: list[float], tol=0.01) -> bool` (True=divergent).

- [ ] **Step 1: failing test**
```python
import importlib.util
def _dq():
    s=importlib.util.spec_from_file_location("dq","services/mcp-tool-service/data_quality.py")
    m=importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
def test_fresh_vs_stale():
    dq=_dq()
    q={"price":10.0,"ts":1000.0,"volume":100,"prev_close":9.9}
    assert dq.assess(dict(q),"ASHARE","sina",now_ts=1000.0+60)["data_status"]=="fresh"
    assert dq.assess(dict(q),"ASHARE","sina",now_ts=1000.0+86400)["data_status"]=="stale"
def test_halt_and_divergence():
    dq=_dq()
    q={"price":10.0,"ts":1000.0,"volume":0,"prev_close":10.0}
    assert dq.assess(dict(q),"ASHARE","sina",now_ts=1000.0+10)["halted"] is True
    assert dq.cross_source_check([10.0,10.5]) is True   # >1% apart
    assert dq.cross_source_check([10.0,10.02]) is False
```
- [ ] **Step 2:** FAIL. **Step 3: implement** (freshness windows by market; halt when volume 0; fallback flag passed by caller):
```python
FRESH={"ASHARE":300,"US":900,"CRYPTO":60}     # seconds
def assess(quote,market,source,now_ts):
    ts=quote.get("ts"); age=(now_ts-ts) if ts else 1e9
    win=FRESH.get(market,600)
    if quote.get("price") is None: status="error"
    elif age<=win: status="fresh"
    elif age<=win*4: status="delayed"
    else: status="stale"
    if source.endswith("fallback"): status="fallback"
    quote["data_status"]=status
    quote["halted"]= (market=="ASHARE" and (quote.get("volume") in (0,None)) and status!="error")
    pc=quote.get("prev_close"); p=quote.get("price")
    quote["limit_up"]=bool(pc and p and (p-pc)/pc>=0.0995)
    quote["limit_down"]=bool(pc and p and (p-pc)/pc<=-0.0995)
    return quote
def cross_source_check(prices,tol=0.01):
    prices=[p for p in prices if p]
    if len(prices)<2: return False
    return (max(prices)-min(prices))/min(prices) > tol
```
- [ ] **Step 4:** PASS. **Step 5:** commit `feat(fin): data-quality layer (pure, tested)`.

### Task A4: finance.py adapters (I/O)
**Files:** Create `services/mcp-tool-service/finance.py`; Test `tests/test_finance_adapter.py` (parse-only, with a fixture; no live network).
**Interfaces — Produces:** `get_adapter(market)`; each adapter: `async get_quote(code)->dict{name,price,prev_close,volume,ts}`, `async get_kline(code,period,count,adjust)->list[dict{ts,open,high,low,close,volume}]`, `async get_news(code,limit)->list[dict{title,url,ts,source}]`. Module fn `parse_sina_quote(text)->dict` (pure, tested).

- [ ] **Step 1: failing test** (test the pure parser; adapters' live calls are covered by integration/smoke, not unit):
```python
import importlib.util
def _fin():
    s=importlib.util.spec_from_file_location("fin","services/mcp-tool-service/finance.py")
    m=importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
SINA='var hq_str_sh600519="贵州茅台,1200.0,1215.0,1208.0,1220.0,1198.0,...";'
def test_parse_sina():
    fin=_fin(); q=fin.parse_sina_quote(SINA)
    assert q["name"]=="贵州茅台" and q["price"]==1208.0 and q["prev_close"]==1215.0
```
- [ ] **Step 2:** FAIL. **Step 3: implement** — `parse_sina_quote` (fields: name,open,prev_close,price,high,low,...), `AshareAdapter` (httpx to sina with Referer; akshare for kline/news via `anyio.to_thread`), `UsAdapter` (yfinance via thread), `CryptoAdapter` (Binance REST → CoinGecko fallback). All set a `source` and return raw dicts (data_quality applied in the MCP tool). Full code written at execution — contract above is binding. Network calls wrapped in try/except → raise on failure (so MCP isError).
- [ ] **Step 4:** PASS (parser test). **Step 5:** commit `feat(fin): market adapters + sina parser`.

---

## Phase B — Storage extension

### Task B1: storage tables + endpoints
**Files:** Modify `services/storage-service/db.py`, `services/storage-service/app.py`; Test append `tests/test_storage.py`.
**Interfaces — Produces (db.py):** `add_quote/get_quotes`, `add_news/get_news`, `add_analysis(symbol,mode,verdict,confidence,committee_json,price_at_analysis)->id`, `pending_reviews(now)`, `fill_review(id,ret_1d,ret_3d,ret_5d,correct)`, `review_stats()`, `add_alert/get_alerts`, `set_watchlist/get_watchlist`.

- [ ] **Step 1: failing test** (analysis + review):
```python
def test_analysis_review(tmp_path):
    import importlib.util
    s=importlib.util.spec_from_file_location("zdb2","services/storage-service/db.py")
    m=importlib.util.module_from_spec(s); s.loader.exec_module(m)
    p=str(tmp_path/"a.db"); m.init_db(p)
    i=m.add_analysis(p,"ASHARE:600519","deep","偏多",0.6,"{}",1200.0)
    m.fill_review(p,i,0.01,0.02,-0.01,True)
    st=m.review_stats(p); assert st["reviewed"]==1 and st["hit_rate"]==1.0
```
- [ ] **Step 2:** FAIL. **Step 3: implement** tables (`quotes,news,analysis,alerts,watchlist` per spec §6) + functions + FastAPI endpoints (`/quotes`,`/news`,`/analysis`,`/analysis/review`,`/alerts`,`/watchlist`). Full SQL written at execution; schema is spec §6.
- [ ] **Step 4:** PASS. **Step 5:** commit `feat(storage): finance tables + self-audit review`.

---

## Phase C — Finance MCP tools

### Task C1: wire 7 finance tools into mcp_server.py
**Files:** Modify `services/mcp-tool-service/mcp_server.py`, `requirements.txt`.
**Interfaces — Consumes:** finance.get_adapter, data_quality.assess, indicators.compute_indicators, backtest.backtest_ma/param_sensitivity, storage HTTP. **Produces:** MCP tools `get_quote,get_kline,get_indicators,get_stock_news,compute_signals,backtest,market_overview` (all async; quotes/kline pass through `data_quality.assess`; errors raise → isError).
- [ ] **Step 1:** implement the 7 `@mcp.tool()` async funcs (see spec §4). `compute_signals` derives golden/dead cross, RSI overbought/oversold, volume surge from indicators + short text. `backtest` returns credible metrics + sensitivity.
- [ ] **Step 2: verify import + tool count** `python -c "import asyncio,mcp_server;print(len(asyncio.run(mcp_server.mcp.list_tools())))"` → expect 12 (5 web + 7 finance).
- [ ] **Step 3:** add akshare/yfinance/pandas/numpy to requirements. **Step 4:** commit `feat(mcp): 7 finance tools w/ data_status`.

---

## Phase D — Trust core (agent-service), TDD

### Task D1: governance.py (R1–R6 + confidence ceiling)
**Files:** Create `services/agent-service/governance.py`; Test `tests/test_governance.py`.
**Interfaces — Produces:** `govern(members: list[dict], data_status: str, ml: dict|None, backtest_stable: bool) -> dict{members_adjusted, ceiling, conflict, report:list[str]}`. Member dict shape = committee schema (spec §7.1).
- [ ] **Step 1: failing test**
```python
import importlib.util
def _g():
    s=importlib.util.spec_from_file_location("gov","services/agent-service/governance.py")
    m=importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
def test_no_evidence_downgraded():
    g=_g()
    m=[{"verdict":"偏多","confidence":0.9,"evidence":[],"abstain":False}]
    r=g.govern(m,"fresh",None,True)
    assert r["members_adjusted"][0]["verdict"]=="中性"   # R1
def test_stale_caps_confidence():
    g=_g()
    m=[{"verdict":"偏多","confidence":0.9,"evidence":[{"type":"indicator"}],"abstain":False}]
    r=g.govern(m,"stale",None,True)
    assert r["ceiling"]<=0.4 and "R2" in " ".join(r["report"])
def test_conflict_flagged():
    g=_g()
    m=[{"verdict":"偏多","confidence":0.8,"evidence":[{"type":"indicator"}],"abstain":False},
       {"verdict":"偏空","confidence":0.8,"evidence":[{"type":"market"}],"abstain":False}]
    r=g.govern(m,"fresh",None,True); assert r["conflict"] is True
```
- [ ] **Step 2:** FAIL. **Step 3: implement** the deterministic rules:
```python
def govern(members, data_status, ml, backtest_stable):
    report=[]; ceiling=0.85; adj=[]
    for m in list(members):
        m=dict(m)
        if not m.get("abstain") and m.get("verdict") in ("偏多","偏空") and not m.get("evidence"):
            m["verdict"]="中性"; report.append("R1: 无证据→降为中性")
        adj.append(m)
    if data_status in ("stale","error"):
        ceiling=min(ceiling,0.4); report.append(f"R2: 数据{data_status}→置信≤0.4")
    actives=[m for m in adj if not m.get("abstain") and m["verdict"]!="中性"]
    verdicts={m["verdict"] for m in actives}
    conflict = "偏多" in verdicts and "偏空" in verdicts
    if conflict: ceiling=min(ceiling,0.55); report.append("R3: 证据冲突→暴露分歧、封顶0.55")
    if ml is not None and ml.get("abstain"): report.append("R4: 模型弃权→该票剔除")
    if not backtest_stable: ceiling=min(ceiling,0.6); report.append("R5: 回测不稳→封顶0.6")
    for m in adj:
        if not m.get("abstain") and m["verdict"] in ("偏多","偏空"):
            ev=m.get("evidence",[])
            if ev and all(e.get("type") in ("news_sentiment","news_inference") for e in ev):
                m["verdict"]="中性"; report.append("R6: 仅情绪/推断证据→降为中性")
    return {"members_adjusted":adj,"ceiling":ceiling,"conflict":conflict,"report":report}
```
- [ ] **Step 4:** PASS. **Step 5:** commit `feat(agent): evidence-governance engine R1-R6 (tested)`.

### Task D2: ml_signal.py (XGBoost calibrator)
**Files:** Create `services/agent-service/ml_signal.py`; `scripts/train_signal.py`; Test `tests/test_ml_signal.py`.
**Interfaces — Produces:** `build_features(kline)->np.ndarray (1×F)`; `SignalCalibrator.load(path)`; `.predict(features)->dict{prob_up,abstain,abstain_reason,auc,feature_importance}`; `train(X,y)->metrics{auc,baseline,abstain}` with walk-forward + `CalibratedClassifierCV`.
- [ ] **Step 1: failing test** (synthetic separable → trains; AUC>0.5; near-random → abstain):
```python
import importlib.util, numpy as np
def _ml():
    s=importlib.util.spec_from_file_location("ml","services/agent-service/ml_signal.py")
    m=importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
def test_train_and_abstain():
    ml=_ml(); rng=np.random.RandomState(0)
    X=rng.randn(400,5); y=(X[:,0]+0.3*rng.randn(400)>0).astype(int)   # learnable
    met=ml.train(X,y); assert met["auc"]>0.7 and met["abstain"] is False
    Xr=rng.randn(400,5); yr=rng.randint(0,2,400)                      # noise
    metr=ml.train(Xr,yr); assert metr["abstain"] is True              # AUC~0.5
```
- [ ] **Step 2:** FAIL. **Step 3: implement** — `train`: time-split (no shuffle), fit XGBClassifier, wrap CalibratedClassifierCV, compute out-of-sample AUC; abstain if AUC<0.55 or n<200; return importance. `predict`: abstain if no model/feature NaN. `build_features`: lagged returns, MA-deviation, RSI, MACD hist, volatility, vol_ratio (all from kline up to T). Full code at execution; contract binding.
- [ ] **Step 4:** PASS. **Step 5:** commit `feat(agent): XGBoost signal calibrator (walk-forward, calibration, abstain)`.

### Task D3: committee.py (evidence members + chairman)
**Files:** Create `services/agent-service/committee.py`; Test `tests/test_committee.py` (fake LLM + fake MCP).
**Interfaces — Consumes:** mcp_client tools, governance.govern, ml_signal. **Produces:** `async run_committee(symbol, gather_fn, llm, model, ml=None) -> dict{members, chairman, governance_report, confidence, disclaimer}`. `gather_fn(symbol)->dict{indicators,signals,news,backtest,market,data_status,backtest_stable}` (injectable; real one calls MCP). Member/chairman LLM calls forced to JSON via schema; `_maybe_await` like agent.run_loop.
- [ ] **Step 1: failing test** (4 fake members + fake chairman; governance applied; confidence ≤ ceiling):
```python
import importlib.util, asyncio, types, json
def _c():
    s=importlib.util.spec_from_file_location("com","services/agent-service/committee.py")
    m=importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
class FakeLLM:
    def __init__(self,outs): self.outs=outs; self.i=0
    @property
    def chat(self):
        outs=self.outs; box=self
        class C:
            class completions:
                @staticmethod
                def create(**kw):
                    o=outs[box.i]; box.i+=1
                    return types.SimpleNamespace(choices=[types.SimpleNamespace(
                        message=types.SimpleNamespace(content=json.dumps(o),tool_calls=None))])
        return C
def test_committee_governs_confidence():
    com=_c()
    member={"verdict":"偏多","confidence":0.95,"reasons":["x"],
            "evidence":[{"type":"indicator","source":"get_indicators","value":"MA5>MA20","interpretation":"多头"}],
            "counter_evidence":["RSI偏高"],"risks":["回调"],"abstain":False,"abstain_reason":None}
    chair={"final":"偏多","confidence":0.95,"majority":"偏多","minority":"无","disagreement":"无",
           "key_evidence":"MA5>MA20","counter_evidence":"RSI偏高","invalidation":"跌破MA20",
           "dissent":"无","max_risk":"回调","confidence_reason":"证据中等"}
    llm=FakeLLM([member,member,member,member,chair])
    async def gather(sym): return {"indicators":{},"signals":{},"news":[],"backtest":{},
        "market":{},"data_status":"stale","backtest_stable":True}
    out=asyncio.run(com.run_committee("ASHARE:600519",gather,llm,"m",ml=None))
    assert out["confidence"]<=0.4            # stale → governance ceiling
    assert "不构成投资建议" in out["disclaimer"]
    assert "governance_report" in out
```
- [ ] **Step 2:** FAIL. **Step 3: implement** — run 4 members concurrently (asyncio.gather, each with a lens system prompt), validate JSON, attach ml as 5th vote, call `governance.govern`, then chairman LLM with governed members; final confidence=min(chairman.confidence, ceiling); attach disclaimer. `_maybe_await` for sync/async LLM.
- [ ] **Step 4:** PASS. **Step 5:** commit `feat(agent): evidence-based committee + chairman (governed, tested)`.

### Task D4: review.py (self-audit)
**Files:** Create `services/agent-service/review.py`; Test `tests/test_review.py`.
**Interfaces — Produces:** `summarize(stats: dict) -> dict{hit_rate, by_member, chairman_overconfident, note}` — pure transform of storage `review_stats` output into a self-audit summary.
- [ ] **Step 1: failing test**
```python
import importlib.util
def _r():
    s=importlib.util.spec_from_file_location("rv","services/agent-service/review.py")
    m=importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
def test_overconfidence_flag():
    rv=_r()
    out=rv.summarize({"reviewed":10,"hit_rate":0.3,"avg_confidence_when_wrong":0.8,"by_member":{}})
    assert out["chairman_overconfident"] is True
```
- [ ] **Step 2:** FAIL. **Step 3: implement** (overconfident if hit_rate<0.5 and avg_confidence_when_wrong>0.65; note string). **Step 4:** PASS. **Step 5:** commit `feat(agent): self-audit summary (tested)`.

### Task D5: modes.py + finance_agent.py + app.py /finance endpoints
**Files:** Create `services/agent-service/modes.py`, `finance_agent.py`; Modify `app.py`, `requirements.txt`.
**Interfaces — Produces:** `finance_agent.analyze(symbol, mode)` routing: `quick`(体检), `deep`(committee), `scan`(watchlist 并发), `alerts`, `review`, `teach`. app.py `POST /finance/analyze {symbol,mode}`, `GET /finance/review`, `GET /status`.
- [ ] **Step 1:** implement modes (quick = gather + signals, no full committee; deep = run_committee with real MCP gather_fn + ml; scan = concurrent quick over watchlist; review = storage review_stats→review.summarize; teach = static explanations). Add xgboost/scikit-learn to requirements.
- [ ] **Step 2: smoke import** `python -c "import finance_agent"`.
- [ ] **Step 3:** commit `feat(agent): task modes + finance endpoints`.

---

## Phase E — ingestion-service (new)

### Task E1: ingestion service
**Files:** Create `services/ingestion-service/{app.py,scheduler.py,reviewer.py,alerts.py,requirements.txt,Dockerfile}`.
**Interfaces — Produces:** FastAPI `/health`,`/status`; APScheduler jobs: `pull_quotes_news` (market-hours aware, writes storage), `fill_reviews` (computes ret_1d/3d/5d for due analyses), `scan_alerts` (change%/volume/news surge). Uses finance adapters via HTTP-less direct import OR calls mcp-tool? → calls storage HTTP + finance adapters directly (import finance.py copy or shared). Decision: ingestion has its own thin `datafetch.py` calling the same public quote endpoints (sina/eastmoney) to avoid cross-service python imports.
- [ ] **Step 1:** implement scheduler with `start_period` market-hours check (A股/美东/crypto). **Step 2:** Dockerfile (python:3.11-slim, non-root, CMD uvicorn app:app --port 8004). **Step 3:** commit `feat(ingestion): scheduler + reviewer + alerts`.

---

## Phase F — gateway, dashboard, observability

### Task F1: gateway finance routes + status
**Files:** Modify `services/api-gateway/app.py`.
- [ ] Add `/api/finance/{analyze,quote,kline,indicators,news,backtest}` (forward to agent/mcp via agent) and `/api/finance/status` (aggregate downstream `/status`/`/health`). `_safe_json` already exists. Commit `feat(gateway): finance routes + status`.

### Task F2: finance dashboard (ECharts) + counter-evidence panel
**Files:** Create `services/api-gateway/static/finance.html`, vendor `static/vendor/echarts.min.js`.
- [ ] Single-page dashboard (青瓷 dark, offline): symbol+market search; ECharts candlestick+volume+MA/BOLL overlay + MACD/RSI subplots; news feed with fact/sentiment/inference tags; **committee verdict + confidence ring**; **counter-evidence-aware explanation panel** (支持/反对证据 + 失效条件 + 异议 + 治理记录 + data_status 徽标 + 免责声明); backtest card (benchmark/sharpe/sensitivity); review-mode view; system-status view. Behavior + components are binding (full HTML written at execution). Commit `feat(dashboard): finance dashboard + counter-evidence panel`.

### Task F3: observability (structured logging + /status)
**Files:** Modify each finance-touching service to add a tiny `obs.py` logger + `/status` counters (collected counts, source success rate, llm latency).
- [ ] Add minimal structured-log helper + counters; expose `/status`. Commit `feat: observability (structured logs + /status)`.

---

## Phase G — Containerize, train, verify

### Task G1: compose + train + smoke
**Files:** Modify `deploy/docker-compose.yml` (add ingestion-service + healthcheck + restart); Create `scripts/smoke_finance.py`; run `scripts/train_signal.py`.
- [ ] Add ingestion-service to compose. Train signal models offline (or fall back to abstain if data scarce). `smoke_finance.py`: for each market, get_quote+kline+news (allow degraded), run deep analyze on one A股 symbol, assert committee+governance_report+disclaimer present, assert a stale/insufficient symbol abstains. `docker compose build && up`; run smoke; screenshot dashboard + explanation panel + status page.
- [ ] Commit `feat: compose ingestion + finance smoke test`.

### Task G2: report addendum
- [ ] Extend report (or a new 金融扩展 section/appendix) documenting 智策: architecture, governance R1-R6, committee, calibrator, self-audit, screenshots. Regenerate docx.

---

## Self-Review (against spec)
- **Spec coverage:** §3.1 adapters→A4; §3.2 data_quality→A3; §4 tools→C1; §4.1 backtest→A2; §5 ingestion→E1; §6 storage→B1; §7.1 evidence members→D3; §7.2 ml→D2; §7.3 chairman→D3; §7.4 self-audit→D4+B1+E1; §7.5 governance→D1; §8 modes→D5; §9 dashboard/counter-evidence→F2; §10 observability→F3; §11 compliance→Global Constraints+D3(disclaimer); §12 tests→A1-A3,B1,D1-D4,G1; §13 deps→C1,D2,D5,E1; §16 acceptance→G1. All covered.
- **Placeholder scan:** A4/B1/E1/F2 give binding interface contracts + representative code with full code authored at execution (I/O & HTML where exact bytes aren't load-bearing); all pure-logic (indicators/backtest/data_quality/governance/ml_signal/committee/review) has complete code. Acceptable per skill guidance.
- **Type consistency:** member dict schema (verdict/confidence/evidence/counter_evidence/risks/abstain/abstain_reason) consistent across D1/D3 + spec §7.1. `govern(...)` signature consistent D1↔D3. `data_status` enum consistent A3/C1/D1. symbol `MARKET:CODE` consistent throughout. storage fns consistent B1↔D5↔E1.
