"""L4 有效前沿 + 收缩协方差报告（spec §8/§10.2，research-only）。"""
import importlib.util
import sys

import numpy as np

sys.path.insert(0, "services/mcp-tool-service")   # portfolio.py 顶层 import backtest


def _pf():
    s = importlib.util.spec_from_file_location("pf", "services/mcp-tool-service/portfolio.py")
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


def test_efficient_frontier_points_monotone():
    pf = _pf()
    mu = [0.10, 0.08, 0.05]
    cov = [[0.04, 0.001, 0.0], [0.001, 0.03, 0.0], [0.0, 0.0, 0.02]]
    out = pf.efficient_frontier(mu, cov, n_points=6, w_max=0.8)
    pts = out["frontier"]
    assert len(pts) >= 3
    for p in pts:
        assert abs(sum(p["weights"]) - 1.0) < 1e-6      # 权重归一
        assert p["vol"] >= 0 and "ret" in p
    # 风险厌恶越低 → 期望收益越高(更激进)，整体单调不降
    rets = [p["ret"] for p in sorted(pts, key=lambda x: x["vol"])]
    assert rets[-1] >= rets[0] - 1e-9
    assert out["research_only"] is True


def test_shrink_cov_report_flags_reliability():
    pf = _pf()
    rng = np.random.RandomState(0)
    R = rng.randn(200, 5) * 0.02
    rep = pf.shrink_cov_report(R)
    assert 0.0 <= rep["delta"] <= 1.0
    assert rep["condition_number"] > 0
    assert rep["n_assets"] == 5 and rep["n_obs"] == 200
    assert isinstance(rep["reliable"], bool)


def test_shrink_cov_report_illconditioned_when_assets_exceed_obs():
    """资产数≫观测数 → 条件数高/不可靠标记（供 R11 封顶/回退 ERC）。"""
    pf = _pf()
    rng = np.random.RandomState(1)
    R = rng.randn(8, 30) * 0.02     # 8 obs, 30 assets：病态
    rep = pf.shrink_cov_report(R)
    assert rep["reliable"] is False
