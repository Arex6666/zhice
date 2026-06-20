"""mcp-tool-service: 智策金融数据工具的 FastMCP 服务器。

双传输 (dual transport):
  MCP_TRANSPORT=stdio  -> 供 `mcp dev` / MCP Inspector / Cline 使用（指导书第三~五步）
  MCP_TRANSPORT=sse    -> 在 :8002 暴露 HTTP/SSE，供 agent-service 跨容器调用（微服务模式）

设计：所有工具均为 async，网络 I/O 用 httpx.AsyncClient，避免阻塞 FastMCP 的事件循环；
行情/新闻抓取与解析封装在 finance.py，纯计算在 indicators.py / backtest.py（均可脱网单元测试）。
工具内部不吞异常——出错时抛出，由 FastMCP 自动置 isError=True，使客户端/智能体能感知失败。
"""
import os
import time

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

_ASHARE_INDEX = "ASHARE:sh000001"  # 上证指数（跨资产 β 默认基准）

METRICS = obs.Metrics()                 # 按数据源 调用/错误/命中/延迟
_QUOTE_CACHE = obs.TTLCache()           # 实时报价短 TTL 缓存（降限流风险）
_QUOTE_TTL = {"ASHARE": 30, "US": 60, "CRYPTO": 15}  # 各市场缓存秒数

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
async def asof_value(symbol: str, field: str, date: str, kind: str = "panel") -> dict:
    """[realtime] 防前视时点取值(visible_date/announce_date<=date 最近)。kind∈{panel,fundamental}。"""
    return await pit_panel.fetch_asof(symbol, field, date, kind)


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
async def data_source_metrics() -> dict:
    """数据源健康：按源的 调用/错误率/缓存命中率/延迟（可观测性 §10）。"""
    return METRICS.snapshot()


@mcp.tool()
async def get_kline(symbol: str, period: str = "daily", count: int = 120, adjust: str = "qfq") -> list:
    """获取 K 线 OHLCV 历史。adjust ∈ {qfq 前复权, hfq 后复权, none}。"""
    market, code = finance.split_symbol(symbol)
    return await finance.get_adapter(market).get_kline(code, period, count, adjust)


@mcp.tool()
async def get_indicators(symbol: str, period: str = "daily") -> dict:
    """计算技术指标 MA/MACD/RSI/BOLL/量能（基于 K 线）。"""
    market, code = finance.split_symbol(symbol)
    kl = await finance.get_adapter(market).get_kline(code, period, 120)
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


if __name__ == "__main__":
    transport = os.getenv("MCP_TRANSPORT", "stdio")
    if transport == "sse":
        print(f"启动 MCP 服务器 (SSE) on {HOST}:{PORT} ...")
        mcp.run(transport="sse")
    else:
        print("启动 MCP 服务器 (stdio) ...")
        mcp.run(transport="stdio")
