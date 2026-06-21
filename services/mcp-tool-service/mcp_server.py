"""mcp-tool-service: 智策金融数据工具的 FastMCP 服务器。

双传输 (dual transport):
  MCP_TRANSPORT=stdio  -> 供 `mcp dev` / MCP Inspector / Cline 使用（指导书第三~五步）
  MCP_TRANSPORT=sse    -> 在 :8002 暴露 HTTP/SSE，供 agent-service 跨容器调用（微服务模式）

设计：所有工具均为 async，网络 I/O 用 httpx.AsyncClient，避免阻塞 FastMCP 的事件循环；
行情/新闻抓取与解析封装在 finance.py，纯计算在 indicators.py / backtest.py（均可脱网单元测试）。
工具内部不吞异常——出错时抛出，由 FastMCP 自动置 isError=True，使客户端/智能体能感知失败。
"""
import math
import os
import time

import anyio

import httpx
from mcp.server.fastmcp import FastMCP

import finance
import data_quality
import indicators
import backtest as backtest_lib
import volatility as volatility_lib
import anomaly as anomaly_lib
import crossasset as crossasset_lib
import seasonality as seasonality_lib
import news_cluster as news_cluster_lib
import obs
import pit_panel
# —— 多因子选股引擎（L1–L6 纯函数） ——
import zoo as zoo_lib
import preprocess as preprocess_lib
import factor_eval as factor_eval_lib
import factor_combine as factor_combine_lib
import portfolio as portfolio_lib
import risk_model as risk_model_lib
import qvix_timing as qvix_lib
import regime_overlay as regime_lib
import ic_audit as ic_audit_lib
import factor_gate as factor_gate_lib
import multi_test as multi_test_lib
import alpha_eval as alpha_eval_lib
import altfactors as altfactors_lib
import industry_map as industry_map_lib

_ASHARE_INDEX = "ASHARE:sh000001"  # 上证指数（跨资产 β 默认基准）

METRICS = obs.Metrics()                 # 按数据源 调用/错误/命中/延迟
_QUOTE_CACHE = obs.TTLCache()           # 实时报价短 TTL 缓存（降限流风险）
_QUOTE_TTL = {"ASHARE": 30, "US": 60, "CRYPTO": 15}  # 各市场缓存秒数
_KLINE_CACHE = obs.TTLCache()           # K线缓存（图表+指标共享, 减外源重复调用; 日K日内变动小）
_KLINE_TTL = 180

HOST = os.getenv("MCP_HOST", "0.0.0.0")
PORT = int(os.getenv("MCP_PORT", "8002"))

mcp = FastMCP("ZhiCe Finance Tools", host=HOST, port=PORT)


# ============================ 金融 MCP 工具 ============================
def _enrich_quote(q, market):
    q = data_quality.assess(q, market, q.get("source", ""), now_ts=time.time())
    pc, p = q.get("prev_close"), q.get("price")
    q["change_pct"] = round((p - pc) / pc * 100, 3) if (pc and p) else None
    return q


async def _fetch_quote(symbol: str) -> dict:
    market, code = finance.split_symbol(symbol)
    q = await finance.get_adapter(market).get_quote(code)
    q = _enrich_quote(q, market)
    # 跨源价差校验（A股：新浪 vs 东财）——真正调用 data_quality.cross_source_check
    if market == "ASHARE" and q.get("price"):
        p2 = await finance.ashare_eastmoney_price(code)
        if p2 and data_quality.cross_source_check([q["price"], p2]):
            q["cross_source_divergent"] = True
            q["second_source_price"] = p2
            if q.get("data_status") == "fresh":
                q["data_status"] = "delayed"  # 双源不一致→降级，不再当作完全可信
    return q


@mcp.tool()
async def get_universe(date: str, lsy_filter: str = "off") -> dict:
    """[realtime] 中证800 时点成分(date<=t 最近快照; lsy_filter=on 剔 ST/小票)。多因子选股可投域。"""
    return await pit_panel.fetch_universe(date, lsy_filter)


