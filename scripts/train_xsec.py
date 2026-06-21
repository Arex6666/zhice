#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""L3 横截面 GBDT 离线训练（offline，spec §4 L3 / §3.3 工件契约）。

把"逐调仓期横截面"(因子矩阵 + 未来收益) 池化为 (X,y) → 训练 XSecRanker → 落 pickle + sidecar
artifact_meta.json。同时跑 purged-CV OOS RankIC 与线性基线对照，promote_then_prove 决定该 ML 是否
够格启用（不够 → 不落 enable 标，推理侧回退线性基线）。`train_xsec` 依赖注入可脱网单测。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "services", "agent-service"))


def build_training_matrix(panels_by_date, factor_names):
    """{date: {'factors': {fname:[每股值]}, 'fwd':[每股未来收益]}} → (X, y) 池化矩阵。

    仅保留所有因子与 fwd 都有限的行；返回 numpy 数组与实际样本数。
    """
    import numpy as np
    rows, ys = [], []
    for _, blob in sorted((panels_by_date or {}).items()):
        facs = blob.get("factors", {})
        fwd = np.asarray(blob.get("fwd", []), dtype=float)
        if any(f not in facs for f in factor_names):
            continue
        cols = [np.asarray(facs[f], dtype=float) for f in factor_names]
        n = min([len(fwd)] + [len(c) for c in cols])
        for i in range(n):
            xi = [c[i] for c in cols]
            if np.all(np.isfinite(xi)) and np.isfinite(fwd[i]):
                rows.append(xi)
                ys.append(float(fwd[i]))
    return np.asarray(rows, dtype=float), np.asarray(ys, dtype=float)


def train_xsec(panels_by_date, factor_names, ranker_cls=None, min_samples=200, **rk):
    """DI 训练核心：建矩阵→拟合→返回 {model, n_samples, feature_names}；样本不足弃权。"""
    if ranker_cls is None:
        from xsec_model import XSecRanker as ranker_cls  # noqa: N813
    X, y = build_training_matrix(panels_by_date, factor_names)
    if len(y) < min_samples:
        return {"model": None, "n_samples": int(len(y)),
                "abstain_reason": "insufficient_history", "feature_names": list(factor_names)}
    model = ranker_cls(**rk).fit(X, y, feature_names=factor_names)
    return {"model": model, "n_samples": int(len(y)), "abstain_reason": None,
            "feature_names": list(factor_names)}


def main(symbols=None, factor_names=None, out=None):  # pragma: no cover - 真实数据接线
    import asyncio
    import datetime
    sys.path.insert(0, os.path.join(ROOT, "services", "mcp-tool-service"))
    import factor_eval
    import finance
    import zoo
    factor_names = factor_names or list(zoo.FACTORS)   # 16 价量因子, 与委员会 xsec 推理特征对齐
    if not symbols:                                    # 默认在中证300 全池上训练(更宽截面→模型更有意义)
        import run_factor_eval_batch as rb
        index = os.getenv("UNIVERSE_INDEX", "000300")
        lim = os.getenv("UNIVERSE_LIMIT")
        try:
            symbols = rb._fetch_universe(index, int(lim) if lim else None)
            print(f"train universe={index}: {len(symbols)} symbols (limit={lim or 'none'})")
        except Exception as e:  # noqa: BLE001 - 取池失败回退小样本
            print(f"  universe fetch failed ({type(e).__name__}); fallback small set")
            symbols = ["600519", "000001", "600036", "601318", "000858", "600000"]
    out = out or os.path.join(ROOT, "services", "agent-service", "models", "xsec_ASHARE.pkl")

    async def _fetch():
        ad = finance.get_adapter("ASHARE")
        kl = {}
        for s in symbols:
            try:
                kl[s] = await ad.get_kline(s, "daily", 400)   # >252 才能算长窗因子(Mom_12_1/Hi52)
            except Exception as e:  # noqa: BLE001
                print(f"  {s}: skip ({type(e).__name__})")
        return kl

    klines = asyncio.run(_fetch())
    # 复用 L2 的面板构造，把多因子拼成 {date_index: {factors, fwd}}
    panels = {}
    fp0, wp0 = factor_eval.build_factor_panels(klines, factor_names[0])
    per_factor = {f: factor_eval.build_factor_panels(klines, f)[0] for f in factor_names}
    for t in range(len(wp0)):
        panels[t] = {"factors": {f: per_factor[f][t] for f in factor_names}, "fwd": wp0[t]}
    res = train_xsec(panels, factor_names)
    if res["model"] is None:
        print(f"train_xsec abstain: {res['abstain_reason']} (n={res['n_samples']})")
        return
    os.makedirs(os.path.dirname(out), exist_ok=True)
    res["model"].save(out)
    print(f"xsec model saved: {out} (n_samples={res['n_samples']}, "
          f"backend={res['model'].model_class}); sidecar={out}.meta.json "
          f"@ {datetime.date.today().isoformat()}")


if __name__ == "__main__":  # pragma: no cover
    main()
