"""L1 另类因子（forward_pit_only）：北向/EPS修正/PEAD/股东户数 + 冷启动弃权守门。"""
import importlib.util

import numpy as np


def _af():
    s = importlib.util.spec_from_file_location("af", "services/mcp-tool-service/altfactors.py")
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


def test_northbound_flow_change():
    af = _af()
    hold = list(np.linspace(1.0, 3.0, 40))           # 北向持股比上升
    out = af.northbound_flow(hold, lag=20)
    assert out[-1] > 0                                # 持股比抬升 → 正


def test_chip_concentration():
    af = _af()
    counts = list(np.linspace(100000, 80000, 10))    # 股东户数下降=筹码集中
    out = af.chip(counts)
    assert out[-1] > 0                                # -Δln(户数) > 0


def test_eps_revision_unscaled():
    af = _af()
    v = af.eps_revision(1.2, 1.0, 0.5)               # (1.2-1.0)/|0.5|=0.4
    assert abs(v - 0.4) < 1e-9


def test_cold_start_abstain():
    af = _af()
    out = af.with_pit_guard([0.1, 0.2], history_depth_days=30)  # <252
    assert out["abstain"] is True and out["abstain_reason"] == "insufficient_history"
    ok = af.with_pit_guard([0.1, 0.2], history_depth_days=300)
    assert ok["abstain"] is False
