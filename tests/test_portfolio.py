"""L4 组合（research-only）：LedoitWolf 收缩 + ERC 风险平价 + HRP + vs 1/N。"""
import importlib.util
import sys

import numpy as np


def _pf():
    sys.path.insert(0, "services/mcp-tool-service")  # imports backtest
    s = importlib.util.spec_from_file_location("pf", "services/mcp-tool-service/portfolio.py")
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


def test_shrink_cov_psd_and_delta():
    pf = _pf()
    rng = np.random.RandomState(0)
    R = rng.randn(60, 10)
    out = pf.shrink_cov(R)
    cov = np.array(out["cov"])
    assert cov.shape == (10, 10)
    assert 0.0 <= out["delta"] <= 1.0
    assert np.linalg.eigvalsh(cov).min() > -1e-9          # 半正定


def test_erc_equal_risk_contribution():
    pf = _pf()
    cov = np.diag([0.04, 0.01, 0.09])                     # vols 0.2/0.1/0.3
    w = np.array(pf.risk_parity_erc(cov))
    assert abs(w.sum() - 1) < 1e-6 and (w > 0).all()
    rc = w * (cov @ w)
    assert np.allclose(rc, rc.mean(), rtol=0.05)          # 风险贡献相等
    assert w[1] > w[0] > w[2]                              # 低波 → 高权重


def test_hrp_weights_valid():
    pf = _pf()
    rng = np.random.RandomState(1)
    R = rng.randn(120, 8)
    w = np.array(pf.hrp_weights(R))
    assert abs(w.sum() - 1) < 1e-6 and (w >= 0).all() and len(w) == 8


def test_beats_one_over_n():
    pf = _pf()
    rng = np.random.RandomState(2)
    base = rng.randn(60) * 0.01
    assert pf.beats_one_over_n(base + 0.005, base)["beats"] is True   # 稳定超额
    out2 = pf.beats_one_over_n(rng.randn(60) * 0.01, rng.randn(60) * 0.01)
    assert out2["beats"] in (False, None)                            # 噪声不跑赢
