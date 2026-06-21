"""L1 zoo 价量因子扩展（≥16 个 history_native，全部从 K线+DSL 可立即计算）。"""
import importlib.util
import sys

import numpy as np

sys.path.insert(0, "services/mcp-tool-service")   # zoo→factor_dsl


def _zoo():
    s = importlib.util.spec_from_file_location("zoo", "services/mcp-tool-service/zoo.py")
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


def _ohlcv(n=300, seed=0):
    rng = np.random.RandomState(seed)
    c = 100 * np.cumprod(1 + 0.012 * rng.randn(n))
    return {"C": c, "O": c * (1 + 0.001 * rng.randn(n)),
            "H": c * (1 + 0.01 * np.abs(rng.randn(n))),
            "L": c * (1 - 0.01 * np.abs(rng.randn(n))),
            "V": 1e6 * (1 + 0.5 * rng.rand(n))}


def test_zoo_has_at_least_16_price_volume_factors():
    zoo = _zoo()
    assert len(zoo.FACTORS) >= 16
    # 覆盖多个家族(不只动量/反转)
    fams = {v["family"] for v in zoo.FACTORS.values()}
    assert len(fams) >= 5


def test_every_factor_computes_finite_and_has_honest_metadata():
    zoo = _zoo()
    data = _ohlcv()
    n = len(data["C"])
    for name, meta in zoo.FACTORS.items():
        v = np.asarray(zoo.compute(name, data), dtype=float)
        assert len(v) == n, f"{name} 长度不符"
        assert np.isfinite(v[-40:]).any(), f"{name} 预热后仍全 NaN"      # 末段有有限值
        assert meta["direction"] in ("+", "-", "risk_gate"), f"{name} 方向非法"
        assert meta["pit_status"] == "history_native", f"{name} 非 history_native"
        assert meta.get("family") and meta.get("desc")


def test_existing_factors_unchanged():
    """既有 4 因子公式/方向不回归（向后兼容）。"""
    zoo = _zoo()
    assert zoo.FACTORS["Mom_12_1"]["formula"] == "Ref(C,21)/Ref(C,252)-1"
    assert zoo.FACTORS["Rev_5"]["direction"] == "+"
    assert zoo.FACTORS["TotalVol"]["direction"] == "-"
    assert zoo.FACTORS["Amihud"]["family"] == "liquidity"
