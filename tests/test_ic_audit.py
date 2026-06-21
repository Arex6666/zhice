"""L6 IC 时序自审：ICIR/子区间一致性/近期漂移 → verdict（纯诊断，不动天花板）。"""
import importlib.util

import numpy as np


def _ia():
    s = importlib.util.spec_from_file_location("ia", "services/mcp-tool-service/ic_audit.py")
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


def test_stable_positive_ic_effective():
    ia = _ia()
    rng = np.random.RandomState(0)
    ics = list(0.06 + 0.01 * rng.randn(60))      # 稳定正 IC
    out = ia.audit(ics)
    assert out["verdict"] in ("有效稳定",) and out["icir"] > 0


def test_decaying_ic_flagged():
    ia = _ia()
    ics = list(np.linspace(0.10, -0.02, 60))      # 持续衰减到负
    out = ia.audit(ics)
    assert out["verdict"] in ("衰减中", "不稳定", "失效")
    assert out["recent_drift"] < 0


def test_insufficient_abstain():
    ia = _ia()
    out = ia.audit([0.05] * 5)
    assert out["verdict"] == "样本不足" and out["abstain_reason"] == "insufficient_history"
