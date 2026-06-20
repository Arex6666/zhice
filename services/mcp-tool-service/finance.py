"""市场无关数据适配器（I/O）。

符号格式 MARKET:CODE。解析类函数（parse_sina_quote）为纯函数、可脱网单测；
真正的网络调用在各 Adapter 内，失败时抛出（由 MCP 工具置 isError）。
同步库（akshare/yfinance）通过 anyio.to_thread 卸载，避免阻塞事件循环。
"""
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import anyio
import httpx

SINA_HEADERS = {"Referer": "https://finance.sina.com.cn", "User-Agent": "Mozilla/5.0"}
UA = {"User-Agent": "Mozilla/5.0"}
_SHANGHAI = ZoneInfo("Asia/Shanghai")


def _sina_ts(date_s, time_s):
    """把 sina 行情里的日期/时间(上海时区)解析为 epoch 秒；缺失/非法返回 None。"""
    try:
        dt = datetime.strptime(f"{date_s} {time_s}", "%Y-%m-%d %H:%M:%S")
        return dt.replace(tzinfo=_SHANGHAI).timestamp()
    except (ValueError, TypeError):
        return None


async def aget(client, url, retries=3, **kw):
    """带重试的 GET：仅对瞬时错误(连接/超时/5xx)重试；4xx 立即失败（不浪费重试）。"""
    last = None
    for i in range(retries):
        try:
            r = await client.get(url, **kw)
            r.raise_for_status()
            return r
        except httpx.HTTPStatusError as e:
            if e.response.status_code < 500:
                raise  # 4xx（如 Binance 451）快速失败，便于尽快回退
            last = e
            await anyio.sleep(0.4 * (i + 1))
        except (httpx.TransportError, httpx.TimeoutException) as e:
            last = e
            await anyio.sleep(0.4 * (i + 1))
    raise last


# ----------------------------------------------------------------- pure parser
def parse_sina_quote(text):
    """解析新浪行情行 var hq_str_xxx="名称,今开,昨收,现价,最高,最低,...";"""
    body = text.split('="', 1)[1].rstrip('";\n') if '="' in text else ""
    f = body.split(",")

    def num(i):
        try:
            return float(f[i])
        except (IndexError, ValueError):
            return None

    # 真实成交时间在 下标30(日期)/31(时间)；缺失时回退当前时间（精简载荷/异常）。
    date_s = f[30] if len(f) > 30 else None
    time_s = f[31] if len(f) > 31 else None
    ts = _sina_ts(date_s, time_s) or time.time()
    return {"name": f[0] if f else "", "open": num(1), "prev_close": num(2),
            "price": num(3), "high": num(4), "low": num(5),
            "volume": num(8), "ts": ts, "source": "sina"}


def _em_kline_rows(klines, adjust):
    """东方财富 K 线行 -> 标准 OHLCV dict，并标注实际复权口径 adjust_actual。"""
    out = []
    for s in klines:  # 日期,开,收,高,低,成交量,...
        p = s.split(",")
        out.append({"ts": p[0], "open": float(p[1]), "close": float(p[2]),
                    "high": float(p[3]), "low": float(p[4]), "volume": float(p[5]),
                    "adjust_actual": adjust})
    return out


def _sina_kline_rows(data):
    """新浪 K 线 -> 标准 OHLCV dict；新浪为**不复权**数据，标注 adjust_actual='none'。"""
    return [{"ts": d["day"], "open": float(d["open"]), "high": float(d["high"]),
             "low": float(d["low"]), "close": float(d["close"]),
             "volume": float(d["volume"]), "adjust_actual": "none"} for d in data]


def _ashare_sina_code(code):
    return ("sh" if code[0] == "6" else "sz") + code


# ----------------------------------------------------------------- adapters
class MarketAdapter:
    async def get_quote(self, code):
        raise NotImplementedError

    async def get_kline(self, code, period="daily", count=120, adjust="qfq"):
        raise NotImplementedError

    async def get_news(self, code, limit=8):
        raise NotImplementedError


