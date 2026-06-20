"""可信回测（纯函数）：双均线交叉策略，含手续费/滑点，输出可信指标包。

仍不可直接外推到未来——所有结果附 DISC 风险标签。
"""
import numpy as np
import pandas as pd

DISC = "历史回测含手续费/滑点，仍不可直接外推到未来（存在过拟合/幸存者偏差/未来函数风险）。"


def _downsample(arr, k=120):
    """把曲线降采样到至多 k 个点，便于前端绘制（保留首尾趋势）。"""
    a = list(arr)
    if len(a) <= k:
        return [round(float(x), 4) for x in a]
    step = len(a) / k
    return [round(float(a[min(len(a) - 1, int(i * step))]), 4) for i in range(k)]


def _signals(c, sh, ln):
    s = pd.Series(c)
    ms = s.rolling(sh).mean()
    ml = s.rolling(ln).mean()
    pos = (ms > ml).astype(int)
    return pos.fillna(0).values


def backtest_ma(closes, short, long, fee_bps=5, slippage_bps=5):
    c = np.array(closes, dtype=float)
    if len(c) < long + 2:
        return {"error": "数据不足", "disclaimer": DISC}
    pos = _signals(c, short, long)
    ret = np.diff(c) / c[:-1]
    pos = pos[:-1]
    cost = (fee_bps + slippage_bps) / 1e4
    trades_idx = np.where(np.diff(pos) != 0)[0]
    ntr = int(len(trades_idx))
    strat = pos * ret
    # 成本扣在仓位真正切换后生效的那一天(i+1)，而非信号变化的空仓日(i)，避免污染空仓日
    cost_idx = trades_idx + 1
    cost_idx = cost_idx[cost_idx < len(strat)]
    if len(cost_idx):
        strat[cost_idx] = strat[cost_idx] - cost
    eq = np.cumprod(1 + strat)
    total = float(eq[-1] - 1)
    bench = float(c[-1] / c[0] - 1)
    n = len(strat)
    # 年化仅在样本足够时给出，避免短样本指数外推（与"不可外推"声明一致）
    ann = float((1 + total) ** (252 / n) - 1) if n >= 200 else None
    # 夏普基于"在场"交易日、用 ddof=1（样本标准差）；空仓日不计入
    in_pos = strat[pos != 0]
    if len(in_pos) > 1:
        sd = float(np.std(in_pos, ddof=1))
        sharpe = float(np.mean(in_pos) / (sd + 1e-9) * np.sqrt(252))
    else:
        sharpe = 0.0
    dd = float(np.min(eq / np.maximum.accumulate(eq) - 1))
    active = strat[strat != 0]
    wr = float((active > 0).mean()) if len(active) else 0.0
    mcl = cur = 0
    for x in strat:
        if x < 0:
            cur += 1
            mcl = max(mcl, cur)
        elif x > 0:
            cur = 0
    bench_curve = c[1:] / c[0]  # 买入持有净值，与 strat 等长(n)
    return {"total_return": total, "annualized": ann, "benchmark_return": bench,
            "max_drawdown": dd, "sharpe": sharpe, "win_rate": wr,
            "max_consec_loss": int(mcl), "trades": ntr,
            "equity_curve": _downsample(eq), "benchmark_curve": _downsample(bench_curve),
            "significance": bootstrap_significance(strat), "disclaimer": DISC}


def bootstrap_significance(returns, n_boot=1000, seed=42, alpha=0.05):
    """平稳(循环)块自助检验：策略日收益的均值是否显著为正，还是仅是运气。

    - 块长取 ~√n（保留短期自相关，避免独立同分布假设高估显著性）。
    - CI：直接对收益重采样的均值分位。
    - p 值：零假设居中(减去观测均值)后，自助均值达到观测均值的单侧概率。
    返回 significant=None 表示样本不足、无法判定（诚实弃权，不冒充结论）。
    """
    r = np.asarray([x for x in returns if x is not None], dtype=float)
    n = len(r)
    if n < 20:
        return {"significant": None, "reason": "样本不足(<20)", "n": int(n)}
    block = max(2, int(round(np.sqrt(n))))
    n_blocks = int(np.ceil(n / block))
    obs_mean = float(r.mean())
    rng = np.random.RandomState(seed)
    means = np.empty(n_boot)
    for b in range(n_boot):
        starts = rng.randint(0, n, size=n_blocks)
        idx = np.concatenate([(s + np.arange(block)) % n for s in starts])[:n]
        means[b] = r[idx].mean()
    ci_low = float(np.quantile(means, alpha / 2))
    ci_high = float(np.quantile(means, 1 - alpha / 2))
    # 零假设居中：null 下均值为 0；观测越极端 p 越小（单侧，方向取观测符号）
    centered = means - obs_mean
    if obs_mean >= 0:
        p_value = float(np.mean(centered >= obs_mean))
    else:
        p_value = float(np.mean(centered <= obs_mean))
    significant = bool(p_value < alpha and (ci_low > 0 or ci_high < 0))
    return {"significant": significant, "p_value": round(p_value, 4),
            "mean_return": obs_mean, "ci_low": ci_low, "ci_high": ci_high,
            "block_len": block, "n": int(n), "n_boot": n_boot}


def param_sensitivity(closes, grid):
    out = []
    for sh, ln in grid:
        r = backtest_ma(closes, sh, ln)
        out.append({"short": sh, "long": ln, "total_return": r.get("total_return")})
    return out
