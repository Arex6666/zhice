import importlib.util


def _fin():
    s = importlib.util.spec_from_file_location("fin", "services/mcp-tool-service/finance.py")
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


SINA = 'var hq_str_sh600519="贵州茅台,1200.0,1215.0,1208.0,1220.0,1198.0,100,200,3000,4000000";'

# 完整 sina 行情含日期(下标30)+时间(下标31)，与真实接口一致。
FULL_SINA = ('var hq_str_sh600519="贵州茅台,1688.0,1685.0,1700.0,1710.0,1680.0,1699.0,1700.0,'
             '123456,200000000.0,' + ','.join(['0'] * 20) + ',2024-01-15,15:00:00,00";')


def test_parse_sina():
    fin = _fin()
    q = fin.parse_sina_quote(SINA)
    assert q["name"] == "贵州茅台"
    assert q["price"] == 1208.0
    assert q["prev_close"] == 1215.0
    assert q["open"] == 1200.0
    assert q["volume"] == 3000.0
    assert q["source"] == "sina"


def test_parse_sina_uses_real_market_timestamp():
    """含日期/时间字段时，ts 必须是真实成交时间，而非 time.time()——否则新鲜度恒为 fresh。"""
    import time
    from datetime import datetime
    from zoneinfo import ZoneInfo
    fin = _fin()
    q = fin.parse_sina_quote(FULL_SINA)
    expected = datetime(2024, 1, 15, 15, 0, 0, tzinfo=ZoneInfo("Asia/Shanghai")).timestamp()
    assert abs(q["ts"] - expected) < 2.0
    assert time.time() - q["ts"] > 1000  # 明显早于当前 → 可被 assess() 判为 stale


def test_parse_sina_short_payload_falls_back_to_now():
    """缺日期/时间的精简载荷优雅回退到当前时间（不崩溃）。"""
    import time
    fin = _fin()
    q = fin.parse_sina_quote(SINA)
    assert abs(q["ts"] - time.time()) < 5.0


def test_kline_rows_carry_adjust_marker():
    """东财 K 线带请求的复权口径；新浪回退标记为 'none'（不复权），供下游识别口径漂移。"""
    fin = _fin()
    em = fin._em_kline_rows(["2024-01-02,10,11,12,9,1000"], "qfq")
    assert em[0]["adjust_actual"] == "qfq"
    sina = fin._sina_kline_rows([{"day": "2024-01-02", "open": "10", "high": "12",
                                  "low": "9", "close": "11", "volume": "1000"}])
    assert sina[0]["adjust_actual"] == "none"


def test_split_symbol():
    fin = _fin()
    assert fin.split_symbol("ASHARE:600519") == ("ASHARE", "600519")
    assert fin.split_symbol("CRYPTO:BTCUSDT") == ("CRYPTO", "BTCUSDT")


def test_get_adapter_unknown():
    fin = _fin()
    import pytest
    with pytest.raises(ValueError):
        fin.get_adapter("FOREX")
