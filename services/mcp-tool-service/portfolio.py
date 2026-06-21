"""L4 组合构建（research-only，纯函数 + 可选 cvxpy）。

默认稳健档：LedoitWolf 收缩协方差 + ERC 风险平价 / HRP（不求逆，大池最稳）。
MVO 是误差最大化器 → 仅收窄池启用（见 build_portfolio）。强制与 1/N 对照（块自助）。
"""
import numpy as np

import backtest


def shrink_cov(returns):
    """Ledoit-Wolf 收缩协方差。返回 {cov, delta, condition_number}。"""
    R = np.asarray(returns, dtype=float)
    from sklearn.covariance import LedoitWolf
    lw = LedoitWolf().fit(R)
    cov = lw.covariance_
    eig = np.linalg.eigvalsh(cov)
    cond = float(eig.max() / eig.min()) if eig.min() > 0 else float("inf")
    return {"cov": [[float(v) for v in row] for row in cov],
            "delta": float(lw.shrinkage_), "condition_number": cond}


def risk_parity_erc(cov):
    """等风险贡献(ERC)权重：凸对数障碍 min 0.5·wᵀΣw − (1/n)Σln(w_i)（Spinu 2013），归一。

    其一阶条件 w_i·(Σw)_i = const 即风险贡献相等；对角协方差退化为反波动权重。
    """
    from scipy.optimize import minimize
    cov = np.asarray(cov, dtype=float)
    n = cov.shape[0]

    def obj(w):
        return 0.5 * float(w @ cov @ w) - (1.0 / n) * float(np.sum(np.log(w)))

    def grad(w):
        return cov @ w - (1.0 / n) / w

    res = minimize(obj, np.ones(n) / n, jac=grad,
                   bounds=[(1e-8, None)] * n, method="L-BFGS-B")
    w = np.maximum(res.x, 1e-12)
    return [float(x) for x in (w / w.sum())]


def _ivp(cov):
    iv = 1.0 / np.maximum(np.diag(cov), 1e-12)   # 零方差列(停牌)不产 inf
    return iv / iv.sum()


def _cluster_var(cov, items):
    c = cov[np.ix_(items, items)]
    w = _ivp(c)
    return float(w @ c @ w)


def hrp_weights(returns):
    """Hierarchical Risk Parity（López de Prado，不求逆）。输入 obs×assets 收益。"""
    from scipy.cluster.hierarchy import leaves_list, linkage
    from scipy.spatial.distance import squareform
    R = np.atleast_2d(np.asarray(returns, dtype=float))
    if R.shape[1] <= 1:                          # 单资产: 全仓, 不走 np.cov(0-d)/聚类
        return [1.0] * R.shape[1]
    cov = np.cov(R, rowvar=False)
    with np.errstate(invalid="ignore", divide="ignore"):
        corr = np.corrcoef(R, rowvar=False)      # 零方差列会产 NaN, 下行清理
    corr = np.nan_to_num(corr, nan=0.0)          # 零方差列 corr=NaN → 置 0(作孤立叶子)
    np.fill_diagonal(corr, 1.0)
    n = cov.shape[0]
    dist = np.nan_to_num(np.sqrt(np.clip(0.5 * (1 - corr), 0, None)), nan=0.0)
    np.fill_diagonal(dist, 0.0)
    order = list(leaves_list(linkage(squareform(dist, checks=False), method="single")))
    w = np.ones(n)
    clusters = [order]
    while clusters:
        nxt = []
        for cl in clusters:
            if len(cl) <= 1:
                continue
            half = len(cl) // 2
            c0, c1 = cl[:half], cl[half:]
            v0, v1 = _cluster_var(cov, c0), _cluster_var(cov, c1)
            alpha = 1 - v0 / (v0 + v1) if (v0 + v1) > 0 else 0.5
            for i in c0:
                w[i] *= alpha
            for i in c1:
                w[i] *= (1 - alpha)
            nxt += [c0, c1]
        clusters = nxt
    return [float(x) for x in (w / w.sum())]


def mvo(mu, cov, w_max=0.04, gamma=5.0):
    """均值方差(cvxpy QP, long-only)：max μᵀw − γ·wᵀΣw s.t. Σw=1, 0≤w≤w_max。

    不可行/求解失败 → 回退等权并带 fallback_reason（MVO 是误差最大化器，慎用）。
    """
    mu = np.asarray(mu, dtype=float)
    cov = np.asarray(cov, dtype=float)
    n = len(mu)
    eq = [1.0 / n] * n
    if n * w_max < 1 - 1e-9:
        return {"weights": eq, "status": "infeasible",
                "fallback_reason": f"w_max={w_max}×n={n}<1，无法满足 Σw=1"}
    try:
        import cvxpy as cp
        w = cp.Variable(n)
        obj = cp.Maximize(mu @ w - gamma * cp.quad_form(w, cp.psd_wrap(cov)))
        cons = [cp.sum(w) == 1, w >= 0, w <= w_max]
        prob = cp.Problem(obj, cons)
        prob.solve()
        if prob.status == "optimal" and w.value is not None:
            wv = np.clip(np.asarray(w.value).flatten(), 0, None)
            wv = wv / wv.sum()
            return {"weights": [float(x) for x in wv], "status": "optimal"}
        return {"weights": eq, "status": prob.status or "failed",
                "fallback_reason": f"solver status={prob.status}"}
    except Exception as e:  # noqa: BLE001 - cvxpy 缺失/求解异常 → 回退
        return {"weights": eq, "status": "error", "fallback_reason": str(e)[:80]}


