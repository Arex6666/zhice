"""L2 因子评估：Rank-IC/ICIR/HAC-t/分层单调 + 显著性硬判定（含弃权）。"""
import importlib.util
import sys

import numpy as np


def _fe():
    sys.path.insert(0, "services/mcp-tool-service")  # imports backtest/multi_test
    s = importlib.util.spec_from_file_location("fe", "services/mcp-tool-service/factor_eval.py")
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


def test_informative_factor_significant_and_monotonic():
    fe = _fe()
    rng = np.random.RandomState(0)
    fac, ret = [], []
    for _ in range(40):                       # 40 调仓期 × 50 股
        r = rng.randn(50)
        fac.append(r + 0.5 * rng.randn(50))   # 因子≈未来收益+噪声 → IC>0
        ret.append(r)
    rep = fe.factor_report(fac, ret, n_quantiles=5)
    assert rep["mean_rank_ic"] > 0.2
    assert rep["significant"] == 1
    assert rep["monotonic_spearman"] > 0.5    # 高分位高收益


def test_noise_factor_not_significant():
    fe = _fe()
    rng = np.random.RandomState(1)
    fac = [rng.randn(50) for _ in range(40)]
    ret = [rng.randn(50) for _ in range(40)]
    rep = fe.factor_report(fac, ret)
    assert rep["significant"] == 0
    assert abs(rep["mean_rank_ic"]) < 0.1


def test_min_dates_below_bootstrap_floor_abstains_not_zero():
    fe = _fe()
    rng = np.random.RandomState(3)
    fac, ret = [], []
    for _ in range(15):                              # 15 期 < 块自助底线 20
        r = rng.randn(50)
        fac.append(r + 0.5 * rng.randn(50))
        ret.append(r)
    rep = fe.factor_report(fac, ret, min_dates=10)   # 绕过 min_dates 但块自助 p 无法算
    assert rep["significant"] is None and rep["abstain_reason"] == "insufficient_history"
    assert rep["ic_block_boot_p"] is None


def test_constant_ic_series_returns_none_t():
    fe = _fe()
    assert fe.ic_hac_t([0.05] * 25) is None           # 零方差不得伪装成天文 t


def test_degenerate_panel_abstains():
    fe = _fe()
    xs = np.arange(50.0)
    rep = fe.factor_report([xs] * 30, [xs] * 30)      # 每期同截面 → IC 恒定
    assert rep["significant"] is None and rep["abstain_reason"] == "statistical_abstain"


def test_insufficient_dates_abstain():
    fe = _fe()
    rng = np.random.RandomState(2)
    fac = [rng.randn(50) for _ in range(5)]   # <20 期
    ret = [rng.randn(50) for _ in range(5)]
    rep = fe.factor_report(fac, ret)
    assert rep["significant"] is None and rep["abstain_reason"] == "insufficient_history"
