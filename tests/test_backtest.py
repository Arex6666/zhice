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
