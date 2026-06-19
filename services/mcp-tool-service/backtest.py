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
    if len(trades_idx):
        strat[trades_idx] = strat[trades_idx] - cost
    eq = np.cumprod(1 + strat)
    total = float(eq[-1] - 1)
    bench = float(c[-1] / c[0] - 1)
    n = len(strat)
    ann = float((1 + total) ** (252 / max(n, 1)) - 1)
    sharpe = float(np.mean(strat) / (np.std(strat) + 1e-9) * np.sqrt(252))
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
