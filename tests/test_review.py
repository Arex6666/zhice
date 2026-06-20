import importlib.util
import sys


def _r():
    sys.path.insert(0, "services/agent-service")  # review.py imports calibration
    s = importlib.util.spec_from_file_location("rv", "services/agent-service/review.py")
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


def test_overconfidence_flag():
    rv = _r()
    out = rv.summarize({"reviewed": 10, "hit_rate": 0.3, "avg_confidence_when_wrong": 0.8, "by_member": {}})
    assert out["chairman_overconfident"] is True
    assert "过度自信" in out["note"]


def test_healthy_no_flag():
    rv = _r()
    out = rv.summarize({"reviewed": 10, "hit_rate": 0.7, "avg_confidence_when_wrong": 0.5, "by_member": {}})
    assert out["chairman_overconfident"] is False


def test_empty():
    rv = _r()
    out = rv.summarize({"reviewed": 0, "hit_rate": None, "avg_confidence_when_wrong": None, "by_member": {}})
    assert out["chairman_overconfident"] is False and "暂无" in out["note"]


def test_summarize_includes_calibration():
    rv = _r()
    pts = [(0.9, 1)] * 3 + [(0.9, 0)] * 7  # 过度自信
    out = rv.summarize({"reviewed": 10, "hit_rate": 0.3, "avg_confidence_when_wrong": 0.9,
                        "by_member": {}, "confidence_points": pts})
    assert out["calibration"] is not None
    assert out["calibration"]["verdict"] == "过度自信"


def test_summarize_no_calibration_points():
    rv = _r()
    out = rv.summarize({"reviewed": 0, "hit_rate": None, "avg_confidence_when_wrong": None,
                        "by_member": {}})
    assert out["calibration"] is None
