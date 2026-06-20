"""季节性/日历效应诊断（置换 p 值 + BH 校正；诚实报告"无显著"）。"""
import importlib.util
import sys


def _se():
    sys.path.insert(0, "services/mcp-tool-service")  # seasonality imports multi_test
    s = importlib.util.spec_from_file_location("se", "services/mcp-tool-service/seasonality.py")
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


def _mk(closes, start="2020-01-06"):
    # 2020-01-06 是周一；连续自然日构造，便于落到不同 weekday
    import datetime
    d0 = datetime.date.fromisoformat(start)
    out = []
    for i, c in enumerate(closes):
        out.append({"ts": (d0 + datetime.timedelta(days=i)).isoformat(), "close": c})
    return out


def test_no_significant_seasonality_on_flat():
    se = _se()
    closes = [100 + (i % 3) for i in range(300)]  # 无星期效应
    out = se.day_of_week_effect(_mk(closes))
    assert out["any_significant"] is False
    assert isinstance(out["effects"], list) and len(out["effects"]) >= 1


def test_detects_injected_monday_effect():
    se = _se()
    import datetime
    d0 = datetime.date.fromisoformat("2020-01-06")
    closes = [100.0]
    for i in range(1, 400):
        day = (d0 + datetime.timedelta(days=i)).weekday()
        bump = 0.03 if day == 0 else 0.0  # 周一系统性 +3%
        closes.append(closes[-1] * (1 + bump + (0.0005 if i % 2 else -0.0005)))
    out = se.day_of_week_effect([{"ts": (d0 + datetime.timedelta(days=i)).isoformat(),
                                  "close": c} for i, c in enumerate(closes)])
    assert out["any_significant"] is True


def test_insufficient():
    se = _se()
    out = se.day_of_week_effect([{"ts": "2020-01-06", "close": 1.0}] * 4)
    assert out["any_significant"] is False and out.get("reason")
