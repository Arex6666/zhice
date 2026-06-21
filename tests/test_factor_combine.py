"""L3 因子合成：线性基线（等权 / IC 加权，按方向）。"""
import importlib.util

import numpy as np


def _fc():
    s = importlib.util.spec_from_file_location("fc", "services/mcp-tool-service/factor_combine.py")
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


def test_equal_weight_respects_direction():
    fc = _fc()
    panel = {"A": np.array([1.0, -1.0]), "B": np.array([1.0, -1.0])}
    directions = {"A": "+", "B": "-"}        # B 反向 → 抵消
    score = np.array(fc.combine(panel, directions))
    assert np.allclose(score, 0.0)


def test_ic_weighted():
    fc = _fc()
    panel = {"A": np.array([2.0, -2.0]), "B": np.array([1.0, -1.0])}
    directions = {"A": "+", "B": "+"}
    ic = {"A": 0.8, "B": 0.0}                 # 只信 A
    score = np.array(fc.combine(panel, directions, ic_weights=ic))
    assert score[0] > 0 and score[1] < 0      # 由 A 主导


def test_empty_panel_zero():
    fc = _fc()
    assert fc.combine({}, {}) == []
