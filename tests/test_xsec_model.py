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
