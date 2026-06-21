"""L1 预处理：MAD 去极值 → z-score → 行业+ln市值 中性化（逐截面）。"""
import importlib.util

import numpy as np


def _pp():
    s = importlib.util.spec_from_file_location("pp", "services/mcp-tool-service/preprocess.py")
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


def test_winsorize_clips_outliers():
    pp = _pp()
    w = pp.mad_winsorize([0.0] * 20 + [1000.0])
    assert max(w) < 1000.0 and min(w) >= -1e-6


def test_zscore():
    pp = _pp()
    z = pp.zscore([1, 2, 3, 4, 5])
    assert abs(float(np.mean(z))) < 1e-9 and abs(float(np.std(z)) - 1) < 1e-9
    assert all(v == 0 for v in pp.zscore([7, 7, 7]))  # 常数 → 全 0


def test_neutralize_residual_orthogonal_to_industry_and_size():
    pp = _pp()
    rng = np.random.RandomState(0)
    n = 200
    ind = ["A" if i % 2 else "B" for i in range(n)]
    lnmc = rng.randn(n)
    base = np.array([1.0 if i % 2 else -1.0 for i in range(n)]) + 0.5 * lnmc
    vals = base + 0.1 * rng.randn(n)
    resid = np.array(pp.neutralize(vals, ind, lnmc)["residual"])
    assert abs(np.corrcoef(resid, lnmc)[0, 1]) < 0.1          # 与市值正交
    rA = resid[[i for i in range(n) if ind[i] == "A"]].mean()
    rB = resid[[i for i in range(n) if ind[i] == "B"]].mean()
    assert abs(rA - rB) < 0.1                                  # 与行业正交


def test_neutralize_pure_industry_factor_residual_near_zero():
    pp = _pp()
    n = 100
    ind = ["A" if i < 50 else "B" for i in range(n)]
    lnmc = np.zeros(n)
    vals = np.array([2.0] * 50 + [5.0] * 50)  # 纯行业决定
    out = pp.neutralize(vals, ind, lnmc)
    assert np.allclose(out["residual"], 0.0, atol=1e-6)


def test_winsorize_single_nan_does_not_poison_others():
    pp = _pp()
    w = pp.mad_winsorize([1, 2, 3, 4, float("nan"), 5, 6, 7, 8, 9])
    assert np.isnan(w[4]) and np.isfinite(np.delete(w, 4)).all()


def test_zscore_single_nan_preserves_finite_rows():
    pp = _pp()
    z = pp.zscore([1, 2, 3, 4, float("nan"), 5, 6, 7, 8, 9])
    finite = np.delete(z, 4)
    assert np.isnan(z[4]) and np.isfinite(finite).all()
    assert abs(float(np.mean(finite))) < 1e-9


def test_preprocess_chain_tolerates_one_missing():
    pp = _pp()
    w = pp.mad_winsorize([1, 2, 3, 4, float("nan"), 5, 6, 7, 8, 9])
    out = pp.neutralize(pp.zscore(w), ["A"] * 10, list(range(10)))
    assert out["n_valid"] == 9 and out["data_quality"] == "ok"   # 单缺失不打成全弃权


def test_neutralize_degraded_on_tiny_bucket():
    pp = _pp()
    rng = np.random.RandomState(1)
    ind = ["A"] * 30 + ["RARE"]          # RARE 桶大小 1 < min_bucket
    out = pp.neutralize(list(rng.randn(31)), ind, list(rng.randn(31)))
    assert out["data_quality"] == "degraded" and out["n_valid"] == 31
