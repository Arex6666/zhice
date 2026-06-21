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


def test_mvo_constraints_satisfied():
    pf = _pf()
    rng = np.random.RandomState(0)
    n = 10
    mu = rng.randn(n) * 0.01
    R = rng.randn(60, n)
    cov = np.cov(R, rowvar=False)
    out = pf.mvo(mu, cov, w_max=0.2)
    w = np.array(out["weights"])
    assert out["status"] == "optimal"
    assert abs(w.sum() - 1) < 1e-4 and (w >= -1e-6).all() and (w <= 0.2 + 1e-4).all()


def test_mvo_infeasible_falls_back():
    pf = _pf()
    out = pf.mvo(np.zeros(3), np.eye(3), w_max=0.2)   # 3*0.2=0.6<1 → 不可行
    assert out["status"] != "optimal" and out.get("fallback_reason")
    assert abs(sum(out["weights"]) - 1) < 1e-6        # 回退等权


def test_capacity_check_flags_illiquid():
    pf = _pf()
    out = pf.capacity_check([0.5, 0.5], capital=1e9, adv=[1e6, 1e10])
    assert out["names"][0]["illiquid"] is True        # 大仓位 vs 极小 ADV
    assert out["names"][1]["illiquid"] is False


def test_build_portfolio_hrp_default():
    pf = _pf()
    rng = np.random.RandomState(5)
    syms = [f"S{i}" for i in range(8)]
    out = pf.build_portfolio(syms, scores=None, returns_panel=rng.randn(120, 8), method="hrp")
    assert abs(sum(out["weights"].values()) - 1) < 1e-6 and out["method"] == "hrp"


def test_hrp_single_and_two_assets():
    pf = _pf()
    assert pf.hrp_weights(np.random.RandomState(0).randn(60, 1)) == [1.0]   # 单资产不崩
    w = np.array(pf.hrp_weights(np.random.RandomState(0).randn(60, 2)))
    assert abs(w.sum() - 1) < 1e-9 and len(w) == 2


def test_build_portfolio_single_symbol_all_methods():
    pf = _pf()
    R = np.random.RandomState(0).randn(60, 1)
    for method in ("hrp", "erc", "mvo"):
        out = pf.build_portfolio(["AAPL"], scores=[0.1], returns_panel=R, method=method)
        assert out["weights"] == {"AAPL": 1.0}


def test_hrp_handles_zero_variance_column():
    pf = _pf()
    R = np.random.RandomState(1).randn(120, 4)
    R[:, 1] = 0.0                                       # 停牌/一字板恒定收益
    w = np.array(pf.hrp_weights(R))
    assert np.isfinite(w).all() and abs(w.sum() - 1) < 1e-6   # 不崩、权重有限


def test_beats_one_over_n():
    pf = _pf()
    rng = np.random.RandomState(2)
    base = rng.randn(60) * 0.01
    assert pf.beats_one_over_n(base + 0.005, base)["beats"] is True   # 稳定超额
    out2 = pf.beats_one_over_n(rng.randn(60) * 0.01, rng.randn(60) * 0.01)
    assert out2["beats"] in (False, None)                            # 噪声不跑赢