@mcp.tool()
async def asof_value(symbol: str, field: str, date: str, kind: str = "panel",
                     indicator: str = None, period: str = None) -> dict:
    """[realtime] 防前视时点取值(visible_date/announce_date<=date 最近)。kind∈{panel,fundamental}。

    估值因子(百度)走 indicator×period 维度：给 indicator 时按 field:indicator:period 复合键检索
    (对齐 §4 L0 stock_zh_valuation_baidu 单指标×period 笛卡尔落库口径)。
    """
    key = f"{field}:{indicator}:{period or '默认'}" if indicator else field
    return await pit_panel.fetch_asof(symbol, key, date, kind)


@mcp.tool()
async def read_factor_eval(factor_name: str, as_of: str = None, universe_filter: str = "lsy") -> dict:
    """[realtime] 读 L2 离线落库的因子评估(委员会因子分析师用; 无记录返 data_missing 弃权)。"""
    return await pit_panel.fetch_factor_eval(factor_name, as_of, universe_filter)


@mcp.tool()
async def read_portfolio(portfolio_id: str, as_of: str = None) -> dict:
    """[realtime] 读 L4 离线落库的组合权重/对比1N/容量(委员会与仪表盘只读)。"""
    return await pit_panel.fetch_portfolio(portfolio_id, as_of)


@mcp.tool()
async def get_panel(date: str, fields: str = None) -> dict:
    """[realtime] 时点面板矩阵(每 symbol×field 取 visible_date<=date 最新值, 防前视)。fields 逗号分隔。"""
    return await pit_panel.fetch_panel(date, [f for f in (fields or "").split(",") if f] or None)


@mcp.tool()
async def data_coverage_report(date: str) -> dict:
    """[realtime] 时点数据覆盖度(面板股数/字段数/财务行数/可投域行数; 供冷启动进度与 backtestable_from)。"""
    return await pit_panel.fetch_coverage(date)


@mcp.tool()
async def pit_data_health() -> dict:
    """[realtime] PIT 数据地基健康度(各表行数 + universe PIT 状态; 诚实暴露幸存者偏差状态)。"""
    return await pit_panel.fetch_data_health()


@mcp.tool()
async def list_factor_meta(factor_name: str = None) -> dict:
    """[realtime] 列出/查询因子元数据(PIT状态/数据源/历史深度/方向/行业映射来源/caveat)。"""
    return await pit_panel.fetch_factor_meta(factor_name)


@mcp.tool()
async def get_quote(symbol: str) -> dict:
    """获取股票/加密货币实时报价（含数据质量标注 data_status；短 TTL 缓存 + 按源指标）。symbol 形如 ASHARE:600519 / US:AAPL / CRYPTO:BTCUSDT。"""
    market, _ = finance.split_symbol(symbol)
    cached = _QUOTE_CACHE.get(symbol)
    if cached is not None:
        METRICS.record(market, 0.0, ok=True, hit=True)
        return cached
    t0 = time.monotonic()
    try:
        q = await _fetch_quote(symbol)
    except Exception:
        METRICS.record(market, time.monotonic() - t0, ok=False)
        raise
    METRICS.record(q.get("source", market), time.monotonic() - t0, ok=q.get("data_status") != "error")
    _QUOTE_CACHE.set(symbol, q, _QUOTE_TTL.get(market, 30))
    return q


