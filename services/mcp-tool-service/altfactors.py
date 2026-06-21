"""L1 另类/风险因子（纯函数，forward_pit_only）。

北向持股、EPS 修正、PEAD、股东户数等无多年历史 → 冷启动 history_depth<252 强制弃权
（with_pit_guard）。绝不用今日快照回填历史。EPS 修正按 Jung(2019) **不缩放/滞后均值缩放**，
绝不除当期 EPS/股价。主力资金流默认弃权（东财口径黑箱）。
"""
import numpy as np

MIN_HISTORY = 252


def northbound_flow(hold_ratio, lag=20):
    """北向持股比变化：hold_ratio_t − Ref(hold_ratio, lag)。"""
    h = np.asarray(hold_ratio, dtype=float)
    out = np.full(len(h), np.nan)
    if lag < len(h):
        out[lag:] = h[lag:] - h[:len(h) - lag]
    return out


def chip(holder_counts):
    """筹码集中：−Δln(股东户数)（户数下降→正）。"""
    c = np.asarray(holder_counts, dtype=float)
    out = np.full(len(c), np.nan)
    if len(c) >= 2:
        ln = np.log(c)
        out[1:] = -(ln[1:] - ln[:-1])
    return out


def eps_revision(eps_now, eps_1m_ago, eps_3m_mean):
    """EPS 修正(未缩放/滞后均值缩放, Jung 2019)：(EPS_t − EPS_{t-1m}) / |EPS 近3月均值|。"""
    denom = abs(float(eps_3m_mean))
    if denom < 1e-9:
        return None
    return (float(eps_now) - float(eps_1m_ago)) / denom


def with_pit_guard(values, history_depth_days, min_history=MIN_HISTORY):
    """冷启动守门：forward_pit_only 因子历史深度<min_history → 弃权(insufficient_history)。"""
    if history_depth_days < min_history:
        return {"abstain": True, "abstain_reason": "insufficient_history",
                "history_depth_days": history_depth_days, "values": None}
    return {"abstain": False, "abstain_reason": None,
            "history_depth_days": history_depth_days, "values": list(values)}
