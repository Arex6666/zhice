"""L6 IC 时序自审（纯函数）：ICIR / 子区间一致性 / 近期漂移 → verdict。

纯诊断，**不动置信度天花板**（对齐 seasonality）。低频因子样本不足即"样本不足"，不输出半衰期数字。
"""
import numpy as np


def audit(ic_series, min_n=20, recent_frac=0.25):
    a = np.asarray(ic_series, dtype=float)
    n = len(a)
    if n < min_n:
        return {"verdict": "样本不足", "abstain_reason": "insufficient_history", "n": n}
    mean = float(a.mean())
    sd = float(a.std(ddof=1)) if n > 1 else 0.0
    icir = float(mean / sd) if sd > 0 else 0.0
    half = n // 2
    h1, h2 = a[:half].mean(), a[half:]. mean()
    same_sign = bool(np.sign(h1) == np.sign(h2) and h1 != 0)
    k = max(1, int(n * recent_frac))
    recent_drift = float(a[-k:].mean() - mean)
    if abs(mean) < 0.01:
        verdict = "失效"
    elif not same_sign:
        verdict = "不稳定"
    elif recent_drift < -abs(mean) * 0.5:
        verdict = "衰减中"
    elif abs(icir) >= 0.3:
        verdict = "有效稳定"
    else:
        verdict = "不稳定"
    return {"verdict": verdict, "icir": round(icir, 3), "mean_ic": round(mean, 4),
            "recent_drift": round(recent_drift, 4), "subperiod_consistent": same_sign,
            "abstain_reason": None, "n": n}