@mcp.tool()
async def get_quotes_batch(symbols: list) -> list:
    """[realtime] 批量实时行情（仪表盘盯盘墙用）：A股个股+指数经**单次 sina 调用**取回，含 data_status/change_pct。

    symbols 形如 ['ASHARE:600519','ASHARE:000858','ASHARE:sh000001']。非 A 股逐个回退 get_quote。
    """
    ashare_codes, ashare_syms, others = [], [], []
    for s in symbols:
        try:
            market, code = finance.split_symbol(s)
        except Exception:
            others.append(s)
            continue
        (ashare_syms.append(s) or ashare_codes.append(code)) if market == "ASHARE" else others.append(s)
    out = []
    if ashare_codes:
        try:
            raw = await finance.get_adapter("ASHARE").get_quotes_batch(ashare_codes)
        except Exception:
            raw = {}
        for s, code in zip(ashare_syms, ashare_codes):
            q = raw.get(code)
            if not q:
                out.append({"symbol": s, "error": "no_quote", "data_status": "error"})
                continue
            q = _enrich_quote(q, "ASHARE")   # data_status(据真实 ts) + change_pct（个股/指数一致重算）
            q["symbol"] = s
            out.append(q)
    for s in others:
        try:
            out.append({**(await get_quote(s)), "symbol": s})
        except Exception:
            out.append({"symbol": s, "error": "no_quote", "data_status": "error"})
    return out


@mcp.tool()
async def data_source_metrics() -> dict:
    """数据源健康：按源的 调用/错误率/缓存命中率/延迟（可观测性 §10）。"""
    return METRICS.snapshot()


async def _fetch_kline(symbol, period="daily", count=120, adjust="qfq"):
    """带 TTL 缓存的 K 线取数（图表与指标共享，杜绝同一研判内重复打外部源；外源慢/限流时显著提速）。"""
    key = f"kl|{symbol}|{period}|{count}|{adjust}"
    cached = _KLINE_CACHE.get(key)
    if cached is not None:
        return cached
    market, code = finance.split_symbol(symbol)
    kl = await finance.get_adapter(market).get_kline(code, period, count, adjust)
    if kl:
        _KLINE_CACHE.set(key, kl, _KLINE_TTL)
    return kl


@mcp.tool()
async def get_kline(symbol: str, period: str = "daily", count: int = 120, adjust: str = "qfq") -> list:
    """获取 K 线 OHLCV 历史。adjust ∈ {qfq 前复权, hfq 后复权, none}。"""
    return await _fetch_kline(symbol, period, count, adjust)


@mcp.tool()
async def get_indicators(symbol: str, period: str = "daily") -> dict:
    """计算技术指标 MA/MACD/RSI/BOLL/量能（基于 K 线）。"""
    kl = await _fetch_kline(symbol, period, 120, "qfq")
    closes = [r["close"] for r in kl]
    vols = [r["volume"] for r in kl]
    return indicators.compute_indicators(closes, volumes=vols)


@mcp.tool()
async def get_stock_news(symbol: str, limit: int = 8) -> list:
    """获取个股相关新闻并**跨源去重**（近重复头条折叠为一条，附 corroboration/k 源报道，防伪造共识）。"""
    market, code = finance.split_symbol(symbol)
    news = await finance.get_adapter(market).get_news(code, limit)
    return news_cluster_lib.dedupe_and_enrich(news) if news else news


@mcp.tool()
async def compute_signals(symbol: str) -> dict:
    """规则技术信号：金叉/死叉、RSI 超买超卖、放量、MACD 红绿柱 + 简短解读。"""
    ind = await get_indicators(symbol)
    sig = []
    ma5, ma20 = ind.get("ma5"), ind.get("ma20")
    if ma5 and ma20:
        sig.append("MA5 上穿 MA20（多头排列倾向）" if ma5 > ma20 else "MA5 下穿 MA20（空头排列倾向）")
    rsi = ind.get("rsi14")
    if rsi is not None:
        if rsi > 70:
            sig.append(f"RSI={rsi:.1f} 超买")
        elif rsi < 30:
            sig.append(f"RSI={rsi:.1f} 超卖")
    vr = ind.get("vol_ratio")
    if vr and vr > 2:
        sig.append(f"放量(量比 {vr:.1f})")
    hist = (ind.get("macd") or {}).get("hist")
    if hist is not None:
        sig.append("MACD 红柱（动能偏多）" if hist > 0 else "MACD 绿柱（动能偏空）")
    return {"signals": sig, "indicators": ind, "text": "；".join(sig) if sig else "无显著信号"}


