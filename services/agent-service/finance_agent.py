"""金融分析师智能体：编排 6 种任务模式，深度研判走证据链委员会 + 治理引擎。"""
import asyncio
import json
import os

import httpx

import committee
import mcp_client
import modes
import review
from ml_signal import SignalCalibrator, build_features

STORAGE_URL = os.getenv("STORAGE_URL", "http://storage-service:8003")
MODEL_DIR = os.getenv("MODEL_DIR", "/app/models")
DISCLAIMER = committee.DISCLAIMER


def _market(symbol):
    return symbol.split(":", 1)[0]


def _stable(sens):
    vals = [s.get("total_return") for s in sens
            if isinstance(s, dict) and s.get("total_return") is not None]
    if len(vals) < 2:
        return True
    signs = {1 if v >= 0 else -1 for v in vals}
    return len(signs) == 1  # 不同参数收益同号 → 较稳；符号翻转 → 不稳（过拟合嫌疑）


def _backtest_trustworthy(bt):
    """回测可信 = 参数稳健 且 边际统计显著（自助检验）。

    显著性不可判定(样本不足→significant=None)时，仅按稳健性判断，不额外降级。
    """
    if not isinstance(bt, dict):
        return True
    stable = _stable(bt.get("sensitivity", []))
    sig = bt.get("significance")
    if isinstance(sig, dict) and sig.get("significant") is False:
        return False
    return stable


async def _gather(symbol, session):
    async def t(name, args):
        try:
            return await mcp_client.call_tool_data(session, name, args)
        except Exception as e:
            return {"error": str(e)}

    ind = await t("get_indicators", {"symbol": symbol})
    sig = await t("compute_signals", {"symbol": symbol})
    news = await t("get_stock_news", {"symbol": symbol, "limit": 6})
    bt = await t("backtest", {"symbol": symbol})
    mkt = await t("market_overview", {"market": _market(symbol)})
    q = await t("get_quote", {"symbol": symbol})
    data_status = q.get("data_status", "error") if isinstance(q, dict) else "error"
    return {"indicators": ind, "signals": sig, "news": news, "backtest": bt, "market": mkt,
            "quote": q, "data_status": data_status, "backtest_stable": _backtest_trustworthy(bt)}


def _ml_vote(symbol, kline):
    cal = SignalCalibrator.load(os.path.join(MODEL_DIR, f"signal_{_market(symbol)}.pkl"))
    feats = build_features(kline) if isinstance(kline, list) and kline else None
    try:
        return cal.predict(feats)
    except Exception:
        return {"prob_big_move": None, "abstain": True, "abstain_reason": "模型推理失败", "auc": None}


def _llm():
    from openai import AsyncOpenAI
    return (AsyncOpenAI(base_url=os.getenv("LLM_BASE_URL", "https://api.deepseek.com"),
                        api_key=os.getenv("LLM_API_KEY", "")),
            os.getenv("LLM_MODEL", "deepseek-chat"))


async def _storage_get(path, params=None):
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(f"{STORAGE_URL}{path}", params=params or {})
        return r.json()


async def mcp_tool(tool, args):
    """供仪表盘取图表数据：开一个 MCP 会话调用单个金融工具并返回结构化数据。"""
    async with mcp_client.open_session() as session:
        return await mcp_client.call_tool_data(session, tool, args)


async def analyze(symbol, mode="deep"):
    if mode == "teach":
        return {"mode": "teach", "content": modes.TEACH, "disclaimer": DISCLAIMER}
    if mode == "review":
        return {"mode": "review", "review": review.summarize(await _storage_get("/analysis/review")),
                "disclaimer": DISCLAIMER}
    if mode == "alerts":
        return {"mode": "alerts", "alerts": await _storage_get("/alerts", {"limit": 30}),
                "disclaimer": DISCLAIMER}

    async with mcp_client.open_session() as session:
        if mode == "scan":
            wl = await _storage_get("/watchlist")
            syms = [w["symbol"] for w in wl] or [symbol]

            async def quick(s):
                q = await mcp_client.call_tool_data(session, "get_quote", {"symbol": s})
                sig = await mcp_client.call_tool_data(session, "compute_signals", {"symbol": s})
                return {"symbol": s, "quote": q,
                        "signal": sig.get("text") if isinstance(sig, dict) else None}

            return {"mode": "scan", "results": await asyncio.gather(*[quick(s) for s in syms]),
                    "disclaimer": DISCLAIMER}

        if mode == "quick":
            q = await mcp_client.call_tool_data(session, "get_quote", {"symbol": symbol})
            sig = await mcp_client.call_tool_data(session, "compute_signals", {"symbol": symbol})
            news = await mcp_client.call_tool_data(session, "get_stock_news", {"symbol": symbol, "limit": 5})
            return {"mode": "quick", "symbol": symbol, "quote": q, "signals": sig,
                    "news": news, "disclaimer": DISCLAIMER}

        # deep: full evidence-based committee
        data = await _gather(symbol, session)
        kline = await mcp_client.call_tool_data(session, "get_kline", {"symbol": symbol, "count": 120})
        ml = _ml_vote(symbol, kline)
        # 已实现波动区间 → 治理 R8（best-effort：取数失败不影响主流程）
        try:
            vol = await mcp_client.call_tool_data(session, "get_volatility", {"symbol": symbol})
            data["vol_regime"] = vol.get("regime") if isinstance(vol, dict) else None
        except Exception:
            data["vol_regime"] = None
        llm, model = _llm()

        async def gather_fn(_):
            return data

        result = await committee.run_committee(symbol, gather_fn, llm, model, ml=ml)
        result["mode"] = "deep"
        result["ml"] = ml
        result["backtest"] = data.get("backtest")        # 含净值曲线/显著性，供仪表盘
        result["vol_regime"] = data.get("vol_regime")    # 已实现波动区间(R8)
        # 复用本次会话已取的报价/新闻/信号 → 仪表盘无需再单独打 /quote /news（省并发外部调用）
        result["quote"] = data.get("quote")
        result["news"] = data.get("news")
        result["signals"] = data.get("signals")
        # 落库供自审计
        try:
            price = (data.get("quote") or {}).get("price")
            async with httpx.AsyncClient(timeout=20) as c:
                await c.post(f"{STORAGE_URL}/analysis", json={
                    "symbol": symbol, "mode": "deep", "verdict": result["verdict"],
                    "confidence": result["confidence"],
                    "committee_json": json.dumps(result, ensure_ascii=False)[:8000],
                    "price_at_analysis": price})
        except Exception:
            pass
        return result