def shrink_cov_report(returns, cond_threshold=1e4):
    """收缩协方差诊断报告（供治理 R11 判"估计可靠性"）：δ/条件数/可靠性标记 + caveat。"""
    R = np.atleast_2d(np.asarray(returns, dtype=float))
    n_obs, n_assets = R.shape
    base = shrink_cov(R)
    cond = base["condition_number"]
    # 不可靠：条件数过高 或 观测数不足以支撑资产维度(T < 2N，协方差欠定)
    reliable = bool(np.isfinite(cond) and cond < cond_threshold and n_obs >= 2 * n_assets)
    caveat = None if reliable else (
        "协方差估计欠定/病态（T<2N 或条件数过高）→ 建议回退 ERC/HRP，勿用 MVO（R11）")
    return {"delta": base["delta"], "condition_number": cond,
            "n_assets": int(n_assets), "n_obs": int(n_obs),
            "reliable": reliable, "caveat": caveat,
            "research_only": True}


def efficient_frontier(mu, cov, n_points=10, w_max=0.04, gamma_lo=0.5, gamma_hi=50.0):
    """research-only 有效前沿：在风险厌恶 γ 网格上解 long-only MVO，给 (ret, vol, weights) 序列。

    仅作研究展示（MVO 是误差最大化器，强制并列 1/N，绝不主张可实盘）。求解失败的网格点跳过。
    """
    mu = np.asarray(mu, dtype=float)
    cov = np.asarray(cov, dtype=float)
    pts = []
    gammas = np.geomspace(gamma_lo, gamma_hi, max(2, n_points))   # 低γ激进→高γ保守
    for g in gammas:
        sol = mvo(mu, cov, w_max=w_max, gamma=float(g))
        w = np.asarray(sol["weights"], dtype=float)
        ret = float(mu @ w)
        vol = float(np.sqrt(max(0.0, w @ cov @ w)))
        pts.append({"gamma": float(round(g, 4)), "ret": round(ret, 6),
                    "vol": round(vol, 6), "weights": [float(x) for x in w],
                    "status": sol.get("status")})
    # 去重(同解)并按波动升序
    pts = sorted(pts, key=lambda p: p["vol"])
    return {"frontier": pts, "research_only": True,
            "caveat": "MVO 有效前沿仅研究展示，误差最大化器，强制并列 1/N，不可实盘"}


def capacity_check(weights, capital, adv, max_participation=0.1):
    """容量诊断：参与度 = 仓位市值/ADV；超阈标 illiquid（仅事后诊断，研究型）。"""
    out = []
    for i, w in enumerate(weights):
        a = float(adv[i]) if adv[i] else 0.0
        part = (float(w) * capital / a) if a > 0 else float("inf")
        out.append({"index": i, "participation": round(part, 4),
                    "illiquid": bool(part > max_participation)})
    return {"names": out, "max_participation": max_participation}


def build_portfolio(symbols, scores, returns_panel, method="hrp", w_max=0.04,
                    enable_mvo=False):
    """组合编排：默认 HRP/ERC 稳健档；MVO 仅 enable_mvo 且 N≤100 时启用，否则回退。"""
    n = len(symbols)
    if n <= 1:   # 单/空标的: 全仓短路, 不进 np.cov(0-d)/聚类/优化器
        return {"weights": {s: 1.0 for s in symbols}, "method": method,
                "fallback_reason": "single_asset" if n == 1 else "no_symbols"}
    fallback = None
    if method == "mvo" and enable_mvo and scores is not None and n <= 100:
        res = mvo(scores, np.cov(np.asarray(returns_panel), rowvar=False), w_max=w_max)
        w = res["weights"]
        if res["status"] != "optimal":
            fallback = res.get("fallback_reason")
            method = "erc"
            w = risk_parity_erc(np.cov(np.asarray(returns_panel), rowvar=False))
    elif method == "erc":
        w = risk_parity_erc(np.cov(np.asarray(returns_panel), rowvar=False))
    else:
        method = "hrp"
        w = hrp_weights(returns_panel)
    return {"weights": {s: float(wi) for s, wi in zip(symbols, w)},
            "method": method, "fallback_reason": fallback}


def beats_one_over_n(port_rets, equal_rets):
    """组合 net 收益与 1/N 配对差分 → 块自助显著性。返回 {beats, mean_excess, p_value}。"""
    excess = np.asarray(port_rets, dtype=float) - np.asarray(equal_rets, dtype=float)
    boot = backtest.bootstrap_significance(excess)
    sig = boot.get("significant")
    mean = float(np.mean(excess))
    if sig is None:
        beats = None
    else:
        beats = bool(sig and mean > 0)
    return {"beats": beats, "mean_excess": round(mean, 6), "p_value": boot.get("p_value")}
