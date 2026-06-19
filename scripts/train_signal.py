#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""离线训练 XGBoost 弱信号校准器（A股），保存到 services/agent-service/models/signal_ASHARE.pkl。

诚实说明：短周期方向接近随机，模型多半 AUC≈0.5 → 自动弃权（这是设计的弃权机制，非缺陷）。
若 AUC≥0.55 才作为委员会"一票"，否则运行期该票弃权。
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
OUT_DIR = os.path.join(ROOT, "services", "agent-service", "models")


async def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    ad = finance.get_adapter("ASHARE")
    Xs, ys = [], []
    for code in SYMBOLS:
        try:
            kl = await ad.get_kline(code, "daily", 250)
            X, y = ml_signal.build_dataset(kl)
            if len(X):
                Xs.append(X)
                ys.append(y)
                print(f"  {code}: {len(X)} samples")
        except Exception as e:
            print(f"  {code}: skip ({type(e).__name__})")
    if not Xs:
        print("无训练数据，跳过（运行期该票将弃权）。")
        return
    X = np.vstack(Xs)
    y = np.concatenate(ys)
    print(f"总样本: {len(X)}")
    met = ml_signal.train(X, y)
    print(f"AUC={met['auc']}  abstain={met['abstain']}  reason={met.get('abstain_reason')}")
    out = os.path.join(OUT_DIR, "signal_ASHARE.pkl")
    ml_signal.save_model(met, out)
    print("saved", out)


if __name__ == "__main__":
    asyncio.run(main())
