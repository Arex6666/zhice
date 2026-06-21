"""L1 因子库 zoo：价量因子公式注册表 + DSL 计算（history_native，立即可算）。"""
import importlib.util
import sys

import numpy as np


def _zoo():
    sys.path.insert(0, "services/mcp-tool-service")  # imports factor_dsl
    s = importlib.util.spec_from_file_location("zoo", "services/mcp-tool-service/zoo.py")
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


def test_registry_has_metadata():
    z = _zoo()
    assert "Mom_12_1" in z.FACTORS
    for name, m in z.FACTORS.items():
        assert {"formula", "direction", "family", "pit_status"} <= set(m), name
        assert m["direction"] in ("+", "-", "risk_gate")


def test_compute_momentum_positive_on_uptrend():
    z = _zoo()
    C = np.array([100 * (1.001 ** i) for i in range(300)])
    V = np.full(300, 1e6)
    out = z.compute("Mom_12_1", {"C": C, "V": V})
    assert out[-1] > 0
    assert z.FACTORS["Mom_12_1"]["pit_status"] == "history_native"


def test_compute_reversal_sign():
    z = _zoo()
    C = np.array([100 * (1.001 ** i) for i in range(30)])  # 持续上涨
    out = z.compute("Rev_5", {"C": C, "V": np.full(30, 1e6)})
    assert out[-1] < 0   # 反转因子=-(近5日涨幅)，上涨→负


def test_unknown_factor_raises():
    z = _zoo()
    import pytest
    with pytest.raises(Exception):
        z.compute("NoSuchFactor", {"C": [1.0]})
