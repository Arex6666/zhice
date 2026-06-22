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


def _is_sina_index(sina_code):
    """指数代码：sh000xxx（上证综指/沪深300/中证500/科创50…）或 sz399xxx（深成指/创业板指）。

    实测：sina 指数行与个股**同字段布局**（名称,今开,昨收,现价,…,日期,时间），故同用 parse_sina_quote，
    仅打 is_index 标记供前端区分（脉搏条 vs 个股墙）。
    """
    return sina_code.startswith("sh000") or sina_code.startswith("sz399")


def parse_sina_multi(text):
    """解析一次 sina list= 调用返回的**多标的**行情（个股 + 指数混合，同字段布局）。

    返回 {sina_code: quote}（sina_code 形如 sh600519/sz000858/sh000001）；指数额外带 is_index=True。
    无法解析的行（空行/垃圾）跳过。
    """
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("var hq_str_") or '="' not in line:
            continue
        sina_code = line[len("var hq_str_"):].split("=", 1)[0].strip()
        if not sina_code:
            continue
        try:
            q = parse_sina_quote(line)
        except (IndexError, ValueError):
            continue
        if _is_sina_index(sina_code):
            q["is_index"] = True
        out[sina_code] = q
    return out


def parse_sina_hk(text):
    """解析新浪港股行：英文名,中文名,今开,昨收,最高,最低,现价,涨跌额,涨跌幅,...,日期,时间(实测 19 字段)。"""
    body = text.split('="', 1)[1].rstrip('";\n') if '="' in text else ""
    f = body.split(",")

    def num(i):
        try:
            return float(f[i])
        except (IndexError, ValueError):
            return None

    # 日期 f[17]=YYYY/MM/DD, 时间 f[18]=HH:MM → 真实成交时间(港股源常延迟, 据此诚实判新鲜度)
    ts = time.time()
    if len(f) > 18 and f[17] and f[18]:
        cand = _sina_ts(f[17].replace("/", "-"), f[18] if f[18].count(":") == 2 else f[18] + ":00")
        if cand:
            ts = cand
    return {"name": f[1] if len(f) > 1 else "", "open": num(2), "prev_close": num(3),
            "high": num(4), "low": num(5), "price": num(6), "volume": num(12),
            "ts": ts, "source": "sina"}


def parse_sina_hk_multi(text):
    """一次 sina list=hk... 批量返回 → {sina_code: quote}（sina_code 形如 hk00700）。"""
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("var hq_str_") or '="' not in line:
            continue
        sina_code = line[len("var hq_str_"):].split("=", 1)[0].strip()
        if not sina_code:
            continue
        try:
            out[sina_code] = parse_sina_hk(line)
        except (IndexError, ValueError):
            continue
    return out


def _hk_sina_code(code):
    return code if code.startswith("hk") else "hk" + code


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


_TENCENT_PERIOD = {"daily": "day", "weekly": "week", "monthly": "month", "60min": "m60"}


def parse_tencent_hk_kline(payload, code, period="daily"):
    """腾讯(ifzq.gtimg.cn) 港股 K 线 -> 标准 OHLCV。东财港股源被限流时的主源。

    实测行布局: [日期, 开, **收**, 高, 低, 量, {除权信息}, 换手, 成交额, ...]
    （注意字段序与东财不同：第 2 列是 *收盘* 不是成交量）。复权键名随口径变化：
    股票前复权→'qfqday'/'qfqweek'…；指数(不复权)→'day'。据命中键如实标 adjust_actual。
    无数据/异常 → 返回 [] 让图表优雅降级，绝不抛错。
    """
    sym = code if str(code).startswith("hk") else "hk" + str(code)
    node = (payload.get("data") or {}).get(sym) or {}
    p = _TENCENT_PERIOD.get(period, "day")
    rows, key_used = None, None
    for k in ("qfq" + p, p):                       # 先试前复权键, 再试不复权键
        v = node.get(k)
        if isinstance(v, list) and v:
            rows, key_used = v, k
            break
    if rows is None:                               # 兜底：取节点里第一个二维数组(键名异变时)
        for k, v in node.items():
            if isinstance(v, list) and v and isinstance(v[0], list):
                rows, key_used = v, k
                break
    adj = "qfq" if (key_used or "").startswith("qfq") else "none"
    out = []
    for r in (rows or []):
        try:
            out.append({"ts": r[0], "open": float(r[1]), "close": float(r[2]),
                        "high": float(r[3]), "low": float(r[4]), "volume": float(r[5]),
                        "adjust_actual": adj})
        except (IndexError, ValueError, TypeError):
            continue
    return out


