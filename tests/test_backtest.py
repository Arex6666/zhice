import importlib.util


def _bt():
    s = importlib.util.spec_from_file_location("bt", "services/mcp-tool-service/backtest.py")
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


def test_metrics_present():
    bt = _bt()
    closes = [100, 101, 102, 101, 103, 105, 104, 106, 108, 107, 109, 111, 110, 112] * 4
    r = bt.backtest_ma(closes, 3, 8)
    for k in ["total_return", "annualized", "benchmark_return", "max_drawdown",
              "sharpe", "win_rate", "max_consec_loss", "trades", "disclaimer"]:
        assert k in r
    assert "不可直接外推" in r["disclaimer"]


def test_insufficient_data():
    bt = _bt()
    r = bt.backtest_ma([1, 2, 3], 3, 8)
    assert "error" in r


def test_sensitivity():
    bt = _bt()
    closes = [100 + (i % 5) for i in range(80)]
    g = bt.param_sensitivity(closes, [(3, 8), (5, 20)])
    assert len(g) == 2 and "total_return" in g[0]


def test_bootstrap_significant_positive():
    import numpy as np
    bt = _bt()
    rng = np.random.RandomState(1)
    r = 0.01 + 0.001 * rng.randn(200)  # 明显正均值、低噪 → 显著
    out = bt.bootstrap_significance(list(r))
    assert out["significant"] is True
    assert out["p_value"] < 0.05
    assert out["ci_low"] > 0


def test_bootstrap_not_significant_noise():
    import numpy as np
    bt = _bt()
    rng = np.random.RandomState(2)
    r = 0.02 * rng.randn(200)  # 零均值高噪 → 不显著
    out = bt.bootstrap_significance(list(r))
    assert out["significant"] is False


def test_bootstrap_insufficient():
    bt = _bt()
    out = bt.bootstrap_significance([0.01, 0.02, 0.01])
    assert out["significant"] is None


def test_backtest_includes_significance():
    bt = _bt()
    closes = [100, 101, 102, 101, 103, 105, 104, 106, 108, 107, 109, 111, 110, 112] * 4
    r = bt.backtest_ma(closes, 3, 8)
    assert "significance" in r and "significant" in r["significance"]


def test_backtest_exposes_equity_curve():
    bt = _bt()
    closes = [100, 101, 102, 101, 103, 105, 104, 106, 108, 107, 109, 111, 110, 112] * 4
    r = bt.backtest_ma(closes, 3, 8)
    assert "equity_curve" in r and "benchmark_curve" in r
    assert len(r["equity_curve"]) >= 2
    assert len(r["equity_curve"]) == len(r["benchmark_curve"])
