"""scheduler: 周期性行情采集 + 研判复盘 + 异动告警。

使用 APScheduler 的 AsyncIOScheduler，三个 job 全部走 httpx 异步调用
storage-service（http://storage-service:8003）。所有网络调用都包了
try/except —— 单点失败只计数，绝不让 job 抛异常拖垮调度器。
"""
import os
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler

import datafetch

STORAGE_URL = os.getenv("STORAGE_URL", "http://storage-service:8003").rstrip("/")

QUOTE_INTERVAL_SEC = int(os.getenv("QUOTE_INTERVAL_SEC", "300"))
REVIEW_INTERVAL_SEC = int(os.getenv("REVIEW_INTERVAL_SEC", "3600"))
ALERT_INTERVAL_SEC = int(os.getenv("ALERT_INTERVAL_SEC", "600"))
ALERT_CHANGE_PCT = float(os.getenv("ALERT_CHANGE_PCT", "5.0"))

# (symbol, 交易日) 去重集合，避免同一标的当日重复告警造成"告警风暴"
_alerted_today: set = set()

# watchlist 为空时的兜底标的。
DEFAULT_WATCHLIST = [
    {"symbol": "ASHARE:600519", "market": "ASHARE"},
    {"symbol": "ASHARE:000001", "market": "ASHARE"},
]

_SHANGHAI = ZoneInfo("Asia/Shanghai")
_HTTP_TIMEOUT = httpx.Timeout(10.0, connect=5.0)

# ---------------------------------------------------------------- counters
quotes_collected = 0
alerts_raised = 0
review_filled = 0
failures = 0
last_run_ts = ""  # 字符串；用 time.time() 生成，避免 datetime.now() 序列化坑

_scheduler: AsyncIOScheduler | None = None


def get_status() -> dict:
    """供 /status 暴露的轻量运行态快照。"""
    return {
        "quotes_collected": quotes_collected,
        "alerts_raised": alerts_raised,
        "review_filled": review_filled,
        "failures": failures,
        "last_run_ts": last_run_ts,
        "running": _scheduler.running if _scheduler else False,
        "intervals": {
            "quote_sec": QUOTE_INTERVAL_SEC,
            "review_sec": REVIEW_INTERVAL_SEC,
            "alert_sec": ALERT_INTERVAL_SEC,
        },
    }


def _touch():
    """记录最近一次 job 触发时间（字符串，基于 time.time()）。"""
    global last_run_ts
    last_run_ts = str(time.time())


def is_a_share_trading(now: datetime | None = None) -> bool:
    """是否处于 A 股交易时段：周一至周五 09:30-11:30 & 13:00-15:00（上海时区）。"""
    now = now or datetime.now(_SHANGHAI)
    if now.weekday() >= 5:  # 5=周六 6=周日
        return False
    t = now.time()
    morning = (t >= datetime(1, 1, 1, 9, 30).time()) and (t <= datetime(1, 1, 1, 11, 30).time())
    afternoon = (t >= datetime(1, 1, 1, 13, 0).time()) and (t <= datetime(1, 1, 1, 15, 0).time())
    return morning or afternoon


async def _get_watchlist(client: httpx.AsyncClient) -> list[dict]:
    """读取 watchlist；为空或失败则回落到 DEFAULT_WATCHLIST。"""
    try:
        resp = await client.get(f"{STORAGE_URL}/watchlist")
        resp.raise_for_status()
        items = resp.json()
        if items:
            return items
    except Exception:  # noqa: BLE001
        global failures
        failures += 1
    return DEFAULT_WATCHLIST


def _is_ashare(item: dict) -> bool:
    sym = (item.get("symbol") or "")
    mkt = (item.get("market") or "")
    return sym.upper().startswith("ASHARE:") or mkt.upper() == "ASHARE"


# ---------------------------------------------------------------- jobs
async def pull_quotes():
    """交易时段内拉取各 A 股标的实时行情并写入 storage。"""
    global quotes_collected, failures
    _touch()
    if not is_a_share_trading():
        return  # 非交易时段不打接口
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        watchlist = await _get_watchlist(client)
        for item in watchlist:
            symbol = item.get("symbol")
            if not symbol or not _is_ashare(item):
                continue
            try:
                quote = await datafetch.fetch_quote(symbol)
                if quote.get("error"):
                    failures += 1
                    continue
                payload = {
                    "symbol": quote["symbol"],
                    "price": quote["price"],
                    "change_pct": quote["change_pct"],
                    "ts": str(quote["ts"]),
                    "data_status": "fresh",
                    "source": quote["source"],
                }
                resp = await client.post(f"{STORAGE_URL}/quotes", json=payload)
                resp.raise_for_status()
                quotes_collected += 1
            except Exception:  # noqa: BLE001 - 单标的失败不影响其它
                failures += 1


