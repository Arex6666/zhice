"""ingestion calendar：交易日历纯函数核心 + load_calendar 注入式两路。

参照 tests/test_finance_adapter.py 范式：用 importlib.util.spec_from_file_location 加载被测模块，
核心 5 函数接收已取好的升序交易日字符串列表（脱网可测）；load_calendar 注入假 fetch_fn。
"""
import importlib.util

import pandas as pd


def _cal():
    s = importlib.util.spec_from_file_location(
        "cal", "services/ingestion-service/calendar.py")
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


# 一周交易日(跨周末缺口)：周一~周五, 下周一~周三
DAYS = ["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05",
        "2024-01-08", "2024-01-09", "2024-01-10"]


# ---------------- is_trading_day ----------------
def test_is_trading_day():
    cal = _cal()
    assert cal.is_trading_day("2024-01-03", DAYS) is True
    assert cal.is_trading_day("2024-01-06", DAYS) is False   # 周末非交易日
    assert cal.is_trading_day("2024-01-08", DAYS) is True


def test_is_trading_day_out_of_range():
    cal = _cal()
    assert cal.is_trading_day("2023-12-31", DAYS) is False   # 早于全表
    assert cal.is_trading_day("2024-02-01", DAYS) is False   # 晚于全表


def test_is_trading_day_empty():
    cal = _cal()
    assert cal.is_trading_day("2024-01-03", []) is False


# ---------------- next_trading_day ----------------
def test_next_trading_day():
    cal = _cal()
    assert cal.next_trading_day("2024-01-03", DAYS) == "2024-01-04"
    # 非交易日(周六) → 下一个交易日(下周一)
    assert cal.next_trading_day("2024-01-06", DAYS) == "2024-01-08"
    # 周五 → 跨周末到下周一
    assert cal.next_trading_day("2024-01-05", DAYS) == "2024-01-08"


def test_next_trading_day_boundaries():
    cal = _cal()
    # 早于全表 → 第一个交易日
    assert cal.next_trading_day("2023-12-31", DAYS) == "2024-01-01"
    # 最后一个交易日 → 无后继
    assert cal.next_trading_day("2024-01-10", DAYS) is None
    # 晚于全表 → None
    assert cal.next_trading_day("2024-02-01", DAYS) is None
    assert cal.next_trading_day("2024-01-03", []) is None


# ---------------- prev_trading_day ----------------
def test_prev_trading_day():
    cal = _cal()
    assert cal.prev_trading_day("2024-01-04", DAYS) == "2024-01-03"
    # 非交易日(周六) → 上一个交易日(周五)
    assert cal.prev_trading_day("2024-01-06", DAYS) == "2024-01-05"
    # 下周一 → 跨周末到上周五
    assert cal.prev_trading_day("2024-01-08", DAYS) == "2024-01-05"


def test_prev_trading_day_boundaries():
    cal = _cal()
    # 第一个交易日 → 无前驱
    assert cal.prev_trading_day("2024-01-01", DAYS) is None
    # 早于全表 → None
    assert cal.prev_trading_day("2023-12-31", DAYS) is None
    # 晚于全表 → 最后一个交易日
    assert cal.prev_trading_day("2024-02-01", DAYS) == "2024-01-10"
    assert cal.prev_trading_day("2024-01-03", []) is None


# ---------------- n_trading_days_ago ----------------
def test_n_trading_days_ago():
    cal = _cal()
    assert cal.n_trading_days_ago("2024-01-10", 1, DAYS) == "2024-01-09"
    assert cal.n_trading_days_ago("2024-01-10", 5, DAYS) == "2024-01-03"
    assert cal.n_trading_days_ago("2024-01-10", 0, DAYS) == "2024-01-10"   # n=0 即当日


def test_n_trading_days_ago_from_non_trading_day():
    cal = _cal()
    # 起点为周六(非交易日)：先回到 <= 起点的最近交易日(周五 01-05), 再回退 n
    assert cal.n_trading_days_ago("2024-01-06", 1, DAYS) == "2024-01-04"
    assert cal.n_trading_days_ago("2024-01-06", 0, DAYS) == "2024-01-05"


