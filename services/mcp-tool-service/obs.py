"""可观测性原语（纯 Python）：进程内 TTL 缓存 + 按数据源指标。

TTL 缓存：在实时行情适配器前削减重复外呼，降低限流/ToS 风险。
Metrics：按数据源记录 调用/错误/命中/延迟，供 /metrics 与"数据源健康"面板展示。
clock 可注入，便于脱时间单测。
"""
import time as _time


class TTLCache:
    def __init__(self, clock=None):
        self._d = {}
        self._clock = clock or _time.monotonic

    def get(self, key):
        e = self._d.get(key)
        if not e:
            return None
        val, exp = e
        if self._clock() >= exp:
            self._d.pop(key, None)
            return None
        return val

    def set(self, key, val, ttl):
        self._d[key] = (val, self._clock() + ttl)

    def clear(self):
        self._d.clear()


class Metrics:
    def __init__(self):
        self._d = {}

    def record(self, source, latency_s=0.0, ok=True, hit=False):
        d = self._d.setdefault(source, {"calls": 0, "errors": 0, "hits": 0,
                                        "lat_sum": 0.0, "lat_max": 0.0, "lat_n": 0})
        d["calls"] += 1
        if not ok:
            d["errors"] += 1
        if hit:
            d["hits"] += 1
        if latency_s and latency_s > 0:
            d["lat_sum"] += latency_s
            d["lat_n"] += 1
            d["lat_max"] = max(d["lat_max"], latency_s)

    def snapshot(self):
        out = {}
        for s, d in self._d.items():
            out[s] = {
                "calls": d["calls"], "errors": d["errors"], "hits": d["hits"],
                "error_rate": round(d["errors"] / d["calls"], 3) if d["calls"] else 0.0,
                "hit_rate": round(d["hits"] / d["calls"], 3) if d["calls"] else 0.0,
                "latency_ms_avg": round(1000 * d["lat_sum"] / d["lat_n"], 1) if d["lat_n"] else 0.0,
                "latency_ms_max": round(1000 * d["lat_max"], 1),
            }
        return out
