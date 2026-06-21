"""L3 因子合成（线性基线，纯函数，无 pickle）。spec §4 L3 + §7.1。

默认线性合成：把通过 L2 闸门的单因子合成为横截面单一打分。
  - equal_weight_combine: 按方向(+原值,-取负)等权平均，NaN 安全(nanmean)。
  - ic_weighted_combine:  w_j ∝ max(0, 方向校正后滚动 mean RankIC)（仅历史），归一；
                          全 ≤0 → 回退等权 fallback。

诚实约束：
  - 输入为已取好的横截面 clean 值（依赖注入，无网络、无 akshare、无 pickle）。
  - 某股在所有因子上全缺 → 该股得分 NaN（绝不编造 0）。
  - 形状不一致 / 空输入 → 弃权（返回空 scores），不崩溃。

返回结构统一：{'scores':[...], 'weights':{factor:w}, 'method':str, 'fallback':bool}

ML 合成(xsec_model)在 agent-service(py3.12)，仅在 purged-CV OOS 优于本线性基线时
接管，否则回退此基线（promote-then-prove，§7.1）。
"""
import numpy as np

EQUAL_WEIGHT = "equal_weight"
IC_WEIGHTED = "ic_weighted"


def _abstain(method, fallback=False):
    """空 / 形状不一致：弃权返回，不崩。"""
    return {"scores": [], "weights": {}, "method": method, "fallback": fallback}


def _stack(clean_by_factor, directions):
    """把 {factor: 值数组} 按方向校正后堆成 (n_factor, n_stock) 矩阵。

    方向 '-' 取负，其余('+'/缺省) 取原值。形状不一致或空 → 返回 None（弃权信号）。
    返回 (names, M) ；M 为 float ndarray，缺失为 np.nan。
    """
    if not clean_by_factor:
        return None
    directions = directions or {}
    names = list(clean_by_factor.keys())
    rows = []
    n_stock = None
    for f in names:
        v = np.asarray(clean_by_factor[f], dtype=float).ravel()
        if n_stock is None:
            n_stock = v.shape[0]
        elif v.shape[0] != n_stock:
            return None  # 形状不一致 → 弃权
        if directions.get(f) == "-":
            v = -v
        rows.append(v)
    if n_stock == 0:
        return None
    return names, np.vstack(rows)


def _nan_weighted_scores(M, w):
    """按权重向量 w 对 (n_factor, n_stock) 矩阵做 NaN 安全加权平均。

    逐股仅用该股非缺的因子，权重在存活因子上重新归一；某股全缺 → NaN。
    w 已是非负且和为 1 的等长向量。
    """
    n_factor, n_stock = M.shape
    w = np.asarray(w, dtype=float).reshape(n_factor, 1)
    valid = ~np.isnan(M)
    contrib = np.where(valid, M, 0.0) * w  # 缺失贡献 0
    num = contrib.sum(axis=0)
    den = (valid * w).sum(axis=0)  # 该股存活因子的权重和
    with np.errstate(invalid="ignore", divide="ignore"):
        scores = np.where(den > 0, num / den, np.nan)
    return scores


def _to_list(scores):
    return [float(x) for x in scores]


def equal_weight_combine(clean_by_factor, directions=None):
    """等权合成（按方向）。NaN 安全：逐股 nanmean，全缺 → NaN。

    clean_by_factor: {factor_name: 横截面 clean 值数组}
    directions:      {factor_name: '+'|'-'}，缺省视为 '+'
    """
    stacked = _stack(clean_by_factor, directions)
    if stacked is None:
        return _abstain(EQUAL_WEIGHT)
    names, M = stacked
    n_factor = M.shape[0]
    eq = 1.0 / n_factor
    weights = {f: eq for f in names}
    scores = _nan_weighted_scores(M, np.full(n_factor, eq))
    return {
        "scores": _to_list(scores),
        "weights": weights,
        "method": EQUAL_WEIGHT,
        "fallback": False,
    }


def ic_weighted_combine(clean_by_factor, rolling_ic=None, directions=None):
    """IC 加权合成。w_j ∝ max(0, 方向校正后滚动 mean RankIC)（仅历史），归一。

    方向校正：direction '-' 的因子，其滚动 IC 取负（与取负后的因子值口径一致）。
    全部因子方向校正后 RankIC <= 0（或 rolling_ic 缺失）→ 无正贡献历史可加权
    → 回退等权（fallback=True，method='equal_weight'）。NaN 安全同等权。
    """
    stacked = _stack(clean_by_factor, directions)
    if stacked is None:
        return _abstain(IC_WEIGHTED)
    names, M = stacked
    directions = directions or {}
    rolling_ic = rolling_ic or {}

    raw = []
    for f in names:
        ic = rolling_ic.get(f)
        if ic is None or (isinstance(ic, float) and np.isnan(ic)):
            ic = 0.0
        ic = float(ic)
        if directions.get(f) == "-":
            ic = -ic  # 方向校正：与取负后的因子值同口径
        raw.append(max(0.0, ic))
    raw = np.asarray(raw, dtype=float)
    total = raw.sum()

    if total <= 0.0:
        # 全 ≤0 → 回退等权
        eq = equal_weight_combine(clean_by_factor, directions)
        eq["fallback"] = True
        return eq

    w = raw / total
    weights = {f: float(wi) for f, wi in zip(names, w)}
    scores = _nan_weighted_scores(M, w)
    return {
        "scores": _to_list(scores),
        "weights": weights,
        "method": IC_WEIGHTED,
        "fallback": False,
    }


# --------------------------------------------------------------------------
# 向后兼容：早期 mcp_server 注册的轻量 combine()（等权/IC 加权，返回纯数组）。
# 新代码请用 equal_weight_combine / ic_weighted_combine（带 weights/method/fallback）。
# --------------------------------------------------------------------------
def combine(panel, directions=None, ic_weights=None):
    """legacy：返回合成打分数组（不带元数据）。保留以免破坏既有注册。"""
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
