"""波动状态层（纯函数，numpy-only）。

把"波动"从隐性变量做成显式、可解释的状态：EWMA 已实现波动、Parkinson / Garman-Klass
高低开收估计，以及当前波动在自身历史分布中的**分位**→ 区间标签(low/normal/elevated/extreme)。
区间来自分位（数据驱动），非魔法阈值，可作为治理 R8 的可达波动刹车。
"""
import numpy as np


def ewma_vol(returns, lam=0.94):
    """RiskMetrics EWMA 波动（递归）。样本<2 返回 None。"""
    r = np.asarray(returns, dtype=float)
    if len(r) < 2:
        return None
    var = float(r[0] ** 2)
    for x in r[1:]:
        var = lam * var + (1 - lam) * float(x) * float(x)
    return float(np.sqrt(var))


def parkinson(highs, lows):
    """Parkinson 高低价波动估计：sqrt(mean(ln(H/L)^2)/(4 ln2))。"""
    h = np.asarray(highs, dtype=float)
    lo = np.asarray(lows, dtype=float)
    if len(h) < 1 or len(lo) != len(h) or np.any(lo <= 0):
        return None
    hl = np.log(h / lo)
    return float(np.sqrt(np.mean(hl ** 2) / (4 * np.log(2))))


def garman_klass(opens, highs, lows, closes):
    """Garman-Klass OHLC 波动估计。"""
    o, h, lo, c = (np.asarray(x, dtype=float) for x in (opens, highs, lows, closes))
    n = len(c)
    if n < 1 or len(o) != n or len(h) != n or len(lo) != n or np.any(lo <= 0) or np.any(o <= 0):
        return None
    hl = np.log(h / lo)
    co = np.log(c / o)
    gk = 0.5 * hl ** 2 - (2 * np.log(2) - 1) * co ** 2
    return float(np.sqrt(max(0.0, float(np.mean(gk)))))


def vol_state(kline, window=20):
    """从 OHLC kline 计算当前已实现波动及其历史分位 → 区间标签。"""
    closes = np.array([r.get("close") for r in kline if r.get("close") is not None], dtype=float)
    if len(closes) < max(2 * window, 30):
        return {"regime": "unknown", "reason": "样本不足", "n": int(len(closes))}
    rets = np.diff(closes) / closes[:-1]
    # 滚动窗口已实现波动序列
    rollvols = np.array([float(np.std(rets[i - window:i], ddof=1))
                         for i in range(window, len(rets) + 1)])
    cur = float(rollvols[-1])
    pct = float((rollvols <= cur).mean())
    regime = ("low" if pct < 0.5 else "normal" if pct < 0.8
              else "elevated" if pct < 0.95 else "extreme")
    highs = [r.get("high") for r in kline if r.get("high") is not None]
    lows = [r.get("low") for r in kline if r.get("low") is not None]
    return {"regime": regime, "vol_pct": round(pct, 3),
            "ewma_vol": ewma_vol(rets[-window:]),
            "realized_vol": cur,
            "parkinson": parkinson(highs[-window:], lows[-window:]) if len(highs) >= window else None,
            "annualized_pct": round(cur * (252 ** 0.5) * 100, 2), "n": int(len(closes))}