def parse_em_trends(payload):
    """东财 trends2 -> 分时点。每行 '日期 时间,开,收(现价),高,低,量,额,均价'。

    返回 {name, prev_close, trade_date, points:[{t='HH:MM', price, avg, volume}]}。
    空/异常 -> points=[] 且 prev_close=None（图表优雅降级，绝不编造）。
    """
    dt = (payload or {}).get("data") or {}
    pre = dt.get("prePrice")
    if pre is None:
        pre = dt.get("preClose")
    points, trade_date = [], None
    for line in dt.get("trends") or []:
        f = str(line).split(",")
        if len(f) < 8:
            continue
        stamp = f[0].split(" ")
        if trade_date is None and len(stamp) == 2:
            trade_date = stamp[0]
        try:
            points.append({"t": stamp[-1][:5], "price": float(f[2]),
                           "avg": float(f[7]), "volume": float(f[5])})
        except (ValueError, IndexError):
            continue
    return {"name": dt.get("name", ""), "prev_close": (float(pre) if pre is not None else None),
            "trade_date": trade_date, "points": points}


def parse_tencent_minute(payload, code):
    """腾讯 minute/query -> 分时点。qt[4]=昨收；data.data 每行 'HHMM 价 累计量 累计额'。

    均价取 VWAP=累计额/累计量；每分钟量取累计差。统一产出契约同 parse_em_trends。
    """
    sym = code if str(code).startswith("hk") else "hk" + str(code)
    node = ((payload or {}).get("data") or {}).get(sym) or {}
    qt = (node.get("qt") or {}).get(sym) or []
    prev_close = None
    name = ""
    if len(qt) > 4:
        try:
            prev_close = float(qt[4])
        except (ValueError, TypeError):
            prev_close = None
        name = qt[1] if len(qt) > 1 else ""
    m = node.get("data") or {}
    raw_date = str(m.get("date") or "")
    trade_date = (f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:8]}" if len(raw_date) == 8 else None)
    points, prev_cum = [], 0.0
    for line in m.get("data") or []:
        g = str(line).split()
        if len(g) < 4:
            continue
        try:
            hhmm, price, cum_vol, cum_amt = g[0], float(g[1]), float(g[2]), float(g[3])
        except (ValueError, IndexError):
            continue
        vol = cum_vol - prev_cum            # 累计量 → 每分钟量
        prev_cum = cum_vol
        avg = (cum_amt / cum_vol) if cum_vol else price   # VWAP 均价线
        t = f"{hhmm[:2]}:{hhmm[2:4]}" if len(hhmm) >= 4 else hhmm
        points.append({"t": t, "price": price, "avg": round(avg, 3), "volume": vol})
    return {"name": name, "prev_close": prev_close, "trade_date": trade_date, "points": points}


def _ashare_sina_code(code):
    return ("sh" if code[0] == "6" else "sz") + code


def _sina_code_any(code):
    """个股 6 位代码 → 加 sh/sz 前缀；已带前缀（指数如 sh000001）原样返回。"""
    return code if code[:2] in ("sh", "sz") else _ashare_sina_code(code)


# ----------------------------------------------------------------- adapters
class MarketAdapter:
    async def get_quote(self, code):
        raise NotImplementedError

    async def get_kline(self, code, period="daily", count=120, adjust="qfq"):
        raise NotImplementedError

    async def get_news(self, code, limit=8):
        raise NotImplementedError

    async def get_intraday(self, code):
        # 默认：不支持分时的市场(US/Crypto)优雅返空, 前端提示"暂无分时", 绝不编造
        return {"name": "", "prev_close": None, "trade_date": None, "points": []}


class AshareAdapter(MarketAdapter):
    async def get_quote(self, code):
        url = f"https://hq.sinajs.cn/list={_ashare_sina_code(code)}"
        async with httpx.AsyncClient(timeout=10, headers=SINA_HEADERS) as c:
            r = await aget(c, url)
            r.encoding = "gbk"
            return parse_sina_quote(r.text)

    async def get_quotes_batch(self, codes):
        """一次 sina list= 调用拿多标的（个股+指数）。返回 {输入code: quote}；缺失项省略。"""
        if not codes:
            return {}
        sina_codes = [_sina_code_any(c) for c in codes]
        url = "https://hq.sinajs.cn/list=" + ",".join(sina_codes)
        async with httpx.AsyncClient(timeout=12, headers=SINA_HEADERS) as c:
            r = await aget(c, url)
            r.encoding = "gbk"
            parsed = parse_sina_multi(r.text)
        return {c: parsed[sc] for c, sc in zip(codes, sina_codes) if sc in parsed}

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

    async def get_intraday(self, code):
        # A股分时走东财 trends2（每分钟 价/均价/量 + prePrice 昨收）；失败优雅返空
        if code[:2] in ("sh", "sz"):
            secid = ("1." if code[:2] == "sh" else "0.") + code[2:]   # 指数(sh000001…)
        else:
            secid = f"{'1' if code[0] == '6' else '0'}.{code}"
        params = {"secid": secid, "iscr": 0, "ndays": 1,
                  "fields1": "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13",
                  "fields2": "f51,f52,f53,f54,f55,f56,f57,f58"}
        try:
            async with httpx.AsyncClient(timeout=12, headers=UA) as c:
                r = await aget(c, "https://push2his.eastmoney.com/api/qt/stock/trends2/get", params=params)
                return parse_em_trends(r.json())
        except (httpx.HTTPError, ValueError, KeyError, IndexError):
            return {"name": "", "prev_close": None, "trade_date": None, "points": []}

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


