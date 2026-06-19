"""数据质量层（纯函数）：为每条行情判定 data_status 与停牌/涨跌停标志，并提供跨源价差检测。

data_status ∈ {fresh, delayed, stale, fallback, error}
"""
FRESH = {"ASHARE": 300, "US": 900, "CRYPTO": 60}  # 各市场新鲜窗（秒）


def assess(quote, market, source, now_ts):
    ts = quote.get("ts")
    age = (now_ts - ts) if ts else 1e9
    win = FRESH.get(market, 600)
    if quote.get("price") is None:
        status = "error"
    elif age <= win:
        status = "fresh"
    elif age <= win * 4:
        status = "delayed"
    else:
        status = "stale"
    if str(source).endswith("fallback") and status != "error":
        status = "fallback"
    quote["data_status"] = status
    quote["halted"] = bool(
        market == "ASHARE" and (quote.get("volume") in (0, None)) and status != "error"
    )
    pc = quote.get("prev_close")
    p = quote.get("price")
    quote["limit_up"] = bool(pc and p and (p - pc) / pc >= 0.0995)
    quote["limit_down"] = bool(pc and p and (p - pc) / pc <= -0.0995)
    return quote


def cross_source_check(prices, tol=0.01):
    prices = [p for p in prices if p]
    if len(prices) < 2:
        return False
    return (max(prices) - min(prices)) / min(prices) > tol
