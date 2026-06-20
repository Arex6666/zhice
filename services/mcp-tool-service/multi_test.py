"""多重检验与去膨胀（纯函数）：BH-FDR / Bonferroni / Harvey 门槛 / Deflated Sharpe。

因子动物园 + 设计选择网格构成大量"试验"，单一 t>2 必然挖出假因子。本模块提供机构级
多重检验纪律。DSR 的 Var(SR_trials) 与 n_trials 同源口径见 spec §7.2。
"""
import math

import numpy as np
from scipy.stats import norm

EULER = 0.5772156649015329  # Euler-Mascheroni


def bh(pvals):
    """Benjamini-Hochberg step-up，返回与输入同序的校正后 p 值列表。

    与 seasonality 原内联实现逐位相等（回归守护）。
    """
    pv = [float(p) for p in pvals]
    m = len(pv)
    if m == 0:
        return []
    order = sorted(range(m), key=lambda i: pv[i])  # 升序
    adj = [0.0] * m
    running = 1.0
    for rank in range(m - 1, -1, -1):
        i = order[rank]
        running = min(running, pv[i] * m / (rank + 1))
        adj[i] = min(1.0, running)
    return adj


def bonferroni(pvals):
    """Bonferroni 校正：min(1, p·m)，同序返回。"""
    m = len(pvals)
    return [min(1.0, float(p) * m) for p in pvals]


def harvey_passed(t_stat, threshold=3.0):
    """Harvey-Liu-Zhu 新因子门槛：|t| ≥ 3.0（而非 2.0）。"""
    try:
        return abs(float(t_stat)) >= threshold
    except (TypeError, ValueError):
        return False


def deflated_sharpe(sr, n_trials, var_sr_trials=None, var_source="auto",
                    skew=0.0, kurt=3.0, n_obs=252):
    """Deflated Sharpe Ratio（Bailey-López de Prado 2014）。

    SR0 = √Var(SR_trials)·[(1-γ)·Φ⁻¹(1−1/N) + γ·Φ⁻¹(1−1/(N·e))]
    DSR = Φ( (SR_obs−SR0)·√(T−1) / √(1 − skew·SR + (kurt−1)/4·SR²) )

    §7.2 口径：var_sr_trials 给定 → var_source='grid_distribution'；
    否则解析回退 Var≈1/T → var_source='analytic_1overT'。N=1 时 SR0=0（退化 PSR）。
    """
    sr = float(sr)
    N = max(1, int(n_trials))
    T = max(2, int(n_obs))
    if var_sr_trials is not None:
        v = float(var_sr_trials)
        src = "grid_distribution"
    else:
        v = 1.0 / T
        src = "analytic_1overT"
    if N <= 1:
        sr0 = 0.0
    else:
        z1 = float(norm.ppf(1 - 1.0 / N))
        z2 = float(norm.ppf(1 - 1.0 / (N * math.e)))
        sr0 = math.sqrt(max(0.0, v)) * ((1 - EULER) * z1 + EULER * z2)
    denom = math.sqrt(max(1e-12, 1 - skew * sr + (kurt - 1) / 4.0 * sr * sr))
    dsr = float(norm.cdf((sr - sr0) * math.sqrt(T - 1) / denom))
    return {"dsr": round(dsr, 4), "sr0": round(sr0, 4), "var_sr_trials": v,
            "var_source": src, "n_trials": N, "n_obs": T}
