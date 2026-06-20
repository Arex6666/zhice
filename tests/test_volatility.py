"""波动状态层（EWMA/Parkinson/Garman-Klass + 分位 regime）。"""
import importlib.util

import numpy as np


def _vol():
    s = importlib.util.spec_from_file_location("vol", "services/mcp-tool-service/volatility.py")
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


def test_ewma_vol_basic():
    vol = _vol()
    assert vol.ewma_vol([0.0]) is None              # 样本不足
    v = vol.ewma_vol([0.01, -0.01, 0.02, -0.02] * 10)
    assert v is not None and v > 0


def test_parkinson_and_gk():
    vol = _vol()
    highs = [11, 12, 13]
    lows = [10, 11, 12]
    opens = [10.5, 11.5, 12.5]
    closes = [10.8, 11.8, 12.8]
    assert vol.parkinson(highs, lows) > 0
    assert vol.garman_klass(opens, highs, lows, closes) >= 0


def test_vol_state_extreme_recent():
    vol = _vol()
    rng = np.random.RandomState(0)
    calm = 100 * np.cumprod(1 + 0.002 * rng.randn(120))
    shock = calm[-1] * np.cumprod(1 + 0.06 * rng.randn(20))  # 近期剧烈放大
    closes = list(calm) + list(shock)
    kline = [{"open": c, "high": c * 1.01, "low": c * 0.99, "close": c} for c in closes]
    out = vol.vol_state(kline)
    assert out["regime"] in ("elevated", "extreme")
    assert out["vol_pct"] > 0.8


def test_vol_state_insufficient():
    vol = _vol()
    out = vol.vol_state([{"open": 1, "high": 1, "low": 1, "close": 1}] * 5)
    assert out["regime"] == "unknown"
