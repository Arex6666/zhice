import importlib.util

import numpy as np


def _ml():
    s = importlib.util.spec_from_file_location("ml", "services/agent-service/ml_signal.py")
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


def test_train_learnable_vs_noise():
    ml = _ml()
    rng = np.random.RandomState(0)
    X = rng.randn(400, 8)
    y = (X[:, 0] + 0.3 * rng.randn(400) > 0).astype(int)  # learnable from feature 0
    met = ml.train(X, y)
    assert met["auc"] > 0.7 and met["abstain"] is False
    assert met["feature_importance"] is not None

    Xr = rng.randn(400, 8)
    yr = rng.randint(0, 2, 400)  # pure noise
    metr = ml.train(Xr, yr)
    assert metr["abstain"] is True  # AUC ~ 0.5


def test_insufficient_samples_abstain():
    ml = _ml()
    X = np.random.randn(50, 8)
    y = np.random.randint(0, 2, 50)
    assert ml.train(X, y)["abstain"] is True


def test_build_features_short():
    ml = _ml()
    assert ml.build_features([{"close": 1.0, "volume": 1}]) is None


def test_calibrator_abstains_without_model():
    ml = _ml()
    c = ml.SignalCalibrator()
    out = c.predict([0.1] * 8)
    assert out["abstain"] is True and out["prob_up"] is None
