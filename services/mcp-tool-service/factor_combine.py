"""L3 因子合成（线性基线，纯函数，无 pickle）。

默认线性合成：按方向（+/-）取向后等权或 IC 加权。ML 合成(xsec_model)在 agent-service(py3.12)，
仅在 purged-CV OOS 优于本线性基线时接管，否则回退此基线（promote-then-prove）。
"""
import numpy as np


def combine(panel, directions=None, ic_weights=None):
    """panel: {factor_name: clean值数组(同一截面各股)}。返回合成打分数组。

    directions[f] ∈ {'+','-'}：'-' 取负后参与。ic_weights[f]：IC 加权（默认等权）。
    """
    if not panel:
        return []
    names = list(panel.keys())
    directions = directions or {}
    n_stocks = len(next(iter(panel.values())))
    score = np.zeros(n_stocks, dtype=float)
    wsum = 0.0
    for f in names:
        v = np.asarray(panel[f], dtype=float)
        if directions.get(f) == "-":
            v = -v
        w = float(ic_weights[f]) if (ic_weights and f in ic_weights) else 1.0
        score += w * v
        wsum += abs(w)
    return [float(x) for x in (score / wsum)] if wsum else [0.0] * n_stocks
