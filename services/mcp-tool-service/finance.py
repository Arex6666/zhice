"""市场无关数据适配器（I/O）。

符号格式 MARKET:CODE。解析类函数（parse_sina_quote）为纯函数、可脱网单测；
真正的网络调用在各 Adapter 内，失败时抛出（由 MCP 工具置 isError）。
同步库（akshare/yfinance）通过 anyio.to_thread 卸载，避免阻塞事件循环。
"""
import time

import anyio
import httpx

SINA_HEADERS = {"Referer": "https://finance.sina.com.cn", "User-Agent": "Mozilla/5.0"}
UA = {"User-Agent": "Mozilla/5.0"}


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

    return {"name": f[0] if f else "", "open": num(1), "prev_close": num(2),
            "price": num(3), "high": num(4), "low": num(5),
            "volume": num(8), "ts": time.time(), "source": "sina"}


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
            r = await c.get(url)
            r.encoding = "gbk"
            r.raise_for_status()
            return parse_sina_quote(r.text)

    async def get_kline(self, code, period="daily", count=120, adjust="qfq"):
        # 直连东方财富 push2his JSON（比 akshare 抓取更稳、async 原生）
        secid = f"{'1' if code[0] == '6' else '0'}.{code}"
        klt = {"daily": 101, "weekly": 102, "monthly": 103, "60min": 60}.get(period, 101)
        fqt = {"qfq": 1, "hfq": 2, "none": 0}.get(adjust, 1)
        params = {"secid": secid, "klt": klt, "fqt": fqt, "lmt": count, "end": "20500101",
                  "fields1": "f1,f2,f3,f4,f5,f6",
                  "fields2": "f51,f52,f53,f54,f55,f56,f57,f58"}
        async with httpx.AsyncClient(timeout=12, headers=UA) as c:
            r = await c.get("https://push2his.eastmoney.com/api/qt/stock/kline/get", params=params)
            r.raise_for_status()
            klines = (r.json().get("data") or {}).get("klines") or []
        out = []
        for s in klines:  # 日期,开,收,高,低,成交量,...
            p = s.split(",")
            out.append({"ts": p[0], "open": float(p[1]), "close": float(p[2]),
                        "high": float(p[3]), "low": float(p[4]), "volume": float(p[5])})
        return out

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
                r = await c.get("https://api.binance.com/api/v3/ticker/24hr",
                                params={"symbol": code})
                r.raise_for_status()
                d = r.json()
                return {"name": code, "price": float(d["lastPrice"]),
                        "prev_close": float(d["prevClosePrice"]), "volume": float(d["volume"]),
                        "ts": time.time(), "source": "binance"}
        except Exception:
            ids = self._cg_id(code)
            async with httpx.AsyncClient(timeout=10, headers=UA) as c:
                r = await c.get("https://api.coingecko.com/api/v3/coins/markets",
                                params={"vs_currency": "usd", "ids": ids})
                r.raise_for_status()
                d = r.json()[0]
                price = float(d["current_price"])
                prev = price - float(d.get("price_change_24h") or 0)
                return {"name": code, "price": price, "prev_close": prev,
                        "volume": d.get("total_volume"), "ts": time.time(),
                        "source": "coingecko-fallback"}

    async def get_kline(self, code, period="daily", count=120, adjust="qfq"):
        try:
            interval = {"daily": "1d", "weekly": "1w", "60min": "1h"}.get(period, "1d")
            async with httpx.AsyncClient(timeout=10, headers=UA) as c:
                r = await c.get("https://api.binance.com/api/v3/klines",
                                params={"symbol": code, "interval": interval, "limit": count})
                r.raise_for_status()
                return [{"ts": str(k[0]), "open": float(k[1]), "high": float(k[2]),
                         "low": float(k[3]), "close": float(k[4]), "volume": float(k[5])}
                        for k in r.json()]
        except Exception:
            # CoinGecko OHLC 回退（无成交量；days 仅接受固定档位）
            ids = self._cg_id(code)
            allowed = [1, 7, 14, 30, 90, 180, 365]
            days = next((d for d in allowed if d >= min(count, 365)), 365)
            async with httpx.AsyncClient(timeout=12, headers=UA) as c:
                r = await c.get(f"https://api.coingecko.com/api/v3/coins/{ids}/ohlc",
                                params={"vs_currency": "usd", "days": days})
                r.raise_for_status()
                rows = r.json()[-count:]
                return [{"ts": str(k[0]), "open": float(k[1]), "high": float(k[2]),
                         "low": float(k[3]), "close": float(k[4]), "volume": 0.0}
                        for k in rows]

    async def get_news(self, code, limit=8):
        return []  # 加密货币新闻源不稳，MVP 暂返回空（仪表盘提示）


_ADAPTERS = {"ASHARE": AshareAdapter, "US": UsAdapter, "CRYPTO": CryptoAdapter}


def get_adapter(market):
    cls = _ADAPTERS.get(market)
    if not cls:
        raise ValueError(f"未知市场：{market}")
    return cls()


def split_symbol(symbol):
    """'ASHARE:600519' -> ('ASHARE','600519')"""
    market, _, code = symbol.partition(":")
    return market, code