@mcp.tool()
async def backtest(symbol: str, strategy: str = "ma", short: int = 5, long: int = 20) -> dict:
    """可信回测（双均线）：含手续费/滑点/基准/夏普/最大回撤/连亏/参数敏感性 + 不可外推标签。"""
    market, code = finance.split_symbol(symbol)
    kl = await finance.get_adapter(market).get_kline(code, "daily", 250)
    closes = [r["close"] for r in kl]
    res = backtest_lib.backtest_ma(closes, short, long)
    res["sensitivity"] = backtest_lib.param_sensitivity(
        closes, [(short, long), (short + 1, long + 1), (short + 3, long + 10)])
    return res


@mcp.tool()
async def get_volatility(symbol: str, period: str = "daily", window: int = 20) -> dict:
    """波动状态层：EWMA/Parkinson 已实现波动 + 当前波动在自身历史分布的分位 → 区间(low/normal/elevated/extreme)。"""
    market, code = finance.split_symbol(symbol)
    kl = await finance.get_adapter(market).get_kline(code, period, 250)
    return volatility_lib.vol_state(kl, window=window)


@mcp.tool()
async def detect_anomalies(symbol: str, period: str = "daily") -> dict:
    """稳健价量异动检测(MAD/Hampel)：区分疑似坏数据 vs 疑似真实事件(放量佐证)。"""
    market, code = finance.split_symbol(symbol)
    kl = await finance.get_adapter(market).get_kline(code, period, 250)
    return anomaly_lib.detect_anomalies(kl)


@mcp.tool()
async def get_market_context(symbol: str, benchmark: str = _ASHARE_INDEX, window: int = 60) -> dict:
    """跨资产上下文：个股相对基准(benchmark, 形如 ASHARE:sh000001)的 β/相关/R²/相对强弱/下行 β。"""
    m1, c1 = finance.split_symbol(symbol)
    m2, c2 = finance.split_symbol(benchmark)
    stock = await finance.get_adapter(m1).get_kline(c1, "daily", 250)
    try:
        bench = await finance.get_adapter(m2).get_kline(c2, "daily", 250)
    except Exception as e:  # 基准取数失败：返回明确错误而非伪造
        return {"beta": None, "reason": f"基准行情不可用：{e}", "benchmark": benchmark}
    res = crossasset_lib.beta_context([r["close"] for r in stock], [r["close"] for r in bench], window)
    res["benchmark"] = benchmark
    return res


@mcp.tool()
async def get_seasonality(symbol: str, period: str = "daily") -> dict:
    """季节性诊断：工作日收益效应 + 置换检验/BH 校正；无显著则诚实报告"与随机一致"。"""
    market, code = finance.split_symbol(symbol)
    kl = await finance.get_adapter(market).get_kline(code, period, 250)
    return seasonality_lib.day_of_week_effect(kl)


@mcp.tool()
async def market_overview(market: str = "ASHARE") -> dict:
    """大盘/指数概览。ASHARE 返回上证/深证/创业板指数报价。"""
    if market == "ASHARE":
        idx = {"上证指数": "sh000001", "深证成指": "sz399001", "创业板指": "sz399006"}
        out = {}
        async with httpx.AsyncClient(timeout=10, headers=finance.SINA_HEADERS) as c:
            r = await finance.aget(c, "https://hq.sinajs.cn/list=" + ",".join(idx.values()))
            r.encoding = "gbk"
            lines = r.text.strip().split("\n")
            for (name, _), ln in zip(idx.items(), lines):
                q = finance.parse_sina_quote(ln)
                out[name] = {"price": q["price"], "prev_close": q["prev_close"]}
        return {"market": market, "indices": out}
    return {"market": market, "note": "该市场概览暂以个股为主"}


# ============================ 多因子选股 MCP 工具 ============================
# realtime=轻量, 委员会 SSE 可直调; offline=重计算, 仅 scheduler 直调落库, 委员会硬拒(§3.4)。
async def _offload(fn, *a, **k):
    return await anyio.to_thread.run_sync(lambda: fn(*a, **k))


