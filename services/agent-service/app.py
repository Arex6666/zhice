"""agent-service: 金融分析智能体的 HTTP 入口。"""
import logging

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

logger = logging.getLogger("agent-service")
app = FastAPI(title="zhice-agent-service")


@app.get("/health")
def health():
    return {"status": "ok", "service": "agent-service"}


class FinanceIn(BaseModel):
    symbol: str = ""
    mode: str = "deep"


@app.post("/finance/analyze")
async def finance_analyze(body: FinanceIn):
    import finance_agent
    try:
        return await finance_agent.analyze(body.symbol, body.mode)
    except Exception:
        logger.exception("金融分析失败")
        raise HTTPException(status_code=502, detail="金融分析失败，请稍后重试")


@app.get("/finance/review")
async def finance_review():
    import finance_agent
    return await finance_agent.analyze("", "review")


@app.get("/finance/quote")
async def finance_quote(symbol: str):
    import finance_agent
    return await finance_agent.mcp_tool("get_quote", {"symbol": symbol})


@app.get("/finance/kline")
async def finance_kline(symbol: str, period: str = "daily", count: int = 120):
    import finance_agent
    return await finance_agent.mcp_tool("get_kline", {"symbol": symbol, "period": period, "count": count})


@app.get("/finance/intraday")
async def finance_intraday(symbol: str):
    """当日分时（盘中走势）：每分钟 价/均价/量 + 昨收基准。"""
    import finance_agent
    return await finance_agent.mcp_tool("get_intraday", {"symbol": symbol})


@app.get("/finance/indicators")
async def finance_indicators(symbol: str):
    import finance_agent
    return await finance_agent.mcp_tool("get_indicators", {"symbol": symbol})


@app.get("/finance/news")
async def finance_news(symbol: str, limit: int = 8):
    import finance_agent
    return await finance_agent.mcp_tool("get_stock_news", {"symbol": symbol, "limit": limit})


@app.get("/finance/board")
async def finance_board(symbols: str):
    """盯盘墙批量行情：一次 MCP 会话 → 单次 sina 批量调用，返回多标的报价数组。"""
    import finance_agent
    syms = [s.strip() for s in symbols.split(",") if s.strip()]
    return await finance_agent.mcp_tool("get_quotes_batch", {"symbols": syms})


@app.get("/status")
def status():
    return {"service": "agent-service", "status": "ok"}
