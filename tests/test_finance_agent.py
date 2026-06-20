"""finance_agent._ml_vote：异常路径契约（prob_big_move，而非死键 prob_up）。"""
import importlib.util
import sys


def _fa():
    sys.path.insert(0, "services/agent-service")
    s = importlib.util.spec_from_file_location("finance_agent", "services/agent-service/finance_agent.py")
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


def test_ml_vote_exception_uses_prob_big_move_key(monkeypatch):
    fa = _fa()

    class Boom:
        def predict(self, feats):
            raise RuntimeError("inference boom")

    monkeypatch.setattr(fa.SignalCalibrator, "load", classmethod(lambda cls, p: Boom()))
    kline = [{"close": 10.0 + i * 0.1, "high": 10.5 + i * 0.1, "low": 9.5 + i * 0.1,
              "open": 10.0 + i * 0.1, "volume": 100} for i in range(30)]
    out = fa._ml_vote("ASHARE:600519", kline)
    assert out["abstain"] is True
    assert "prob_big_move" in out and out["prob_big_move"] is None
    assert "prob_up" not in out


def test_backtest_trustworthy_combines_stability_and_significance():
    fa = _fa()
    stable = [{"total_return": 0.1}, {"total_return": 0.2}]  # 同号 → 稳健
    assert fa._backtest_trustworthy({"sensitivity": stable,
                                     "significance": {"significant": True}}) is True
    assert fa._backtest_trustworthy({"sensitivity": stable,
                                     "significance": {"significant": False}}) is False
    # 显著性不可判(样本不足)时不因显著性降级，仅看稳健性
    assert fa._backtest_trustworthy({"sensitivity": stable,
                                     "significance": {"significant": None}}) is True