@mcp.tool()
async def list_factor_universe() -> list:
    """[realtime] 列出价量因子库(名称/方向/家族/PIT状态)。"""
    return zoo_lib.list_factors()


@mcp.tool()
async def compute_factor_series(factor_name: str, closes: list, opens: list = None,
                                highs: list = None, lows: list = None, volumes: list = None) -> dict:
    """[realtime] 用 DSL 计算命名价量因子时序(末值对齐)。"""
    data = {"C": closes, "O": opens or closes, "H": highs or closes,
            "L": lows or closes, "V": volumes or [1.0] * len(closes)}
    vals = zoo_lib.compute(factor_name, data)
    return {"factor": factor_name,
            "values": [None if not math.isfinite(v) else float(v) for v in vals],  # NaN/±Inf→null(合法JSON)
            "execution_mode": "realtime", **{k: v for k, v in zoo_lib.FACTORS[factor_name].items() if k != "formula"}}


@mcp.tool()
async def preprocess_cross_section(values: list, industries: list, ln_mktcap: list) -> dict:
    """[realtime] 逐截面预处理: MAD去极值→z-score→行业+ln市值中性化(残差)。"""
    w = preprocess_lib.mad_winsorize(values)
    z = preprocess_lib.zscore(w)
    return {**preprocess_lib.neutralize(z, industries, ln_mktcap), "execution_mode": "realtime"}


@mcp.tool()
async def combine_factors(panel: dict, directions: dict = None, ic_weights: dict = None) -> dict:
    """[realtime] 线性因子合成(等权/IC加权, 按方向)。"""
    return {"score": factor_combine_lib.combine(panel, directions, ic_weights),
            "execution_mode": "realtime"}


@mcp.tool()
async def get_qvix_timing(qvix_series: list, window: int = 250) -> dict:
    """[realtime] QVIX 隐含波动率分位→择时区间(沪深300恐慌代理)。"""
    return {**qvix_lib.qvix_level(qvix_series, window), "execution_mode": "realtime"}


@mcp.tool()
async def get_regime_overlay(vol_regime: str, qvix_level: str, floor: float = 0.5) -> dict:
    """[realtime] 已实现波动+QVIX→仓位乘子(只减不加, 取min)。"""
    return {**regime_lib.target_scale(vol_regime, qvix_level, floor), "execution_mode": "realtime"}


@mcp.tool()
async def ic_self_audit(ic_series: list) -> dict:
    """[realtime] IC 时序自审: ICIR/子区间一致/近期漂移→verdict(纯诊断)。"""
    return {**ic_audit_lib.audit(ic_series), "execution_mode": "realtime"}


@mcp.tool()
async def factor_report(factor_panel: list, fwd_panel: list, n_quantiles: int = 5) -> dict:
    """[offline] 单因子诊断: Rank-IC/ICIR/HAC-t/分层单调+显著性硬判定(scheduler 直调落库)。"""
    return {**await _offload(factor_eval_lib.factor_report, factor_panel, fwd_panel, n_quantiles),
            "execution_mode": "offline"}


@mcp.tool()
async def factor_family_gate(reports: list, alpha: float = 0.05) -> dict:
    """[offline] 因子家族 BH-FDR+Harvey 联合闸门。"""
    return {"gated": await _offload(factor_gate_lib.family_gate, reports, alpha),
            "execution_mode": "offline"}


@mcp.tool()
async def deflated_sharpe(sr: float, n_trials: int, var_sr_trials: float = None,
                          n_obs: int = 252) -> dict:
    """[offline] Deflated Sharpe(N与Var(SR_trials)同源, §7.2)。"""
    return {**await _offload(multi_test_lib.deflated_sharpe, sr, n_trials, var_sr_trials),
            "execution_mode": "offline"}


