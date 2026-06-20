"""校准自审纯函数：Brier / ECE / 可靠性分箱 / 过度自信判定。"""
import importlib.util


def _cal():
    s = importlib.util.spec_from_file_location("cal", "services/agent-service/calibration.py")
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


def test_empty_returns_none():
    cal = _cal()
    assert cal.assess([]) is None


def test_overconfident_high_brier():
    cal = _cal()
    # 全部以 0.9 置信度断言，但仅 30% 命中 → 过度自信、Brier 偏高
    pts = [(0.9, 1)] * 3 + [(0.9, 0)] * 7
    out = cal.assess(pts)
    assert out["verdict"] == "过度自信"
    assert out["brier"] > 0.3
    assert out["ece"] > 0.4  # |0.9 - 0.3|
    assert out["n"] == 10


def test_well_calibrated():
    cal = _cal()
    # 0.5 置信度、50% 命中 → 校准良好
    pts = [(0.5, 1)] * 5 + [(0.5, 0)] * 5
    out = cal.assess(pts)
    assert out["verdict"] == "校准良好"
    assert out["brier"] <= 0.26
    assert isinstance(out["reliability"], list)