async def fill_reviews():
    """对 >=1 天前、尚未回填的研判记录补充实际收益（复盘）。"""
    global review_filled, failures
    _touch()
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        try:
            resp = await client.get(f"{STORAGE_URL}/analysis/pending")
            resp.raise_for_status()
            pending = resp.json()
        except Exception:  # noqa: BLE001
            failures += 1
            return

        cutoff = datetime.now(timezone.utc) - timedelta(days=1)
        for row in pending:
            try:
                created_at = row.get("created_at")
                if not created_at or not _older_than(created_at, cutoff):
                    continue
                symbol = row.get("symbol") or ""
                if not symbol.upper().startswith("ASHARE:"):
                    continue  # 仅 A 股可取现价
                price0 = row.get("price_at_analysis")
                if not price0:
                    continue
                quote = await datafetch.fetch_quote(symbol)
                if quote.get("error"):
                    failures += 1
                    continue
                now_price = quote["price"]
                if not now_price or now_price <= 0:
                    continue  # 无效现价（停牌/竞价）不回填，避免 -100% 脏数据
                ret_1d = (now_price - price0) / price0
                # 按研判方向判定是否兑现（带最小波动阈值，过滤 ret≈0 抖动）；
                # analysis 行带 verdict（pending 用 SELECT *）。ret_3d/5d 暂不写假值。
                verdict = (row.get("verdict") or "").strip()
                thr = 0.005
                if verdict == "偏多":
                    correct = ret_1d > thr
                elif verdict == "偏空":
                    correct = ret_1d < -thr
                else:  # 中性/缺失：以"波动在阈值内"视为兑现
                    correct = abs(ret_1d) <= thr
                rid = row.get("id")
                params = {
                    "ret_1d": ret_1d,
                    "correct": str(correct).lower(),
                }
                r2 = await client.post(f"{STORAGE_URL}/analysis/{rid}/review", params=params)
                r2.raise_for_status()
                review_filled += 1
            except Exception:  # noqa: BLE001 - 单条复盘失败隔离
                failures += 1


async def scan_alerts():
    """扫描 watchlist，单日涨跌幅 >=阈值 则上报 big_move 告警（交易时段 + 按日去重，防告警风暴）。"""
    global alerts_raised, failures
    _touch()
    today = datetime.now(_SHANGHAI).date().isoformat()
    trading = is_a_share_trading()
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        watchlist = await _get_watchlist(client)
        for item in watchlist:
            symbol = item.get("symbol")
            if not symbol:
                continue
            if _is_ashare(item) and not trading:
                continue  # A股非交易时段不告警（避免盘后/周末重复上报）
            key = (symbol, today)
            if key in _alerted_today:
                continue  # 当日已就该标的告警 → 抑制重复
            try:
                quote = await datafetch.fetch_quote(symbol)
                if quote.get("error"):
                    continue  # 未接入市场/无效行情不算失败
                change_pct = quote.get("change_pct", 0.0)
                if abs(change_pct) >= ALERT_CHANGE_PCT:
                    direction = "涨" if change_pct > 0 else "跌"
                    detail = f"{quote.get('name', symbol)} 单日{direction} {change_pct:.2f}% (现价 {quote.get('price')})"
                    params = {"symbol": symbol, "type": "big_move", "detail": detail}
                    resp = await client.post(f"{STORAGE_URL}/alerts", params=params)
                    resp.raise_for_status()
                    _alerted_today.add(key)
                    alerts_raised += 1
            except Exception:  # noqa: BLE001
                failures += 1


def _older_than(created_at: str, cutoff: datetime) -> bool:
    """created_at(ISO 字符串) 是否早于 cutoff（容错解析，失败则视为不满足）。"""
    try:
        dt = datetime.fromisoformat(created_at)
    except (ValueError, TypeError):
        return False
    if dt.tzinfo is None:  # storage 实际带 tz，这里仅作兜底
        dt = dt.replace(tzinfo=timezone.utc)
    return dt <= cutoff


# ---------------------------------------------------------------- lifecycle
def start() -> AsyncIOScheduler:
    """构建并启动调度器（幂等：重复调用只返回已有实例）。"""
    global _scheduler
    if _scheduler and _scheduler.running:
        return _scheduler
    sched = AsyncIOScheduler(timezone="Asia/Shanghai")
    sched.add_job(pull_quotes, "interval", seconds=QUOTE_INTERVAL_SEC,
                  id="pull_quotes", max_instances=1, coalesce=True)
    sched.add_job(fill_reviews, "interval", seconds=REVIEW_INTERVAL_SEC,
                  id="fill_reviews", max_instances=1, coalesce=True)
    sched.add_job(scan_alerts, "interval", seconds=ALERT_INTERVAL_SEC,
                  id="scan_alerts", max_instances=1, coalesce=True)
    sched.start()
    _scheduler = sched
    return sched


def shutdown():
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
    _scheduler = None
