# -*- coding: utf-8 -*-
"""AI 量化模拟引擎(纯函数)：横截面**反转**多因子、top-K 等权、周频调仓的持续纸面交易。

诚实边界:
  - 信号 = 短期反转(近 lookback 日跌幅越大 → 打分越高)。A股经实测为反转市(Rev_5 RankIC+0.063)。
  - **无未来函数**: 第 t 日调仓只用 close[<=t]; 成交按 close[t] 计, 收 cost。
  - 固定当代表宇宙 → 有幸存者偏差(研究演示, 非实盘)。做多头, 无杠杆无做空。
输入 panel 需**已对齐**(各 symbol 的 closes 与 dates 等长、同交易日)。
"""


def _default_params(p):
    d = {"lookback": 5, "rebalance": 5, "top_k": 5, "cost": 0.001,
         "principal": 100000.0, "warmup": 25, "reason_tag": "5日反转·超跌买入"}
    d.update(p or {})
    d["warmup"] = max(d["warmup"], d["lookback"])
    return d


def _mark(shares, closes, t):
    return sum(sh * closes[s][t] for s, sh in shares.items() if sh)


def simulate(panel, params=None):
    p = _default_params(params)
    dates = panel["dates"]
    syms = panel["symbols"]
    closes = {s: syms[s]["closes"] for s in syms}
    names = {s: syms[s].get("name", s) for s in syms}
    T = len(dates)
    lb, reb, K, cost = p["lookback"], p["rebalance"], p["top_k"], p["cost"]
    warm, principal = p["warmup"], float(p["principal"])

    cash = principal
    shares = {s: 0.0 for s in syms}
    avg_cost = {s: 0.0 for s in syms}
    trades, equity, holdings = [], [], []
    peak, max_dd = -1e18, 0.0
    wins = closed = 0

    # 基准：等权买入持有(warmup 日建仓)
    bench_alloc = principal / len(syms)
    bench_shares = {s: (bench_alloc / closes[s][warm]) if closes[s][warm] else 0.0 for s in syms}
    benchmark = []

    for t in range(warm, T):
        d = dates[t]
        # —— 调仓(仅用 <=t 数据) ——
        if (t - warm) % reb == 0:
            scores = []
            for s in syms:
                base = closes[s][t - lb]
                if base:
                    scores.append((-(closes[s][t] / base - 1.0), s))   # 跌多→分高
            scores.sort(reverse=True)
            target = {s for _, s in scores[:K]}
            equity_now = cash + _mark(shares, closes, t)
            # 先卖出不在目标里的
            for s in list(shares):
                if shares[s] > 0 and s not in target:
                    px = closes[s][t]; sh = shares[s]
                    val = sh * px * (1 - cost)
                    cash += val
                    pnl = (px - avg_cost[s]) * sh
                    closed += 1; wins += 1 if pnl > 0 else 0
                    trades.append({"date": d, "action": "sell", "symbol": s, "name": names[s],
                                   "price": round(px, 3), "shares": round(sh, 2),
                                   "value": round(sh * px, 2), "pnl": round(pnl, 2),
                                   "reason": "移出持仓(不再最超跌)"})
                    shares[s] = 0.0
            # 再把目标调到等权
            tgt_val = equity_now / K
            for s in target:
                px = closes[s][t]
                if not px:
                    continue
                cur_val = shares[s] * px
                delta_val = tgt_val - cur_val
                if abs(delta_val) < max(equity_now * 0.005, 1.0):   # 变动过小不折腾
                    continue
                dsh = delta_val / px
                if dsh > 0:                                          # 买
                    spend = dsh * px * (1 + cost)
                    if spend > cash:
                        dsh = (cash / (px * (1 + cost))); spend = cash
                    if dsh <= 0:
                        continue
                    new_sh = shares[s] + dsh
                    avg_cost[s] = ((avg_cost[s] * shares[s]) + px * dsh) / new_sh if new_sh else 0.0
                    shares[s] = new_sh; cash -= spend
                    trades.append({"date": d, "action": "buy", "symbol": s, "name": names[s],
                                   "price": round(px, 3), "shares": round(dsh, 2),
                                   "value": round(dsh * px, 2), "reason": p["reason_tag"]})
                else:                                               # 减
                    sh = -dsh
                    cash += sh * px * (1 - cost)
                    pnl = (px - avg_cost[s]) * sh
                    closed += 1; wins += 1 if pnl > 0 else 0
                    shares[s] -= sh
                    trades.append({"date": d, "action": "sell", "symbol": s, "name": names[s],
                                   "price": round(px, 3), "shares": round(sh, 2),
                                   "value": round(sh * px, 2), "pnl": round(pnl, 2),
                                   "reason": "再平衡减仓"})
            # 调仓后持仓快照(供前端展示)
            eq2 = cash + _mark(shares, closes, t)
            pos = [{"symbol": s, "name": names[s], "shares": round(shares[s], 2),
                    "value": round(shares[s] * closes[s][t], 2),
                    "weight": round(shares[s] * closes[s][t] / eq2, 4) if eq2 else 0.0}
                   for s in syms if shares[s] > 0]
            holdings.append({"date": d, "positions": sorted(pos, key=lambda x: -x["value"])})

        # —— 每日盯市 ——
        inv = _mark(shares, closes, t)
        eq = cash + inv
        peak = max(peak, eq)
        max_dd = min(max_dd, eq / peak - 1.0) if peak > 0 else max_dd
        equity.append({"date": d, "equity": round(eq, 2), "cash": round(cash, 2),
                       "invested": round(inv, 2)})
        benchmark.append({"date": d, "value": round(sum(bench_shares[s] * closes[s][t] for s in syms), 2)})

    final_eq = equity[-1]["equity"] if equity else principal
    bench_final = benchmark[-1]["value"] if benchmark else principal
    stats = {"principal": principal, "final_equity": final_eq,
             "total_return": round(final_eq / principal - 1.0, 4),
             "benchmark_return": round(bench_final / principal - 1.0, 4),
             "excess_return": round(final_eq / principal - bench_final / principal, 4),
             "n_trades": len(trades),
             "n_buys": sum(1 for t in trades if t["action"] == "buy"),
             "n_sells": sum(1 for t in trades if t["action"] == "sell"),
             "win_rate": round(wins / closed, 4) if closed else None,
             "closed_trades": closed,
             "max_drawdown": round(max_dd, 4),
             "days": len(equity)}
    return {"equity": equity, "benchmark": benchmark, "trades": trades,
            "holdings": holdings, "stats": stats,
            "params": {k: p[k] for k in ("lookback", "rebalance", "top_k", "cost", "principal")}}
