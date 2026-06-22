"""港股 K 线解析（腾讯 gtimg hkfqkline，实测抓包）——纯函数脱网可测。

东财 push2his 港股 K线源在本机被限流(返回空) → 改用腾讯 ifzq.gtimg.cn 作主源。
行格式实测：[日期, 开, 收, 高, 低, 量, {除权信息}, 换手, 成交额, ...]
复权键名随口径变化：股票 qfq → 'qfqday'；指数(不复权) → 'day'。
"""
import importlib.util


def _fin():
    s = importlib.util.spec_from_file_location("fin", "services/mcp-tool-service/finance.py")
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


# 实测：腾讯港股(前复权)返回 data.hk00700.qfqday，行 [日期,开,收,高,低,量,...]
STOCK = {"code": 0, "msg": "", "data": {"hk00700": {"qfqday": [
    ["2026-06-15", "475.000", "459.600", "476.800", "457.800", "19748938.000",
     {"cqr": "2026-06-15"}, "0.220", "916114.887"],
    ["2026-06-16", "462.600", "447.400", "462.600", "445.400", "24323142.000",
     {"cqr": "2026-06-16"}, "0.270", "1092770.096"],
]}}}

# 实测：腾讯港股指数(恒生)不复权 → 键名为 'day'（非 qfqday）
INDEX = {"code": 0, "msg": "", "data": {"hkHSI": {"day": [
    ["2026-06-12", "24501.500", "24718.100", "24771.609", "24445.510", "316438308281.00",
     {}, "0.00", "31643830.83", "0.000", "0.000"],
]}}}


def test_parse_tencent_stock_ohlcv_order():
    """股票行：开=列1, 收=列2, 高=列3, 低=列4, 量=列5（腾讯字段序与东财不同）。"""
    fin = _fin()
    rows = fin.parse_tencent_hk_kline(STOCK, "00700", "daily")
    assert len(rows) == 2
    r0 = rows[0]
    assert r0["ts"] == "2026-06-15"
    assert r0["open"] == 475.0
    assert r0["close"] == 459.6
    assert r0["high"] == 476.8
    assert r0["low"] == 457.8
    assert r0["volume"] == 19748938.0
    assert r0["adjust_actual"] == "qfq"   # 股票走 qfqday → 前复权口径


def test_parse_tencent_accepts_hk_prefixed_code():
    """code 可带或不带 'hk' 前缀，均能命中 data.hkXXXX。"""
    fin = _fin()
    rows = fin.parse_tencent_hk_kline(STOCK, "hk00700", "daily")
    assert len(rows) == 2 and rows[1]["close"] == 447.4


def test_parse_tencent_index_falls_back_to_day_key():
    """指数无复权键(qfqday)，应回退到 'day' 键，且口径标为 none（指数不复权）。"""
    fin = _fin()
    rows = fin.parse_tencent_hk_kline(INDEX, "HSI", "daily")
    assert len(rows) == 1
    assert rows[0]["open"] == 24501.5 and rows[0]["high"] == 24771.609
    assert rows[0]["adjust_actual"] == "none"


def test_parse_tencent_empty_graceful():
    """空/异常载荷 → 返回 []（图表优雅降级，绝不抛错崩溃）。"""
    fin = _fin()
    assert fin.parse_tencent_hk_kline({}, "00700", "daily") == []
    assert fin.parse_tencent_hk_kline({"data": {"hk00700": {}}}, "00700", "daily") == []
    assert fin.parse_tencent_hk_kline({"data": {}}, "00700", "daily") == []
