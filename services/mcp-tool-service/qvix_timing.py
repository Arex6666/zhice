"""L5 QVIX 择时（纯函数）：隐含波动率(沪深300 QVIX)分位 → 择时区间。

QVIX = 沪深300大盘恐慌代理，不可当个股/中小盘波动（caveat）。仅缩仓位，不参与方向 ceiling。
实测 index_option_300etf_qvix 仅单一 QVIX OHLC 序列，无近/远月双序列 → term_structure 固定 None。
"""
import numpy as np


def qvix_level(qvix_series, window=250, min_history=20):
    s = np.asarray(qvix_series, dtype=float)
    if len(s) < min_history:
        return {"level": "unknown", "reason": "insufficient_history", "term_structure": None}
    cur = float(s[-1])
    win = s[-window:]
    pct = float((win <= cur).mean())
    level = ("low" if pct < 0.5 else "normal" if pct < 0.8
             else "elevated" if pct < 0.95 else "extreme")
    return {"level": level, "percentile": round(pct, 3), "qvix": cur, "term_structure": None}
