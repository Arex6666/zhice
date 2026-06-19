import importlib.util


def _ind():
    s = importlib.util.spec_from_file_location("ind", "services/mcp-tool-service/indicators.py")
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


def test_ma_rsi():
    ind = _ind()
    closes = [float(i) for i in range(1, 40)]  # strictly rising
    r = ind.compute_indicators(closes)
    assert round(r["ma5"], 2) == round(sum(closes[-5:]) / 5, 2)
    assert r["rsi14"] > 99  # all-up series -> RSI ~100
    assert "dif" in r["macd"] and "up" in r["boll"]


def test_short_series_no_crash():
    ind = _ind()
    r = ind.compute_indicators([1.0, 2.0])
    assert r["ma60"] is None and r["ma5"] is None


def test_vol_ratio():
    ind = _ind()
    closes = [float(i) for i in range(1, 30)]
    vols = [100] * 28 + [300]
    r = ind.compute_indicators(closes, volumes=vols)
    assert r["vol_ratio"] == 3.0
