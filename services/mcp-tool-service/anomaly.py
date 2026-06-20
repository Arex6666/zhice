"""稳健价量异动检测（纯函数，numpy-only）。

用 MAD/Hampel 稳健 z 分数（对离群不敏感）标记价/量异动，并**区分**
"疑似坏数据"(suspected_bad_data，价格尖峰但无成交量佐证) 与
"疑似真实事件"(suspected_event，放量大幅波动)。前者应降级数据质量，后者入委员会证据。
"""
import numpy as np

_K = 0.6745  # 正态一致化常数：z = K*(x-median)/MAD


def mad_zscore(x):
    """稳健 z 分数序列：K*(x-median)/MAD。

    当过半数值相同导致 MAD=0 时，退回标准差作尺度（仍能识别尖峰）；
    标准差也为 0（完全恒定）才返回全 0。
    """
    a = np.asarray(x, dtype=float)
    med = np.median(a)
    mad = np.median(np.abs(a - med))
    if mad == 0:
        sd = float(np.std(a))
        if sd == 0:
            return [0.0] * len(a)
        return [float((v - med) / sd) for v in a]
    return [float(_K * (v - med) / mad) for v in a]


def detect_anomalies(kline, ret_z=3.5, vol_z=2.0):
    """检测价量异动并消歧。kline: OHLCV dict 列表（时间升序）。"""
    closes = np.array([r.get("close") for r in kline if r.get("close") is not None], dtype=float)
    vols = np.array([(r.get("volume") or 0.0) for r in kline if r.get("close") is not None], dtype=float)
    if len(closes) < 20:
        return {"anomalies": [], "reason": "样本不足(<20)", "n": int(len(closes))}
    rets = np.diff(closes) / closes[:-1]
    rz = mad_zscore(rets)
    vz = mad_zscore(vols[1:])  # 对齐 rets（每个 ret 对应其当日成交量）
    out = []
    for i, (r, z) in enumerate(zip(rets, rz)):
        if abs(z) < ret_z:
            continue
        v_confirm = vz[i] > vol_z
        out.append({
            "index": i + 1,
            "ts": kline[i + 1].get("ts"),
            "ret": round(float(r), 4),
            "ret_z": round(float(z), 2),
            "vol_z": round(float(vz[i]), 2),
            "classification": "suspected_event" if v_confirm else "suspected_bad_data",
        })
    return {"anomalies": out, "n": int(len(closes)),
            "note": "suspected_event=放量异动(入证据)；suspected_bad_data=无量价尖峰(降数据质量)"}
