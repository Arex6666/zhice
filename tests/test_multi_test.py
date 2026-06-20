"""L2 多重检验：BH(回归守护) / Bonferroni / Harvey / Deflated Sharpe(§7.2 口径)。"""
import importlib.util
import sys


def _mt():
    sys.path.insert(0, "services/mcp-tool-service")
    s = importlib.util.spec_from_file_location("mt", "services/mcp-tool-service/multi_test.py")
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


def _ref_bh(pv):
    """seasonality 原内联 BH 的独立参考实现（逐位相等回归基准）。"""
    m = len(pv)
    order = sorted(range(m), key=lambda i: pv[i])
    adj = [0.0] * m
    running = 1.0
    for rank in range(m - 1, -1, -1):
        i = order[rank]
        running = min(running, pv[i] * m / (rank + 1))
        adj[i] = min(1.0, running)
    return adj


def test_bh_bit_identical_to_reference():
    mt = _mt()
    pvals = [0.01, 0.04, 0.03, 0.20, 0.50]
    assert mt.bh(pvals) == _ref_bh(pvals)


def test_bonferroni():
    mt = _mt()
    assert mt.bonferroni([0.01, 0.02]) == [0.02, 0.04]
    assert mt.bonferroni([0.6, 0.7]) == [1.0, 1.0]  # 封顶 1.0


def test_harvey_threshold():
    mt = _mt()
    assert mt.harvey_passed(3.1) is True
    assert mt.harvey_passed(2.9) is False


def test_deflated_sharpe_monotonic_and_var_source():
    mt = _mt()
    # 每期(非年化)夏普 ~0.1，T=252；DSR 不饱和，可观测单调下降
    d1 = mt.deflated_sharpe(0.1, n_trials=1, n_obs=252)
    d50 = mt.deflated_sharpe(0.1, n_trials=50, n_obs=252)
    assert d50["sr0"] > d1["sr0"]                 # 去膨胀阈值随试验数升高(机制)
    assert d50["dsr"] < d1["dsr"]                 # 更多试验 → DSR 下降
    assert d1["var_source"] == "analytic_1overT"  # 无分布 → 解析回退
    dg = mt.deflated_sharpe(0.1, n_trials=10, var_sr_trials=0.25, n_obs=252)
    assert dg["var_source"] == "grid_distribution"


def test_deflated_sharpe_psr_when_single_trial():
    mt = _mt()
    d = mt.deflated_sharpe(1.0, n_trials=1, n_obs=252)
    assert d["sr0"] == 0.0 and 0.0 <= d["dsr"] <= 1.0  # N=1 退化 PSR
