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
    out = c.predict([0.1] * 10)
    assert out["abstain"] is True and out["prob_big_move"] is None


def test_walk_forward_auc_learnable_with_groups():
    ml = _ml()
    rng = np.random.RandomState(0)
    X = rng.randn(600, 8)
    y = (X[:, 0] + 0.3 * rng.randn(600) > 0).astype(int)
    groups = np.array([0] * 300 + [1] * 300)
    wf = ml.walk_forward_auc(X, y, groups)
    assert wf["auc"] > 0.7 and wf["n_oos"] > 0
    assert len(wf["fold_aucs"]) >= 1


def test_train_uses_walk_forward_and_groups():
    ml = _ml()
    rng = np.random.RandomState(1)
    X = rng.randn(600, 8)
    y = (X[:, 0] + 0.3 * rng.randn(600) > 0).astype(int)
    groups = np.array([0] * 300 + [1] * 300)
    met = ml.train(X, y, groups)
    assert met["abstain"] is False
    assert "fold_aucs" in met and met["prob_quantiles"] is not None


def test_permutation_null_auc_centered_half():
    ml = _ml()
    rng = np.random.RandomState(2)
    X = rng.randn(300, 8)
    y = (X[:, 0] + 0.3 * rng.randn(300) > 0).astype(int)
    out = ml.permutation_null_auc(X, y, n_perm=12)
    # 打乱标签后 AUC 应聚集在 0.5 附近（无信息）
    assert 0.40 <= out["null_mean"] <= 0.60
    assert out["n_perm"] == 12


def test_train_persists_prob_quantiles():
    ml = _ml()
    rng = np.random.RandomState(0)
    X = rng.randn(400, 8)
    y = (X[:, 0] + 0.3 * rng.randn(400) > 0).astype(int)
    met = ml.train(X, y)
    assert met["abstain"] is False
    q = met["prob_quantiles"]
    assert 0.0 <= q["q_elevated"] <= q["q_extreme"] <= 1.0


class _FakeModel:
    def predict_proba(self, X):
        return [[0.55, 0.45]]


def test_predict_includes_quantiles():
    ml = _ml()
    c = ml.SignalCalibrator(model=_FakeModel(), auc=0.6, abstain=False, importance=None,
                            quantiles={"q_elevated": 0.40, "q_extreme": 0.45})
    out = c.predict([0.1] * 10)
    assert out["prob_big_move"] == 0.45
    assert out["q_elevated"] == 0.40 and out["q_extreme"] == 0.45