class AshareAdapter(MarketAdapter):
    async def get_quote(self, code):
        url = f"https://hq.sinajs.cn/list={_ashare_sina_code(code)}"
        async with httpx.AsyncClient(timeout=10, headers=SINA_HEADERS) as c:
            r = await aget(c, url)
            r.encoding = "gbk"
            return parse_sina_quote(r.text)

    async def get_kline(self, code, period="daily", count=120, adjust="qfq"):
        # 主源：东方财富 push2his JSON；失败回退 新浪 K 线 JSON（多源容错）
        # 注意：新浪回退为不复权数据；当请求复权(qfq/hfq)时回退会改变口径（已知降级）。
        try:
            return await self._kline_eastmoney(code, period, count, adjust)
        except (httpx.HTTPError, ValueError, KeyError, IndexError):
            return await self._kline_sina(code, count)

    async def _kline_eastmoney(self, code, period, count, adjust):
        secid = f"{'1' if code[0] == '6' else '0'}.{code}"
        klt = {"daily": 101, "weekly": 102, "monthly": 103, "60min": 60}.get(period, 101)
        fqt = {"qfq": 1, "hfq": 2, "none": 0}.get(adjust, 1)
        params = {"secid": secid, "klt": klt, "fqt": fqt, "lmt": count, "end": "20500101",
                  "fields1": "f1,f2,f3,f4,f5,f6",
                  "fields2": "f51,f52,f53,f54,f55,f56,f57,f58"}
        async with httpx.AsyncClient(timeout=12, headers=UA) as c:
            r = await aget(c, "https://push2his.eastmoney.com/api/qt/stock/kline/get", params=params)
            klines = (r.json().get("data") or {}).get("klines") or []
        out = _em_kline_rows(klines, adjust)
        if not out:
            raise ValueError("eastmoney empty")
        return out

    async def _kline_sina(self, code, count):
        sym = _ashare_sina_code(code)
        url = ("https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
               f"CN_MarketData.getKLineData?symbol={sym}&scale=240&datalen={count}")
        async with httpx.AsyncClient(timeout=12, headers=SINA_HEADERS) as c:
            r = await aget(c, url)
            data = r.json()
        return _sina_kline_rows(data)

    async def get_news(self, code, limit=8):
        # 新闻非关键路径：akshare 失败时优雅返回空（委员会会据此弃权情绪票）
        try:
            import akshare as ak

            def _f():
                df = ak.stock_news_em(symbol=code).head(limit)
                return [{"title": row.get("新闻标题", ""), "url": row.get("新闻链接", ""),
                         "ts": str(row.get("发布时间", "")), "source": "eastmoney"}
                        for _, row in df.iterrows()]

            return await anyio.to_thread.run_sync(_f)
        except Exception:
            return []


class UsAdapter(MarketAdapter):
    async def get_quote(self, code):
        import yfinance as yf

        def _f():
            t = yf.Ticker(code)
            fi = t.fast_info
            price = float(fi.get("last_price")) if fi.get("last_price") else None
            prev = float(fi.get("previous_close")) if fi.get("previous_close") else None
            return {"name": code, "price": price, "prev_close": prev,
                    "volume": fi.get("last_volume"), "ts": time.time(), "source": "yfinance"}

        return await anyio.to_thread.run_sync(_f)

    async def get_kline(self, code, period="daily", count=120, adjust="qfq"):
        import yfinance as yf

        def _f():
            df = yf.Ticker(code).history(period="1y").tail(count)
            return [{"ts": str(idx.date()), "open": float(r["Open"]), "high": float(r["High"]),
                     "low": float(r["Low"]), "close": float(r["Close"]),
                     "volume": float(r["Volume"])} for idx, r in df.iterrows()]

        return await anyio.to_thread.run_sync(_f)

    async def get_news(self, code, limit=8):
        import yfinance as yf

        def _f():
            items = getattr(yf.Ticker(code), "news", []) or []
            out = []
            for n in items[:limit]:
                out.append({"title": n.get("title", ""), "url": n.get("link", ""),
                            "ts": str(n.get("providerPublishTime", "")), "source": "yahoo"})
            return out

        return await anyio.to_thread.run_sync(_f)


