"""可观测性：TTL 缓存 + 按数据源 调用/错误/命中/延迟 指标。"""
import importlib.util


def _obs():
    s = importlib.util.spec_from_file_location("obs", "services/mcp-tool-service/obs.py")
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


def test_ttl_cache_hit_and_expiry():
    obs = _obs()
    t = [1000.0]
    c = obs.TTLCache(clock=lambda: t[0])
    c.set("k", "v", ttl=60)
    assert c.get("k") == "v"     # 命中(未过期)
    t[0] += 61
    assert c.get("k") is None    # 过期淘汰


def test_metrics_record_snapshot():
    obs = _obs()
    m = obs.Metrics()
    m.record("sina", 0.1, ok=True, hit=False)
    m.record("sina", 0.3, ok=True, hit=True)
    m.record("sina", 0.05, ok=False, hit=False)
    snap = m.snapshot()["sina"]
    assert snap["calls"] == 3 and snap["errors"] == 1 and snap["hits"] == 1
    assert snap["error_rate"] == round(1 / 3, 3)
    assert snap["latency_ms_avg"] > 0 and snap["latency_ms_max"] >= snap["latency_ms_avg"]