class HkAdapter(MarketAdapter):
    """港股适配器：行情走新浪(hk 前缀, 实时但常延迟)，K线走东财 push2his(secid 116.)。"""

    async def get_quote(self, code):
        url = f"https://hq.sinajs.cn/list={_hk_sina_code(code)}"
        async with httpx.AsyncClient(timeout=10, headers=SINA_HEADERS) as c:
            r = await aget(c, url)
            r.encoding = "gbk"
            return parse_sina_hk(r.text)

    async def get_quotes_batch(self, codes):
        if not codes:
            return {}
        sina_codes = [_hk_sina_code(c) for c in codes]
        url = "https://hq.sinajs.cn/list=" + ",".join(sina_codes)
        async with httpx.AsyncClient(timeout=12, headers=SINA_HEADERS) as c:
            r = await aget(c, url)
            r.encoding = "gbk"
            parsed = parse_sina_hk_multi(r.text)
        return {c: parsed[sc] for c, sc in zip(codes, sina_codes) if sc in parsed}

    async def get_kline(self, code, period="daily", count=120, adjust="qfq"):
        # 主源：腾讯 ifzq.gtimg.cn（东财港股 push2his 在本机被限流返空 → 降级为备源）。
        # 双源容错；两源皆失败时优雅返空(图表显示暂无, 绝不崩/绝不编造)。
        try:
            kl = await self._kline_tencent(code, period, count, adjust)
            if kl:
                return kl
        except (httpx.HTTPError, ValueError, KeyError, IndexError):
            pass
        try:
            return await self._kline_eastmoney(code, period, count, adjust)
        except (httpx.HTTPError, ValueError, KeyError, IndexError):
            return []

    async def _kline_tencent(self, code, period, count, adjust):
        sym = _hk_sina_code(code)                       # hk00700 / hkHSI
        p = _TENCENT_PERIOD.get(period, "day")
        fq = "hfq" if adjust == "hfq" else "qfq"        # 腾讯须带复权位, 否则返回空
        param = f"{sym},{p},,,{count},{fq}"
        async with httpx.AsyncClient(timeout=12, headers=UA) as c:
            r = await aget(c, "https://web.ifzq.gtimg.cn/appstock/app/hkfqkline/get",
                           params={"param": param})
            return parse_tencent_hk_kline(r.json(), code, period)

    async def _kline_eastmoney(self, code, period, count, adjust):
        secid = f"116.{code}"
        klt = {"daily": 101, "weekly": 102, "monthly": 103, "60min": 60}.get(period, 101)
        fqt = {"qfq": 1, "hfq": 2, "none": 0}.get(adjust, 1)
        params = {"secid": secid, "klt": klt, "fqt": fqt, "lmt": count, "end": "20500101",
                  "fields1": "f1,f2,f3,f4,f5,f6",
                  "fields2": "f51,f52,f53,f54,f55,f56,f57,f58"}
        async with httpx.AsyncClient(timeout=12, headers=UA) as c:
            r = await aget(c, "https://push2his.eastmoney.com/api/qt/stock/kline/get", params=params)
            return _em_kline_rows((r.json().get("data") or {}).get("klines") or [], adjust)

    async def get_intraday(self, code):
        # 港股分时走腾讯 minute（qt[4]昨收 + 每分钟 价/VWAP均价/量）；失败优雅返空
        sym = _hk_sina_code(code)
        try:
            async with httpx.AsyncClient(timeout=12, headers=UA) as c:
                r = await aget(c, "https://web.ifzq.gtimg.cn/appstock/app/minute/query",
                               params={"code": sym})
                return parse_tencent_minute(r.json(), code)
        except (httpx.HTTPError, ValueError, KeyError, IndexError):
            return {"name": "", "prev_close": None, "trade_date": None, "points": []}

    async def get_news(self, code, limit=8):
        return []   # 港股新闻源不稳，MVP 返回空（仪表盘提示），绝不编造


_ADAPTERS = {"ASHARE": AshareAdapter, "US": UsAdapter, "CRYPTO": CryptoAdapter, "HK": HkAdapter}


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
