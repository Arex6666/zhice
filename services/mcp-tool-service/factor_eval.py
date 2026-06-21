"""L2 因子评估（纯函数）：单因子机构级诊断 —— Rank-IC / ICIR / HAC-t / 分层单调 + 硬判定。

输入为"逐调仓期横截面"：factor_panel/fwd_panel 均为 list（每期一个数组：该期各股因子值/未来收益）。
显著性需 HAC-t 与块自助 p 双满足；样本<20 期弃权（insufficient_history）。复用 backtest 块自助。
"""
import numpy as np
from scipy.stats import spearmanr

import backtest


def ic_series(factor_panel, fwd_panel):
    """逐期 Rank-IC（Spearman）序列；该期有效股<5 跳过。"""
    out = []
    for f, r in zip(factor_panel, fwd_panel):
        f = np.asarray(f, dtype=float)
        r = np.asarray(r, dtype=float)
        m = np.isfinite(f) & np.isfinite(r)
        if m.sum() < 5:
            continue
        rho, _ = spearmanr(f[m], r[m])
        if np.isfinite(rho):
            out.append(float(rho))
    return out


def icir(ics):
    a = np.asarray(ics, dtype=float)
    sd = a.std(ddof=1) if len(a) > 1 else 0.0
    return float(a.mean() / sd) if sd > 0 else 0.0


def ic_hac_t(ics):
    """IC 均值的 Newey-West HAC t 统计量（抗自相关）。

    方差退化(零/近零, 如恒定 IC 序列)→ 返回 None(弃权)，绝不用 1e-12 地板伪装成天文级 t。
    """
    a = np.asarray(ics, dtype=float)
    T = len(a)
    if T < 2:
        return None
    mean = float(a.mean())
    dev = a - mean
    g0 = float(np.mean(dev * dev))
    if g0 <= 1e-10 * max(1.0, mean * mean):   # 相对阈值：方差退化 → 弃权
        return None
    L = int(np.floor(4 * (T / 100) ** (2 / 9)))
    s = g0
    for l in range(1, L + 1):
        s += 2 * (1 - l / (L + 1)) * float(np.mean(dev[l:] * dev[:-l]))
    if s <= 0:
        return None
    return float(mean / np.sqrt(s / T))


def quantile_monotonicity(factor_panel, fwd_panel, n_q=5):
    """分层(Q1..Qn)各层平均未来收益对层序号的 Spearman；接近 ±1 = 单调。"""
    sums = np.zeros(n_q)
    cnt = np.zeros(n_q)
    for f, r in zip(factor_panel, fwd_panel):
        f = np.asarray(f, dtype=float)
        r = np.asarray(r, dtype=float)
        m = np.isfinite(f) & np.isfinite(r)
        if m.sum() < n_q:
            continue
        fv, rv = f[m], r[m]
        ranks = np.argsort(np.argsort(fv))
        q = (ranks * n_q // len(ranks)).clip(0, n_q - 1)
        for qi in range(n_q):
            sel = q == qi
            if sel.any():
                sums[qi] += rv[sel].mean()
                cnt[qi] += 1
    valid = cnt > 0
    if valid.sum() < 2:
        return 0.0
    qm = sums[valid] / cnt[valid]
    rho, _ = spearmanr(np.arange(n_q)[valid], qm)
    return float(rho) if np.isfinite(rho) else 0.0


def build_factor_panels(klines_by_symbol, factor_name):
    """把"逐标的 K 线"转为 factor_report 所需的"逐调仓期横截面"(factor_panel, fwd_panel)。

    每标的经 zoo 算因子序列 + 次日收益, 按时间对齐成截面。离线批(L2)的输入构造。
    """
    import zoo
    facs, fwds = {}, {}
    for sym, kl in (klines_by_symbol or {}).items():
        if not kl:
            continue
        data = {"C": [r["close"] for r in kl], "O": [r.get("open", r["close"]) for r in kl],
                "H": [r.get("high", r["close"]) for r in kl], "L": [r.get("low", r["close"]) for r in kl],
                "V": [r.get("volume", 0) for r in kl]}
        facs[sym] = np.asarray(zoo.compute(factor_name, data), dtype=float)
        c = np.asarray(data["C"], dtype=float)
        fwds[sym] = np.append(np.diff(c) / c[:-1], np.nan)   # 次日收益(末位 NaN)
    syms = list(facs.keys())
    if not syms:
        return [], []
    T = min(len(facs[s]) for s in syms)
    fp = [[float(facs[s][t]) for s in syms] for t in range(T)]
    wp = [[float(fwds[s][t]) for s in syms] for t in range(T)]
    return fp, wp


def factor_report(factor_panel, fwd_panel, n_quantiles=5, alpha=0.05, min_dates=20):
    """单因子诊断汇总 + 显著性硬判定。<min_dates 期 → 弃权。"""
    ics = ic_series(factor_panel, fwd_panel)
    if len(ics) < min_dates:
        return {"mean_rank_ic": round(float(np.mean(ics)), 4) if ics else None,
                "icir": None, "ic_t_hac": None, "ic_block_boot_p": None,
                "monotonic_spearman": None, "significant": None,
                "abstain_reason": "insufficient_history", "n_dates": len(ics)}
    mic = float(np.mean(ics))
    t = ic_hac_t(ics)
    if t is None:   # IC 方差退化(每期同截面等) → 弃权, 不盖章显著
        return {"mean_rank_ic": round(mic, 4), "icir": None, "ic_t_hac": None,
                "ic_block_boot_p": None, "monotonic_spearman": None, "significant": None,
                "abstain_reason": "statistical_abstain", "n_dates": len(ics)}
    boot = backtest.bootstrap_significance(ics)
    p = boot.get("p_value")
    if p is None:   # 块自助样本不足(<20) → 无法判定 → 弃权(非伪装成 0)
        return {"mean_rank_ic": round(mic, 4), "icir": round(icir(ics), 4),
                "ic_t_hac": round(t, 3), "ic_block_boot_p": None,
                "monotonic_spearman": None, "significant": None,
                "abstain_reason": "insufficient_history", "n_dates": len(ics)}
    mono = quantile_monotonicity(factor_panel, fwd_panel, n_quantiles)
    sig = 1 if (abs(t) >= 2.0 and p < alpha) else 0
    return {"mean_rank_ic": round(mic, 4), "icir": round(icir(ics), 4),
            "ic_t_hac": round(t, 3), "ic_block_boot_p": p,
            "monotonic_spearman": round(mono, 3), "significant": sig,
            "abstain_reason": None, "n_dates": len(ics)}