class CryptoAdapter(MarketAdapter):
    @staticmethod
    def _cg_id(code):
        cg = code.replace("USDT", "").replace("USD", "").lower()
        return {"btc": "bitcoin", "eth": "ethereum", "bnb": "binancecoin",
                "sol": "solana", "xrp": "ripple", "doge": "dogecoin"}.get(cg, cg)

    async def get_quote(self, code):
        # Binance 优先（CN 常被 451 封禁），失败回退 CoinGecko
        try:
            async with httpx.AsyncClient(timeout=10, headers=UA) as c:
                r = await aget(c, "https://api.binance.com/api/v3/ticker/24hr",
                               params={"symbol": code})
                d = r.json()
                return {"name": code, "price": float(d["lastPrice"]),
                        "prev_close": float(d["prevClosePrice"]), "volume": float(d["volume"]),
                        "ts": time.time(), "source": "binance"}
        except Exception:
            ids = self._cg_id(code)
            async with httpx.AsyncClient(timeout=10, headers=UA) as c:
                r = await aget(c, "https://api.coingecko.com/api/v3/coins/markets",
                               params={"vs_currency": "usd", "ids": ids})
                arr = r.json()
                if not isinstance(arr, list) or not arr:
                    raise ValueError(f"coingecko 未收录该符号：{code}")
                d = arr[0]
                price = float(d["current_price"])
                prev = price - float(d.get("price_change_24h") or 0)
                return {"name": code, "price": price, "prev_close": prev,
                        "volume": d.get("total_volume"), "ts": time.time(),
                        "source": "coingecko-fallback"}

    async def get_kline(self, code, period="daily", count=120, adjust="qfq"):
        try:
            interval = {"daily": "1d", "weekly": "1w", "60min": "1h"}.get(period, "1d")
            async with httpx.AsyncClient(timeout=10, headers=UA) as c:
                r = await aget(c, "https://api.binance.com/api/v3/klines",
                               params={"symbol": code, "interval": interval, "limit": count})
                return [{"ts": str(k[0]), "open": float(k[1]), "high": float(k[2]),
                         "low": float(k[3]), "close": float(k[4]), "volume": float(k[5])}
                        for k in r.json()]
        except Exception:
            # CoinGecko OHLC 回退（无成交量；days 仅接受固定档位）
            ids = self._cg_id(code)
            allowed = [1, 7, 14, 30, 90, 180, 365]
            days = next((d for d in allowed if d >= min(count, 365)), 365)
            async with httpx.AsyncClient(timeout=12, headers=UA) as c:
                r = await aget(c, f"https://api.coingecko.com/api/v3/coins/{ids}/ohlc",
                               params={"vs_currency": "usd", "days": days})
                data = r.json()
                if not isinstance(data, list) or not data:
                    raise ValueError(f"coingecko OHLC 无数据：{code}")
                rows = data[-count:]
                return [{"ts": str(k[0]), "open": float(k[1]), "high": float(k[2]),
                         "low": float(k[3]), "close": float(k[4]), "volume": 0.0}
                        for k in rows]

    async def get_news(self, code, limit=8):
        return []  # 加密货币新闻源不稳，MVP 暂返回空（仪表盘提示）


_ADAPTERS = {"ASHARE": AshareAdapter, "US": UsAdapter, "CRYPTO": CryptoAdapter}


async def ashare_eastmoney_price(code):
    """A股第二数据源（东方财富 push2），用于跨源价差校验；失败返回 None（best-effort）。"""
    secid = f"{'1' if code[0] == '6' else '0'}.{code}"
    try:
        async with httpx.AsyncClient(timeout=8, headers=UA) as c:
            r = await aget(c, "https://push2.eastmoney.com/api/qt/stock/get",
                           params={"secid": secid, "fields": "f43"})
            f43 = (r.json().get("data") or {}).get("f43")
            return float(f43) / 100 if f43 not in (None, "-") else None
    except Exception:
        return None


def get_adapter(market):
    cls = _ADAPTERS.get(market)
    if not cls:
        raise ValueError(f"未知市场：{market}")
    return cls()


def split_symbol(symbol):
    """'ASHARE:600519' -> ('ASHARE','600519')"""
    market, _, code = symbol.partition(":")
    return market, code
