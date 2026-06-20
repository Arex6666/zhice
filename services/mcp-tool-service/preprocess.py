"""因子预处理（纯函数，逐截面 Fama-MacBeth 风格）：MAD 去极值 → z-score → 中性化。

中性化 = 对 [申万一级行业哑变量 + ln市值] 做 OLS 取残差，剥离行业与规模暴露。
**仅用当日横截面统计量**，绝不跨期池化（防泄漏）。numpy-only。
"""
from collections import Counter

import numpy as np

_MAD_C = 1.4826  # MAD → 稳健标准差


def mad_winsorize(x, k=3.0):
    """按 median ± k·(1.4826·MAD) 截尾；MAD=0(过半相同)时退回标准差尺度；std 也为 0 才原样返回。"""
    a = np.asarray(x, dtype=float)
    med = np.median(a)
    sigma = _MAD_C * np.median(np.abs(a - med))
    if sigma == 0:
        sigma = float(np.std(a))
        if sigma == 0:
            return a.copy()
    return np.clip(a, med - k * sigma, med + k * sigma)


def zscore(x):
    """横截面 z-score；常数序列返回全 0。"""
    a = np.asarray(x, dtype=float)
    sd = a.std(ddof=0)
    if sd == 0:
        return np.zeros_like(a)
    return (a - a.mean()) / sd


def neutralize(values, industries, ln_mktcap, min_bucket=5):
    """对 [行业哑变量 + ln市值] OLS 取残差。小行业桶(<min_bucket)合并为 OTHER 并标 degraded。

    返回 {residual: list(原长, 无效位 NaN), data_quality: ok|degraded, n_valid: int}。
    """
    y = np.asarray(values, dtype=float)
    lnmc = np.asarray(ln_mktcap, dtype=float)
    ind = list(industries)
    n = len(y)
    mask = np.isfinite(y) & np.isfinite(lnmc)
    cnt = Counter(ind[i] for i in range(n) if mask[i])
    degraded = any(c < min_bucket for c in cnt.values())
    eff = [ind[i] if cnt.get(ind[i], 0) >= min_bucket else "OTHER" for i in range(n)]
    rows = np.where(mask)[0]
    resid = np.full(n, np.nan)
    if len(rows) < 3:
        return {"residual": [float(v) for v in resid], "data_quality": "degraded",
                "n_valid": int(len(rows))}
    cats = sorted({eff[i] for i in rows})
    cols = [np.ones(len(rows))]                       # 截距
    for c in cats[1:]:                                # 去一列哑变量防共线
        cols.append(np.array([1.0 if eff[i] == c else 0.0 for i in rows]))
    cols.append(lnmc[rows])                           # ln市值
    X = np.column_stack(cols)
    beta, *_ = np.linalg.lstsq(X, y[rows], rcond=None)
    resid[rows] = y[rows] - X @ beta
    return {"residual": [float(v) for v in resid],
            "data_quality": "degraded" if degraded else "ok", "n_valid": int(len(rows))}
