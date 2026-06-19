import importlib.util


def _r():
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
