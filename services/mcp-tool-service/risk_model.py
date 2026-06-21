"""L4 风险模型（纯函数）：Barra 式 Σ = B·F·B' + D 风险归因。

把组合方差分解为 系统(行业+风格暴露) 与 特质(specific) 两部分，供治理 R11 与诚实披露。
行业/风格暴露依赖 L1 行业映射 + §5.7 风格基底。
"""
import numpy as np


def risk_attribution(weights, B, F, D):
    """weights(N) · B(N×K 因子暴露) · F(K×K 因子协方差) · D(N 特质方差)。

    返回 {total_var, systematic_var, specific_var, factor_exposures, pct_systematic}。
    """
    w = np.asarray(weights, dtype=float)
    B = np.asarray(B, dtype=float)
    F = np.asarray(F, dtype=float)
    D = np.asarray(D, dtype=float)
    expo = B.T @ w                       # 组合因子暴露 (K)
    systematic = float(expo @ F @ expo)
    specific = float(np.sum((w ** 2) * D))
    total = systematic + specific
    return {"total_var": total, "systematic_var": systematic, "specific_var": specific,
            "factor_exposures": [float(x) for x in expo],
            "pct_systematic": round(systematic / total, 4) if total > 0 else None}
