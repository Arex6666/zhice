#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""诚实审计 XGBoost 信号：方向靶 vs 波动靶，并用随机游走零假设检验是否优于随机。

产出一句可引用的诚实结论，例如：
  "次日方向与随机游走不可区分(AUC=0.50, 置换零假设均值=0.50)；
   次日波动弱可学习(AUC=0.556 > 零假设 0.50)。"
用于答辩时坦诚说明"为何 ML 票是非方向的波动风险票，而非涨跌预测"。
"""
import asyncio
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "services", "mcp-tool-service"))
sys.path.insert(0, os.path.join(ROOT, "services", "agent-service"))

import finance  # noqa: E402
import ml_signal  # noqa: E402

SYMBOLS = ["600519", "000001", "600036", "601318", "000858", "600000", "002594", "300750"]


def _direction_dataset(kline):
    """方向靶：次日是否上涨(ret>0)。特征与波动靶一致(仅截至 T 日)。"""
    closes = np.array([r["close"] for r in kline], dtype=float)
    if len(closes) < 3:
        return np.array([]), np.array([])
    rets = np.diff(closes) / closes[:-1]
    X, y = [], []
    for i in range(21, len(kline) - 1):
        f = ml_signal.build_features(kline[:i + 1])
        if f is None:
            continue
        X.append(f)
        y.append(1 if rets[i] > 0 else 0)
    return np.array(X), np.array(y)


async def main():
    ad = finance.get_adapter("ASHARE")
    Xv, yv, gv, Xd, yd, gd = [], [], [], [], [], []
    for gi, code in enumerate(SYMBOLS):
        try:
            kl = await ad.get_kline(code, "daily", 250)
        except Exception as e:
            print(f"  {code}: skip ({type(e).__name__})")
            continue
        X1, y1 = ml_signal.build_dataset(kl)       # 波动靶
        X2, y2 = _direction_dataset(kl)            # 方向靶
        if len(X1):
            Xv.append(X1); yv.append(y1); gv.append(np.full(len(X1), gi))
        if len(X2):
            Xd.append(X2); yd.append(y2); gd.append(np.full(len(X2), gi))
    if not Xv or not Xd:
        print("无数据，退出。")
        return
    Xv, yv, gv = np.vstack(Xv), np.concatenate(yv), np.concatenate(gv)
    Xd, yd, gd = np.vstack(Xd), np.concatenate(yd), np.concatenate(gd)

    vol = ml_signal.walk_forward_auc(Xv, yv, gv)
    vol_null = ml_signal.permutation_null_auc(Xv, yv, gv, n_perm=20)
    dirn = ml_signal.walk_forward_auc(Xd, yd, gd)
    dir_null = ml_signal.permutation_null_auc(Xd, yd, gd, n_perm=20)

    print("=== 信号诚实审计（pooled OOS walk-forward）===")
    print(f"波动靶 AUC={vol['auc']:.3f}  零假设均值={vol_null['null_mean']:.3f}±{vol_null['null_std']:.3f}")
    print(f"方向靶 AUC={dirn['auc']:.3f}  零假设均值={dir_null['null_mean']:.3f}±{dir_null['null_std']:.3f}")
    vol_skill = vol["auc"] - vol_null["null_mean"]
    dir_skill = dirn["auc"] - dir_null["null_mean"]
    print("\n结论：")
    print(f"  方向：{'与随机不可区分' if dir_skill < 0.02 else f'弱可学习(+{dir_skill:.3f})'}")
    print(f"  波动：{'与随机不可区分' if vol_skill < 0.02 else f'弱可学习(+{vol_skill:.3f})'}")
    print("  → 故 ML 票定位为非方向的『波动风险票』，仅校准不确定性，不预测涨跌。")


if __name__ == "__main__":
    asyncio.run(main())
