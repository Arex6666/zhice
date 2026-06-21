"""L7 AlphaEval（无回测因子初筛，纯函数）—— 系统作"证伪机"。

对 LLM 生成的候选因子做廉价五维初筛，先杀掉明显无效者再进昂贵的 purged-CV/回测：
- PPS 预测力 = 0.5·Pearson-IC + 0.5·Rank-IC
- PFS 扰动稳定性 = 加噪后排序的最差 Spearman（高斯/厚尾 t 两种噪声取 min）
- DH 多样性熵 = 因子库相关阵特征值归一化熵（与库内已有因子越正交越高）
不含未来函数；financial_logic/RRE 等软维度由 LLM 仅作展示，不进硬判据。
"""
import numpy as np
from scipy.stats import pearsonr, spearmanr


def _finite_pair(a, b):
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    m = np.isfinite(a) & np.isfinite(b)
    return a[m], b[m]


def pps(factor, fwd_return):
    """预测力评分 = 0.5·IC + 0.5·RankIC。"""
    f, r = _finite_pair(factor, fwd_return)
    if len(f) < 5 or np.std(f) == 0 or np.std(r) == 0:
        return 0.0
    return float(0.5 * pearsonr(f, r)[0] + 0.5 * spearmanr(f, r)[0])


def pfs(factor, noise_scale=0.01, seed=42):
    """扰动稳定性：加小噪后秩相关，高斯与厚尾 t(ν=3) 取较差者。"""
    f = np.asarray(factor, dtype=float)
    f = f[np.isfinite(f)]
    if len(f) < 5 or np.std(f) == 0:
        return 0.0
    rng = np.random.RandomState(seed)
    sd = noise_scale * np.std(f)
    s_g = spearmanr(f, f + sd * rng.randn(len(f)))[0]
    s_t = spearmanr(f, f + sd * rng.standard_t(3, len(f)))[0]
    return float(min(s_g, s_t))


def diversity_entropy(library_matrix):
    """因子库相关阵特征值归一化熵 ∈[0,1]；与已有因子越正交越接近 1，越冗余越接近 0。"""
    X = np.asarray(library_matrix, dtype=float)
    if X.ndim != 2 or X.shape[1] < 2:
        return 0.0
    with np.errstate(invalid="ignore", divide="ignore"):
        c = np.corrcoef(X, rowvar=False)
    c = np.nan_to_num(c, nan=0.0)
    np.fill_diagonal(c, 1.0)
    eig = np.clip(np.linalg.eigvalsh(c), 0, None)
    s = eig.sum()
    if s <= 0:
        return 0.0
    p = eig / s
    p = p[p > 0]
    return float(-(p * np.log(p)).sum() / np.log(len(eig)))


def evaluate(factor_values, forward_returns, library_matrix=None, pps_min=0.02, pfs_min=0.8):
    """五维初筛汇总 + 硬闸门：PPS 须超 max(pps_min, 2-sigma 噪声地板 2/√n)(样本越小要求越高,
    杜绝把随机 IC 当预测力) 且 PFS 达标，才放行进下一关。"""
    f_arr, _ = _finite_pair(factor_values, forward_returns)
    n = len(f_arr)
    p = pps(factor_values, forward_returns)
    fs = pfs(factor_values)
    d = diversity_entropy(library_matrix) if library_matrix is not None else None
    floor = max(pps_min, 2.0 / np.sqrt(n)) if n > 0 else 1.0   # 2σ 噪声地板
    return {"pps": round(p, 4), "pfs": round(fs, 4), "pps_floor": round(floor, 4),
            "diversity_entropy": round(d, 4) if d is not None else None,
            "passes": bool(abs(p) >= floor and fs >= pfs_min)}
