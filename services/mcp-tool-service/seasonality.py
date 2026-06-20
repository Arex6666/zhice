"""季节性/日历效应诊断（纯函数，numpy-only）。

诚实定位：只在**多重检验校正后**仍显著才报告效应，否则明确报"无显著季节性(与随机一致)"。
用置换检验得 p 值（不假设正态），Benjamini-Hochberg 控制 5 个工作日的假发现率。
季节性仅作诊断展示，**永不抬升**治理置信度天花板。
"""
import datetime

import numpy as np

import multi_test

_NAMES = {0: "周一", 1: "周二", 2: "周三", 3: "周四", 4: "周五", 5: "周六", 6: "周日"}


def _weekday(ts):
    try:
        return datetime.date.fromisoformat(str(ts)[:10]).weekday()
    except (ValueError, TypeError):
        return None


def day_of_week_effect(kline, n_perm=1500, seed=42, alpha=0.05):
    rows = [(_weekday(r.get("ts")), r.get("close")) for r in kline]
    wkdays, rets = [], []
    for i in range(1, len(rows)):
        wd, c0, c1 = rows[i][0], rows[i - 1][1], rows[i][1]
        if wd is None or not c0 or c1 is None:
            continue
        wkdays.append(wd)
        rets.append((c1 - c0) / c0)
    if len(rets) < 30:
        return {"any_significant": False, "reason": "有效样本不足(<30)", "effects": []}
    wkdays = np.array(wkdays)
    rets = np.array(rets, dtype=float)
    overall = float(rets.mean())
    buckets = sorted(set(wkdays.tolist()))
    obs = {wd: abs(float(rets[wkdays == wd].mean()) - overall) for wd in buckets}
    rng = np.random.RandomState(seed)
    counts = {wd: 0 for wd in buckets}
    for _ in range(n_perm):
        perm = rng.permutation(wkdays)
        for wd in buckets:
            if abs(float(rets[perm == wd].mean()) - overall) >= obs[wd]:
                counts[wd] += 1
    pvals = {wd: (counts[wd] + 1) / (n_perm + 1) for wd in buckets}
    # Benjamini-Hochberg step-up（抽取到 multi_test.bh，逐位相等回归守护）
    adj_list = multi_test.bh([pvals[wd] for wd in buckets])
    adj = {wd: adj_list[i] for i, wd in enumerate(buckets)}
    effects = [{"bucket": _NAMES.get(wd, str(wd)), "weekday": int(wd),
                "mean": round(float(rets[wkdays == wd].mean()), 5),
                "n": int((wkdays == wd).sum()), "p": round(pvals[wd], 4),
                "p_adj": round(adj[wd], 4), "significant": bool(adj[wd] < alpha)}
               for wd in buckets]
    return {"any_significant": any(e["significant"] for e in effects),
            "effects": effects, "overall_mean": round(overall, 5),
            "note": "置换检验 + BH 校正；季节性仅作诊断、不抬升置信度天花板"}
