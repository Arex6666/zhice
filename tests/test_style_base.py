"""L1 A股风格因子基底：MKT/SMB/VMG（LSY 2019）+ 残差化（控制已知风格）。"""
import importlib.util

import numpy as np


def _sb():
    s = importlib.util.spec_from_file_location("sb", "services/mcp-tool-service/style_base.py")
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


def test_mkt_cap_weighted_excess():
    sb = _sb()
    rets = np.array([0.10, 0.00])
    cap = np.array([1.0, 9.0])          # 大权重在 0.00
    assert abs(sb.mkt(rets, cap, rf=0.0) - 0.01) < 1e-9   # 0.1*0.1 + 0*0.9


def test_smb_small_minus_big():
    sb = _sb()
    n = 100
    cap = np.arange(1, n + 1, dtype=float)
    rets = np.where(cap <= np.median(cap), 0.02, -0.01)   # 小市值高收益
    assert sb.smb(rets, cap) > 0


def test_vmg_value_minus_growth():
    sb = _sb()
    n = 100
    ep = np.arange(1, n + 1, dtype=float)
    cap = np.full(n, 50.0)
    rets = np.where(ep >= np.median(ep), 0.02, -0.01)     # 高EP(价值)高收益
    assert sb.vmg(rets, ep, cap) > 0


def test_residualize_removes_style_exposure():
    sb = _sb()
    rng = np.random.RandomState(0)
    T = 200
    mkt = rng.randn(T)
    style = np.column_stack([mkt, rng.randn(T), rng.randn(T)])
    y = 2.0 * mkt + 0.1 * rng.randn(T)                    # y 主要由 MKT 驱动
    resid = sb.residualize(y, style)
    assert abs(np.corrcoef(resid, mkt)[0, 1]) < 0.1       # 残差与 MKT 正交


def test_insufficient_history_abstain():
    sb = _sb()
    out = sb.build_style_series([])                       # 无截面
    assert out["abstain"] is True and out["abstain_reason"] == "insufficient_history"