@mcp.tool()
async def build_portfolio(symbols: list, returns_panel: list, method: str = "hrp",
                          scores: list = None) -> dict:
    """[offline] 组合构建(HRP默认/ERC/MVO收窄池)。"""
    return {**await _offload(portfolio_lib.build_portfolio, symbols, scores, returns_panel, method),
            "execution_mode": "offline"}


@mcp.tool()
async def risk_attribution(weights: list, exposures: list, factor_cov: list,
                           specific_var: list) -> dict:
    """[offline] Barra Σ=BFB'+D 风险归因(系统/特质)。"""
    return {**await _offload(risk_model_lib.risk_attribution, weights, exposures, factor_cov, specific_var),
            "execution_mode": "offline"}


@mcp.tool()
async def evaluate_factor(factor_values: list, forward_returns: list, library_matrix: list = None) -> dict:
    """[offline] AlphaEval 五维无回测初筛(PPS/PFS/多样性熵 + 硬闸门); LLM 候选因子先过此关。"""
    return {**await _offload(alpha_eval_lib.evaluate, factor_values, forward_returns, library_matrix),
            "execution_mode": "offline"}


@mcp.tool()
async def efficient_frontier(mu: list, cov: list, n_points: int = 10, w_max: float = 0.04) -> dict:
    """[offline] research-only 有效前沿(γ网格 long-only MVO; 误差最大化器, 强制并列1/N, 不可实盘)。"""
    return {**await _offload(portfolio_lib.efficient_frontier, mu, cov, n_points, w_max),
            "execution_mode": "offline"}


@mcp.tool()
async def shrink_cov_report(returns: list, cond_threshold: float = 1e4) -> dict:
    """[offline] 收缩协方差诊断(δ/条件数/可靠性标记, 供治理 R11 判估计可靠性)。"""
    return {**await _offload(portfolio_lib.shrink_cov_report, returns, cond_threshold),
            "execution_mode": "offline"}


@mcp.tool()
async def altfactor(name: str, series: list = None, actual: float = None, expected: float = None,
                    std_hist: float = None, pledge_ratio: float = None,
                    days_to_release: int = None, release_ratio: float = None) -> dict:
    """[realtime] 另类/风险闸因子计算(PEAD-SUE/EPS修正/Chip户数/北向/质押·解禁); 不足→弃权。"""
    af = altfactors_lib
    direction = af.FACTOR_DIRECTIONS.get(name, "+")
    if name == "pead_sue":
        val = af.pead_sue(actual, expected, std_hist)
    elif name == "eps_revision":
        val = af.eps_revision(series or [])
    elif name == "chip_factor":
        val = af.chip_factor(series or [])
    elif name == "northbound_flow":
        val = af.northbound_flow(series or [])
    elif name == "pledge_risk_gate":
        return {**af.pledge_risk_gate(pledge_ratio), "name": name, "execution_mode": "realtime"}
    elif name == "restricted_release_gate":
        return {**af.restricted_release_gate(days_to_release, release_ratio), "name": name,
                "execution_mode": "realtime"}
    else:
        return {"error": f"unknown altfactor {name}", "execution_mode": "realtime"}
    return {"name": name, "value": val, "direction": direction,
            "abstain": val is None, "execution_mode": "realtime"}


@mcp.tool()
async def industry_dummies(symbols: list, sym2ind: dict) -> dict:
    """[realtime] 申万一级行业哑变量矩阵(中性化前置; today_snapshot_only PIT, 带 coverage/caveat)。"""
    matrix, order, meta = industry_map_lib.build_industry_dummies(symbols, sym2ind, with_meta=True)
    return {"matrix": matrix, "industry_order": order, **meta, "execution_mode": "realtime"}


if __name__ == "__main__":
    transport = os.getenv("MCP_TRANSPORT", "stdio")
    if transport == "sse":
        print(f"启动 MCP 服务器 (SSE) on {HOST}:{PORT} ...")
        mcp.run(transport="sse")
    else:
        print("启动 MCP 服务器 (stdio) ...")
        mcp.run(transport="stdio")
