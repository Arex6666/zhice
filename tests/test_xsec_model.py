"""L3 横截面 ML 诚实层：promote-then-prove 闸门 + 工件版本契约（agent-service py3.12）。"""
import importlib.util

import numpy as np


def _xm():
    s = importlib.util.spec_from_file_location("xm", "services/agent-service/xsec_model.py")
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


def test_promote_gate_enables_when_ml_strictly_better():
    xm = _xm()
    rng = np.random.RandomState(0)
    base = list(0.02 + 0.004 * rng.randn(40))
    ml = list(0.05 + 0.004 * rng.randn(40))            # 一致更优
    out = xm.promote_then_prove(ml, base)
    assert out["enable_ml"] is True and out["ci_low"] > 0


def test_promote_gate_abstains_when_not_better():
    xm = _xm()
    rng = np.random.RandomState(1)
    base = list(0.03 + 0.01 * rng.randn(40))
    ml = list(0.03 + 0.01 * rng.randn(40))             # 无增益
    out = xm.promote_then_prove(ml, base)
    assert out["enable_ml"] is False and out["abstain_reason"] == "statistical_abstain"


def test_promote_gate_insufficient_history():
    xm = _xm()
    out = xm.promote_then_prove([0.1, 0.2], [0.05, 0.1])
    assert out["enable_ml"] is False and out["abstain_reason"] == "insufficient_history"


def test_artifact_meta_and_contract():
    xm = _xm()
    meta = xm.artifact_meta()
    assert "python_version" in meta and "sklearn_version" in meta and "numpy_version" in meta
    assert xm.check_artifact(meta)["ok"] is True                 # 自身一致
    chk = xm.check_artifact({**meta, "python_version": "2.7"})
    assert chk["ok"] is False and chk["abstain_reason"] == "model_load_failed"


# ---- L3 GBDT 横截面排序器 + 工件契约 round-trip ----
def test_ranker_learns_monotone_signal():
    """合成 y≈2·f0：训练后预测分应与 f0 强正相关（确实学到方向）。"""
    xm = _xm()
    rng = np.random.RandomState(0)
    X = rng.randn(400, 3)
    y = 2 * X[:, 0] + 0.1 * rng.randn(400)
    r = xm.XSecRanker(n_estimators=60, max_depth=3)
    r.fit(X, y, feature_names=["f0", "f1", "f2"])
    pred = np.asarray(r.predict(X))
    assert np.corrcoef(pred, X[:, 0])[0, 1] > 0.7


def test_save_load_roundtrip_predicts_identically(tmp_path):
    """存→读回(同环境) 预测逐点一致；sidecar artifact_meta.json 落盘。"""
    import os
    xm = _xm()
    rng = np.random.RandomState(1)
    X = rng.randn(200, 2)
    y = X[:, 1] + 0.1 * rng.randn(200)
    r = xm.XSecRanker(n_estimators=40, max_depth=3)
    r.fit(X, y, feature_names=["a", "b"])
    p = str(tmp_path / "xsec.pkl")
    r.save(p)
    assert os.path.exists(p + ".meta.json")
    r2 = xm.XSecRanker.load(p)
    assert np.allclose(np.asarray(r.predict(X)), np.asarray(r2.predict(X)))


def test_load_rejects_env_mismatch(tmp_path):
    """跨容器/跨版本：加载侧与 sidecar 不一致 → model_load_failed（不静默降级）。"""
    import pytest
    xm = _xm()
    rng = np.random.RandomState(2)
    X = rng.randn(120, 2)
    r = xm.XSecRanker(n_estimators=20, max_depth=2)
    r.fit(X, X[:, 0], feature_names=["a", "b"])
    p = str(tmp_path / "m.pkl")
    r.save(p)
    bad = {"python_version": "2.7", "sklearn_version": "0.0", "numpy_version": "0.0"}
    with pytest.raises(xm.ArtifactContractError):
        xm.XSecRanker.load(p, current_env=bad)
    out = xm.load_or_abstain(p, current_env=bad)
    assert out["model"] is None and out["abstain_reason"] == "model_load_failed"


def test_predict_scores_from_factor_dict():
    """xsec_rank 用：按 feature_names 从 clean 因子 dict 组装 X 预测；缺因子列→弃权(None)。"""
    xm = _xm()
    rng = np.random.RandomState(3)
    X = rng.randn(150, 2)
    r = xm.XSecRanker(n_estimators=30, max_depth=3)
    r.fit(X, X[:, 0], feature_names=["mom", "val"])
    scores = r.predict_scores({"mom": list(X[:, 0]), "val": list(X[:, 1])})
    assert len(scores) == 150
    assert r.predict_scores({"mom": [1, 2, 3]}) is None
