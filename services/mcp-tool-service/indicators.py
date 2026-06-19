"""技术指标（纯函数，不联网，可脱网单测）。

输入为收盘价序列（及可选 high/low/volume），长度不足时对应指标返回 None。
"""
import numpy as np
import pandas as pd


def _ma(s, n):
    return float(s[-n:].mean()) if len(s) >= n else None


def _rsi(s, n=14):
    if len(s) < n + 1:
        return None
    d = np.diff(s)
    up = np.where(d > 0, d, 0.0)
    dn = np.where(d < 0, -d, 0.0)
    ag = pd.Series(up).rolling(n).mean().iloc[-1]
    al = pd.Series(dn).rolling(n).mean().iloc[-1]
    if al == 0:
        return 100.0
    rs = ag / al
    return float(100 - 100 / (1 + rs))


def _macd(s, f=12, sl=26, sig=9):
    if len(s) < sl:
        return {"dif": None, "dea": None, "hist": None}
    ser = pd.Series(s)
    ef = ser.ewm(span=f).mean()
    es = ser.ewm(span=sl).mean()
    dif = ef - es
    dea = dif.ewm(span=sig).mean()
    return {"dif": float(dif.iloc[-1]), "dea": float(dea.iloc[-1]),
            "hist": float((dif - dea).iloc[-1] * 2)}


def _boll(s, n=20, k=2):
    if len(s) < n:
        return {"mid": None, "up": None, "low": None}
    ser = pd.Series(s[-n:])
    m = ser.mean()
    sd = ser.std()
    return {"mid": float(m), "up": float(m + k * sd), "low": float(m - k * sd)}


def compute_indicators(closes, highs=None, lows=None, volumes=None):
    s = np.array(closes, dtype=float)
    vr = None
    if volumes and len(volumes) >= 6:
        base = np.mean(volumes[-6:-1]) or 1
        vr = float(volumes[-1] / base)
    return {"ma5": _ma(s, 5), "ma10": _ma(s, 10), "ma20": _ma(s, 20), "ma60": _ma(s, 60),
            "rsi14": _rsi(s), "macd": _macd(s), "boll": _boll(s), "vol_ratio": vr}
