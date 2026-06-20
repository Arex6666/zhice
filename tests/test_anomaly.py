"""稳健价量异动检测（MAD/Hampel）+ 数据错误 vs 真实事件消歧。"""
import importlib.util


def _an():
    s = importlib.util.spec_from_file_location("an", "services/mcp-tool-service/anomaly.py")
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


def test_mad_zscore_flags_outlier():
    an = _an()
    x = [0.0] * 30 + [10.0]  # 末位极端值
    z = an.mad_zscore(x)
    assert abs(z[-1]) > 5
    assert all(abs(v) < 1 for v in z[:-1])


def test_detect_event_vs_bad_data():
    an = _an()
    # 平稳 + 末日大涨且放量 → suspected_event
    base = [{"close": 100 + 0.01 * i, "volume": 100} for i in range(40)]
    base.append({"close": 112.0, "volume": 1000})  # +10% on 10x volume
    out = an.detect_anomalies(base)
    assert out["anomalies"], "应检出末位异动"
    last = out["anomalies"][-1]
    assert last["classification"] == "suspected_event"


def test_detect_bad_data_without_volume():
    an = _an()
    base = [{"close": 100 + 0.01 * i, "volume": 100} for i in range(40)]
    base.append({"close": 130.0, "volume": 100})  # +30% spike, no volume → bad data
    out = an.detect_anomalies(base)
    last = out["anomalies"][-1]
    assert last["classification"] == "suspected_bad_data"


def test_detect_insufficient():
    an = _an()
    out = an.detect_anomalies([{"close": 1.0, "volume": 1}] * 5)
    assert out["anomalies"] == [] and out.get("reason")
