"""L5 风控/择时叠加（纯函数）：已实现波动 + QVIX → 目标仓位乘子 scale∈[floor,1]。

取两刹车 min（保守优先），永不>1（只减不加）。scale 只缩 net-exposure，不参与方向 ceiling
（与 R8 解耦，避免多刹车连乘"诚实到无用"）。
"""
_FACTOR = {"low": 1.0, "normal": 1.0, "elevated": 0.75, "extreme": 0.5, "unknown": 1.0}


def target_scale(vol_regime, qvix_level, floor=0.5):
    rf = _FACTOR.get(vol_regime, 1.0)
    qf = _FACTOR.get(qvix_level, 1.0)
    scale = max(floor, min(1.0, rf, qf))
    return {"scale": round(scale, 3), "vol_factor": rf, "qvix_factor": qf, "floor": floor}
