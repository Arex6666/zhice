"""M11: 复盘 horizon 漂移 —— 复盘年龄(天)计算 + 窗口边界(纯函数, 离线可测)。"""
import importlib.util
import sys


def _sch():
    sys.path.insert(0, "services/ingestion-service")  # scheduler imports datafetch
    s = importlib.util.spec_from_file_location("sch_m11", "services/ingestion-service/scheduler.py")
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


def test_review_age_days():
    sch = _sch()
    from datetime import datetime, timezone
    now = datetime(2024, 6, 10, tzinfo=timezone.utc)
    assert sch._review_age_days("2024-06-09T00:00:00+00:00", now) == 1
    assert sch._review_age_days("2024-06-05T00:00:00+00:00", now) == 5
    assert sch._review_age_days("garbage", now) is None       # 容错


def test_in_review_window_bounds_horizon_drift():
    sch = _sch()
    from datetime import datetime, timezone
    now = datetime(2024, 6, 10, tzinfo=timezone.utc)
    assert sch._in_review_window("2024-06-09T00:00:00+00:00", now) is True    # ~1日, 入窗
    assert sch._in_review_window("2024-06-01T00:00:00+00:00", now) is False   # 9日漂移, 出窗
    assert sch._in_review_window("2024-06-10T06:00:00+00:00", now) is False   # 不足1日
