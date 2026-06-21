"""L4 风险模型：Barra 式 Σ=BFB'+D 风险归因（系统/特质分解）。"""
import importlib.util

import numpy as np


def _rm():
    s = importlib.util.spec_from_file_location("rm", "services/mcp-tool-service/risk_model.py")
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


def test_risk_attribution_decomposition():
    rm = _rm()
    w = np.array([0.5, 0.5])
    B = np.array([[1.0, 0.0], [0.0, 1.0]])     # 2 股 × 2 因子
    F = np.array([[0.04, 0.0], [0.0, 0.09]])   # 因子协方差
    D = np.array([0.01, 0.01])                  # 特质方差
    out = rm.risk_attribution(w, B, F, D)
    assert abs(out["total_var"] - (out["systematic_var"] + out["specific_var"])) < 1e-9
    assert out["systematic_var"] > 0 and out["specific_var"] > 0
    # 手算: sys = (B'w)'F(B'w) = [0.5,0.5]·diag(0.04,0.09)·[0.5,0.5] = 0.01+0.0225=0.0325
    assert abs(out["systematic_var"] - 0.0325) < 1e-9
    assert abs(out["specific_var"] - (0.25 * 0.01 + 0.25 * 0.01)) < 1e-9
