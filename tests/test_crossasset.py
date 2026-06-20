"""跨资产：β / 相关 / R² / 相对强弱 / 下行 β。"""
import importlib.util

import numpy as np


def _ca():
    s = importlib.util.spec_from_file_location("ca", "services/mcp-tool-service/crossasset.py")
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


def test_beta_of_2x_leveraged():
    ca = _ca()
    rng = np.random.RandomState(0)
    idx = 100 * np.cumprod(1 + 0.01 * rng.randn(120))
    # 个股 ≈ 指数收益的 2 倍 → beta≈2, corr≈1
    idx_ret = np.diff(idx) / idx[:-1]
    stk = [100.0]
    for r in idx_ret:
        stk.append(stk[-1] * (1 + 2 * r))
    out = ca.beta_context(stk, list(idx))
    assert 1.7 < out["beta"] < 2.3
    assert out["corr"] > 0.95
    assert out["r2"] > 0.9


def test_insufficient_returns_none():
    ca = _ca()
    out = ca.beta_context([1, 2, 3], [1, 2, 3])
    assert out["beta"] is None
