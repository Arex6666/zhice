"""L5 风控/择时叠加（纯函数）：已实现波动 + QVIX → 目标仓位乘子 scale∈[floor,1]。

取两刹车 min（保守优先），永不>1（只减不加）。scale 只缩 net-exposure，不参与方向 ceiling
（与 R8 解耦，避免多刹车连乘"诚实到无用"）。
"""
_FACTOR = {"low": 1.0, "normal": 1.0, "elevated": 0.75, "extreme": 0.5, "unknown": 1.0}


def target_scale(vol_regime, qvix_level, floor=0.5):
    floor = min(max(floor, 0.0), 1.0)            # floor 越界钳到 [0,1]，杜绝放大>1
    rf = _FACTOR.get(vol_regime, 1.0)
    qf = _FACTOR.get(qvix_level, 1.0)
    scale = min(1.0, max(floor, min(rf, qf)))    # 硬不变量: scale 永不>1(只减不加)
    return {"scale": round(scale, 3), "vol_factor": rf, "qvix_factor": qf, "floor": floor}
