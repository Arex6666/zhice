"""可信回测（纯函数）：双均线交叉策略，含手续费/滑点，输出可信指标包。

仍不可直接外推到未来——所有结果附 DISC 风险标签。
"""
import numpy as np
import pandas as pd

DISC = "历史回测含手续费/滑点，仍不可直接外推到未来（存在过拟合/幸存者偏差/未来函数风险）。"


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
    return {"total_return": total, "annualized": ann, "benchmark_return": bench,
            "max_drawdown": dd, "sharpe": sharpe, "win_rate": wr,
            "max_consec_loss": int(mcl), "trades": ntr, "disclaimer": DISC}


def param_sensitivity(closes, grid):
    out = []
    for sh, ln in grid:
        r = backtest_ma(closes, sh, ln)
        out.append({"short": sh, "long": ln, "total_return": r.get("total_return")})
    return out
