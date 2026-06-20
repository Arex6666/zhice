"""datafetch: 轻量行情抓取层（异步 / httpx）。

本模块**不依赖**其它服务的 Python 代码，直接打公开行情接口。
目前仅 A 股（Sina）真正落地；US: / CRYPTO: 等市场优雅降级返回 error。

符号约定（与 storage-service 的 watchlist 一致）：
    "ASHARE:600519"  -> 上交所贵州茅台
    "ASHARE:000001"  -> 深交所平安银行
    "US:AAPL" / "CRYPTO:BTC" -> 暂未接入
"""
import asyncio
import hashlib
import re
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx

# 轻量金融情绪词典（[-1,1]）；ingestion 不依赖 agent-service 的 news_nlp。
_POS = ("利好", "增长", "盈利", "中标", "签约", "回购", "增持", "创新高", "超预期",
        "大涨", "看好", "扭亏", "突破")
_NEG = ("利空", "下滑", "亏损", "减持", "违约", "处罚", "退市", "暴跌", "下跌",
        "低于预期", "风险", "爆雷", "立案")


def lexicon_sentiment(text):
    t = str(text or "")
    pos = sum(t.count(w) for w in _POS)
    neg = sum(t.count(w) for w in _NEG)
    tot = pos + neg
    return round((pos - neg) / tot, 3) if tot else 0.0


def enrich_news(item):
    """为单条新闻附 词典情绪 / 摘要 / 内容 hash（去重用）。"""
    title = str(item.get("title", ""))
    return {**item, "sentiment": str(lexicon_sentiment(title)),
            "summary": title[:80],
            "hash": hashlib.md5(title.encode("utf-8")).hexdigest()[:12]}


def parse_news_json(data, limit=8):
    """防御式解析 eastmoney 新闻搜索 JSON（字段名多变，尽量兼容）。"""
    cand = []
    if isinstance(data, dict):
        d = data.get("data") or data.get("result") or {}
        if isinstance(d, dict):
            cand = d.get("web") or d.get("news") or d.get("list") or []
        elif isinstance(d, list):
            cand = d
    elif isinstance(data, list):
        cand = data
    out = []
    for it in cand[:limit]:
        if not isinstance(it, dict):
            continue
        title = re.sub(r"</?em>", "", str(it.get("title") or it.get("Title") or ""))
        if not title:
            continue
        out.append({"title": title,
                    "url": it.get("url") or it.get("Url") or it.get("link") or "",
                    "ts": str(it.get("date") or it.get("showtime") or it.get("ts") or ""),
                    "source": "eastmoney"})
    return out

_SHANGHAI = ZoneInfo("Asia/Shanghai")
# 各市场新鲜窗（秒），与 mcp-tool-service/data_quality.FRESH 对齐（ingestion 不跨服务 import）。
_FRESH_WINDOW = {"ASHARE": 300, "US": 900, "CRYPTO": 60}


def _sina_ts(date_s, time_s):
    """sina 行情日期/时间(上海时区) -> epoch 秒；缺失/非法返回 None。"""
    try:
        dt = datetime.strptime(f"{date_s} {time_s}", "%Y-%m-%d %H:%M:%S")
        return dt.replace(tzinfo=_SHANGHAI).timestamp()
    except (ValueError, TypeError):
        return None


def freshness(ts, now_ts, market):
    """依据行情真实时间判定 data_status；ts 未知时返回保守的 'delayed'（绝不乐观地报 fresh）。"""
    if not ts:
        return "delayed"
    win = _FRESH_WINDOW.get(market, 600)
    age = now_ts - ts
    if age <= win:
        return "fresh"
    if age <= win * 4:
        return "delayed"
    return "stale"


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
    # 真实成交时间在 下标30(日期)/31(时间)；缺失时回退当前时间。
    date_s = fields[30] if len(fields) > 30 else None
    time_s = fields[31] if len(fields) > 31 else None
    return {
        "name": fields[0],
        "prev_close": float(fields[2]),
        "price": float(fields[3]),
        "volume": float(fields[8]) if fields[8] else 0.0,
        "ts": _sina_ts(date_s, time_s) or time.time(),
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


async def fetch_news(symbol: str, limit: int = 8) -> list:
    """抓取个股相关新闻并轻量富化（best-effort：任何失败返回 []，绝不抛出）。仅 A 股。"""
    if not symbol or ":" not in symbol:
        return []
    market, _, code = symbol.partition(":")
    if market.upper() != "ASHARE":
        return []
    import json
    param = json.dumps({"uid": "", "keyword": code, "type": ["cmsArticleWebOld"],
                        "client": "web", "clientType": "web", "clientVersion": "curr",
                        "param": {"cmsArticleWebOld": {"searchScope": "default", "sort": "default",
                                  "pageIndex": 1, "pageSize": limit,
                                  "preTag": "<em>", "postTag": "</em>"}}}, ensure_ascii=False)
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_HEADERS) as client:
            r = await client.get("https://search-api-web.eastmoney.com/search/jsonp",
                                 params={"cb": "x", "param": param})
            r.raise_for_status()
            txt = r.text
            s, e = txt.find("("), txt.rfind(")")
            data = json.loads(txt[s + 1:e] if 0 <= s < e else txt)
        return [enrich_news(n) for n in parse_news_json(data, limit)]
    except Exception:  # noqa: BLE001 - 新闻为非关键路径，优雅降级
        return []


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
    ts = data.get("ts") or time.time()
    return {
        "symbol": symbol,
        "name": data["name"],
        "price": price,
        "prev_close": prev_close,
        "change_pct": change_pct,
        "volume": data["volume"],
        "ts": ts,
        "data_status": freshness(ts, time.time(), market),
        "source": "sina",
    }