def test_n_trading_days_ago_boundaries():
    cal = _cal()
    # 回退越界(历史不足) → None, 绝不编造
    assert cal.n_trading_days_ago("2024-01-03", 10, DAYS) is None
    # 起点早于全表 → 无 <=起点的交易日 → None
    assert cal.n_trading_days_ago("2023-12-31", 1, DAYS) is None
    # 起点晚于全表 → 锚到最后交易日再回退
    assert cal.n_trading_days_ago("2024-02-01", 1, DAYS) == "2024-01-09"
    assert cal.n_trading_days_ago("2024-01-10", 1, []) is None
    # 负 n 视作非法 → None
    assert cal.n_trading_days_ago("2024-01-10", -1, DAYS) is None


# ---------------- trading_days_between (闭区间计数) ----------------
def test_trading_days_between():
    cal = _cal()
    # 闭区间 [01-03, 01-08] 含 03,04,05,08 = 4
    assert cal.trading_days_between("2024-01-03", "2024-01-08", DAYS) == 4
    assert cal.trading_days_between("2024-01-03", "2024-01-03", DAYS) == 1   # 同日含自身
    # 全表
    assert cal.trading_days_between("2024-01-01", "2024-01-10", DAYS) == len(DAYS)


def test_trading_days_between_non_trading_endpoints():
    cal = _cal()
    # 端点落非交易日仍按闭区间数区间内交易日：[01-06(六), 01-09] → 08,09 = 2
    assert cal.trading_days_between("2024-01-06", "2024-01-09", DAYS) == 2
    # 区间内无交易日(周末) → 0
    assert cal.trading_days_between("2024-01-06", "2024-01-07", DAYS) == 0


def test_trading_days_between_out_of_range_and_swapped():
    cal = _cal()
    # 区间覆盖全表外延 → 计满全表
    assert cal.trading_days_between("2023-01-01", "2025-01-01", DAYS) == len(DAYS)
    # a > b (逆序) → 0
    assert cal.trading_days_between("2024-01-08", "2024-01-03", DAYS) == 0
    assert cal.trading_days_between("2024-01-03", "2024-01-08", []) == 0


# ---------------- load_calendar 两路 ----------------
def _fake_fetch_ok():
    # 模拟 ak.tool_trade_date_hist_sina(): 返回带 trade_date 列的 DataFrame(乱序+脏值)
    return pd.DataFrame({"trade_date": ["2024-01-05", "2024-01-03", "2024-01-04",
                                        None, "2024-01-04"]})  # 含 None + 重复 → 应清洗去重排序


def test_load_calendar_real_source():
    cal = _cal()
    res = cal.load_calendar(fetch_fn=_fake_fetch_ok, _cache={})
    assert res["fallback"] is False
    # 清洗：去 None / 去重 / 升序
    assert res["days"] == ["2024-01-03", "2024-01-04", "2024-01-05"]
    assert res.get("caveat") in (None, "")   # 命中真源不带 caveat


def test_load_calendar_fallback_on_error():
    cal = _cal()

    def boom():
        raise RuntimeError("akshare down")

    res = cal.load_calendar(fetch_fn=boom, _cache={})
    assert res["fallback"] is True
    assert res["caveat"]                       # 回退必带 caveat
    assert isinstance(res["days"], list) and len(res["days"]) > 0   # 工作日启发式非空
    # 启发式产物应为升序、且全部 Mon-Fri(无周末)
    from datetime import date
    ds = res["days"]
    assert ds == sorted(ds)
    assert all(date.fromisoformat(d).weekday() < 5 for d in ds)


def test_load_calendar_caches():
    cal = _cal()
    calls = {"n": 0}

    def counting():
        calls["n"] += 1
        return pd.DataFrame({"trade_date": ["2024-01-02", "2024-01-03"]})

    cache = {}
    r1 = cal.load_calendar(fetch_fn=counting, _cache=cache)
    r2 = cal.load_calendar(fetch_fn=counting, _cache=cache)
    assert r1["days"] == r2["days"]
    assert calls["n"] == 1   # 第二次命中缓存, 不再调 fetch
