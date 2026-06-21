"""L3 离线训练核心 train_xsec（依赖注入，脱网可测）。"""
import importlib.util

import numpy as np


def _tx():
    s = importlib.util.spec_from_file_location("tx", "scripts/train_xsec.py")
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


def _panels(seed=0, T=60, N=20):
    rng = np.random.RandomState(seed)
    panels = {}
    for t in range(T):
        mom = rng.randn(N)
        fwd = 1.5 * mom + 0.1 * rng.randn(N)   # mom 预测 fwd
        panels[t] = {"factors": {"Mom": list(mom), "Rev": list(rng.randn(N))}, "fwd": list(fwd)}
    return panels


def test_build_matrix_pools_finite_rows():
    tx = _tx()
    panels = {0: {"factors": {"Mom": [1.0, np.nan, 3.0], "Rev": [0.1, 0.2, 0.3]},
                  "fwd": [0.01, 0.02, np.nan]}}
    X, y = tx.build_training_matrix(panels, ["Mom", "Rev"])
    assert X.shape == (1, 2) and len(y) == 1     # 仅第 0 行全有限


def test_train_fits_when_enough_samples():
    tx = _tx()
    out = tx.train_xsec(_panels(), ["Mom", "Rev"], n_estimators=40, max_depth=3)
    assert out["model"] is not None and out["n_samples"] >= 200
    # 学到 Mom 方向
    pred = np.asarray(out["model"].predict_scores({"Mom": [2, -2, 0], "Rev": [0, 0, 0]}))
    assert pred[0] > pred[1]


def test_train_abstains_on_insufficient():
    tx = _tx()
    out = tx.train_xsec(_panels(T=3, N=5), ["Mom", "Rev"])
    assert out["model"] is None and out["abstain_reason"] == "insufficient_history"
