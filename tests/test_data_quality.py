import importlib.util


def _dq():
    s = importlib.util.spec_from_file_location("dq", "services/mcp-tool-service/data_quality.py")
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


def test_fresh_vs_stale():
    dq = _dq()
    q = {"price": 10.0, "ts": 1000.0, "volume": 100, "prev_close": 9.9}
    assert dq.assess(dict(q), "ASHARE", "sina", now_ts=1000.0 + 60)["data_status"] == "fresh"
    assert dq.assess(dict(q), "ASHARE", "sina", now_ts=1000.0 + 86400)["data_status"] == "stale"


def test_error_when_no_price():
    dq = _dq()
    q = {"price": None, "ts": 1000.0}
    assert dq.assess(q, "US", "yfinance", now_ts=1000.0)["data_status"] == "error"


def test_halt_limit_and_divergence():
    dq = _dq()
    q = {"price": 10.0, "ts": 1000.0, "volume": 0, "prev_close": 10.0}
    a = dq.assess(dict(q), "ASHARE", "sina", now_ts=1000.0 + 10)
    assert a["halted"] is True
    up = {"price": 11.0, "ts": 1000.0, "volume": 5, "prev_close": 10.0}
    assert dq.assess(up, "ASHARE", "sina", now_ts=1000.0 + 10)["limit_up"] is True
    assert dq.cross_source_check([10.0, 10.5]) is True
    assert dq.cross_source_check([10.0, 10.02]) is False


def test_fallback_source():
    dq = _dq()
    q = {"price": 50000.0, "ts": 1000.0, "volume": 5}
    assert dq.assess(q, "CRYPTO", "coingecko-fallback", now_ts=1000.0 + 5)["data_status"] == "fallback"
