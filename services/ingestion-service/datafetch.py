"""datafetch: 轻量行情抓取层（异步 / httpx）。

本模块**不依赖**其它服务的 Python 代码，直接打公开行情接口。
目前仅 A 股（Sina）真正落地；US: / CRYPTO: 等市场优雅降级返回 error。

符号约定（与 storage-service 的 watchlist 一致）：
    "ASHARE:600519"  -> 上交所贵州茅台
    "ASHARE:000001"  -> 深交所平安银行
    "US:AAPL" / "CRYPTO:BTC" -> 暂未接入
"""
import asyncio
import time

import httpx

# Sina 行情接口需要伪装成浏览器 + 带 Referer，否则返回 403 / 空串。
_SINA_URL = "https://hq.sinajs.cn/list={code}"
_HEADERS = {
    "Referer": "https://finance.sina.com.cn",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
}

_TIMEOUT = httpx.Timeout(8.0, connect=5.0)
_RETRIES = 3


def _sina_code(ashare_code: str) -> str:
    """A 股 6 位代码 -> Sina 代码：6 开头走沪市(sh)，否则深市(sz)。"""
    ashare_code = ashare_code.strip()
    prefix = "sh" if ashare_code.startswith("6") else "sz"
    return prefix + ashare_code


def _parse_sina(text: str, sina_code: str) -> dict:
    """解析 GBK 解码后的形如
    var hq_str_sh600519="贵州茅台,1688.00,1685.50,1700.00,...";
    的响应。字段下标：0=名称 2=昨收 3=现价 8=成交量。
    """
    # 取等号右侧引号内的内容
    start = text.find('"')
    end = text.rfind('"')
    if start == -1 or end == -1 or end <= start:
        raise ValueError(f"unparseable sina payload for {sina_code}: {text!r}")
    fields = text[start + 1:end].split(",")
    if len(fields) < 9 or not fields[0]:
        raise ValueError(f"empty/short sina payload for {sina_code}: {text!r}")
    return {
        "name": fields[0],
        "prev_close": float(fields[2]),
        "price": float(fields[3]),
        "volume": float(fields[8]) if fields[8] else 0.0,
    }


async def _fetch_sina(ashare_code: str) -> dict:
    """带重试地抓取并解析单只 A 股行情。"""
    sina_code = _sina_code(ashare_code)
    url = _SINA_URL.format(code=sina_code)
    last_err: Exception | None = None
    for attempt in range(_RETRIES):
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_HEADERS) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                # Sina 返回 GBK 编码，需显式解码（httpx 默认按 charset/utf-8 会乱码）。
                text = resp.content.decode("gbk", errors="replace")
            return _parse_sina(text, sina_code)
        except Exception as exc:  # noqa: BLE001 - 网络/解析异常统一重试
            last_err = exc
            # 指数式小退避，吸收瞬时断连。
            await asyncio.sleep(0.4 * (attempt + 1))
    raise RuntimeError(f"sina fetch failed for {ashare_code}: {last_err}")


async def fetch_quote(symbol: str) -> dict:
    """抓取单个符号的实时行情。

    成功（仅 ASHARE:）返回：
        {symbol, name, price, prev_close, change_pct, volume, ts, source:"sina"}
    其它市场或抓取失败时优雅返回 {"symbol":symbol, "error": "..."}，绝不抛出。
    """
    if not symbol or ":" not in symbol:
        return {"symbol": symbol, "error": "bad symbol"}

    market, _, code = symbol.partition(":")
    market = market.upper()

    if market != "ASHARE":
        return {"symbol": symbol, "error": "market not ingested"}

    try:
        data = await _fetch_sina(code)
    except Exception as exc:  # noqa: BLE001 - 对外永不抛出
        return {"symbol": symbol, "error": str(exc)}

    prev_close = data["prev_close"]
    price = data["price"]
    # 现价/昨收 <=0 多为停牌或集合竞价前的占位，视为无效行情（避免脏数据入库与 -100% 复盘）
    if price <= 0 or prev_close <= 0:
        return {"symbol": symbol, "error": "invalid price (likely halted/pre-open)"}
    change_pct = (price - prev_close) / prev_close * 100.0
    return {
        "symbol": symbol,
        "name": data["name"],
        "price": price,
        "prev_close": prev_close,
        "change_pct": change_pct,
        "volume": data["volume"],
        "ts": time.time(),
        "source": "sina",
    }
