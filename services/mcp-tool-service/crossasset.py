"""跨资产上下文（纯函数，numpy-only）：个股相对指数的 β / 相关 / R² / 相对强弱 / 下行 β。

让"宏观面"委员有实测的市场敏感度证据，而非 LLM 直觉。
"""
import numpy as np


def _returns(closes):
    c = np.asarray(closes, dtype=float)
    return np.diff(c) / c[:-1]


def beta_context(stock_closes, index_closes, window=60):
    """对齐两条收盘价序列(取共同末段)，计算 β/相关/R²/相对强弱/下行 β。"""
    rs = _returns(stock_closes)
    rm = _returns(index_closes)
    n = min(len(rs), len(rm))
    if n < 20:
        return {"beta": None, "reason": "样本不足(<20)", "n": int(n)}
    rs = rs[-min(n, window):]
    rm = rm[-min(n, window):]
    var_m = float(np.var(rm, ddof=1))
    beta = float(np.cov(rs, rm, ddof=1)[0, 1] / var_m) if var_m > 0 else None
    corr = float(np.corrcoef(rs, rm)[0, 1]) if np.std(rm) > 0 and np.std(rs) > 0 else None
    r2 = float(corr ** 2) if corr is not None else None
    rel_strength = float(np.prod(1 + rs) - np.prod(1 + rm))  # 区间累计超额
    down = rm < 0
    if down.sum() >= 5 and float(np.var(rm[down], ddof=1)) > 0:
        downside_beta = float(np.cov(rs[down], rm[down], ddof=1)[0, 1] / np.var(rm[down], ddof=1))
    else:
        downside_beta = None
    return {"beta": round(beta, 3) if beta is not None else None,
            "corr": round(corr, 3) if corr is not None else None,
            "r2": round(r2, 3) if r2 is not None else None,
            "rel_strength": round(rel_strength, 4),
            "downside_beta": round(downside_beta, 3) if downside_beta is not None else None,
            "window": int(len(rs)), "n": int(n)}
