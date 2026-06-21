"""A股风格因子基底（纯函数，numpy）：MKT / SMB / VMG（Liu-Stambaugh-Yuan 2019）+ 残差化。

用途：L3/L7 闸门"控制已知风格后仍有增量 IC"的残差化底座，以及 Barra 风格暴露。
LSY 在剔最小 30% 市值样本上构造（去壳价值污染）。风格收益的做空腿是统计构造、不进可实现组合。
冷启动 history_depth<252 时整体弃权（依赖它的增量 IC 判据随之 abstain），诚实优先。
"""
import numpy as np

MIN_HISTORY = 252


def _drop_small(cap, frac=0.3):
    """返回保留掩码：剔除最小 frac 市值（LSY 去壳）。"""
    cap = np.asarray(cap, dtype=float)
    if len(cap) == 0:
        return np.zeros(0, dtype=bool)
    thr = np.quantile(cap, frac)
    return cap >= thr  # 剔最小 frac；市值相等(退化)时保留全部


def mkt(rets, cap, rf=0.0):
    """市值加权市场超额收益。停牌(NaN)收益剔除并在有效子集上**重归一权重**(非当 0 计入)；全 NaN 返回 NaN。"""
    rets = np.asarray(rets, dtype=float)
    cap = np.asarray(cap, dtype=float)
    m = np.isfinite(rets)
    if not m.any():
        return float("nan")
    c = cap[m]
    w = c / c.sum() if c.sum() else np.full(int(m.sum()), 1.0 / int(m.sum()))
    return float((w * rets[m]).sum() - rf)


def smb(rets, cap, drop_small_frac=0.3):
    """小市值组 − 大市值组（剔最小 30% 后按中位二分，组内市值加权）。中位并列致一腿为空→弃权 0。"""
    rets = np.asarray(rets, dtype=float)
    cap = np.asarray(cap, dtype=float)
    keep = _drop_small(cap, drop_small_frac)
    r, c = rets[keep], cap[keep]
    if len(c) < 4:
        return 0.0
    med = np.median(c)
    small, big = c <= med, c > med
    if not small.any() or not big.any():
        return 0.0
    return float(_cap_w(r[small], c[small]) - _cap_w(r[big], c[big]))


def vmg(rets, ep, cap, drop_small_frac=0.3):
    """高EP(价值) − 低EP(成长)（剔最小30%后按 EP 中位二分）。中位并列致一腿为空→弃权 0。"""
    rets = np.asarray(rets, dtype=float)
    ep = np.asarray(ep, dtype=float)
    cap = np.asarray(cap, dtype=float)
    keep = _drop_small(cap, drop_small_frac)
    r, e, c = rets[keep], ep[keep], cap[keep]
    if len(e) < 4:
        return 0.0
    med = np.median(e)
    high, low = e >= med, e < med
    if not high.any() or not low.any():
        return 0.0
    return float(_cap_w(r[high], c[high]) - _cap_w(r[low], c[low]))


def _cap_w(r, c):
    """组内市值加权收益；停牌 NaN 剔除并在有效子集重归一。"""
    r = np.asarray(r, dtype=float)
    c = np.asarray(c, dtype=float)
    m = np.isfinite(r)
    if not m.any():
        return 0.0
    cc, rr = c[m], r[m]
    s = cc.sum()
    return float(((cc / s) * rr).sum()) if s else float(rr.mean())


def residualize(y, style_matrix):
    """对风格矩阵 [MKT,SMB,VMG] OLS 取残差（剥离已知风格暴露）。"""
    y = np.asarray(y, dtype=float)
    X = np.asarray(style_matrix, dtype=float)
    X = np.column_stack([np.ones(len(y)), X])  # 含截距
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    return y - X @ beta


def build_style_series(cross_sections):
    """cross_sections: list[每期 dict(rets, cap, ep)] → MKT/SMB/VMG 时序；不足 252 期弃权。"""
    if len(cross_sections) < MIN_HISTORY:
        return {"abstain": True, "abstain_reason": "insufficient_history",
                "n_periods": len(cross_sections)}
    mkt_s, smb_s, vmg_s = [], [], []
    for cs in cross_sections:
        mkt_s.append(mkt(cs["rets"], cs["cap"], cs.get("rf", 0.0)))
        smb_s.append(smb(cs["rets"], cs["cap"]))
        vmg_s.append(vmg(cs["rets"], cs["ep"], cs["cap"]))
    return {"abstain": False, "MKT": mkt_s, "SMB": smb_s, "VMG": vmg_s,
            "n_periods": len(cross_sections)}
