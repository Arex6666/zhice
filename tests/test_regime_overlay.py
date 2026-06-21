"""L5 风控/择时叠加：QVIX 分位 + 已实现波动 → 仓位乘子(只减不加)。"""
import importlib.util

import numpy as np


def _qv():
    s = importlib.util.spec_from_file_location("qv", "services/mcp-tool-service/qvix_timing.py")
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


def _ro():
    s = importlib.util.spec_from_file_location("ro", "services/mcp-tool-service/regime_overlay.py")
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


def test_qvix_level_extreme_on_spike():
    qv = _qv()
    series = list(np.full(240, 15.0)) + list(np.linspace(15, 40, 20))  # 近期飙升
    out = qv.qvix_level(series)
    assert out["level"] in ("elevated", "extreme") and out["percentile"] > 0.8


def test_qvix_insufficient():
    qv = _qv()
    assert qv.qvix_level([15.0] * 5)["level"] == "unknown"


def test_target_scale_min_and_capped():
    ro = _ro()
    assert ro.target_scale("extreme", "normal")["scale"] == 0.5   # 取 min(0.5,1.0)
    assert ro.target_scale("normal", "normal")["scale"] == 1.0    # 永不>1
    assert ro.target_scale("elevated", "extreme")["scale"] == 0.5  # 两刹车取 min
    assert ro.target_scale("low", "low", floor=0.6)["scale"] == 1.0
    assert ro.target_scale("normal", "normal", floor=1.5)["scale"] == 1.0  # floor>1 不得放大>1
