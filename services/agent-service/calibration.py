"""校准自审（纯函数，仅依赖 numpy）。

把"命中率"升级为真正的概率校准评估：Brier 分数、ECE(期望校准误差)、可靠性分箱，
并据 平均置信度 vs 实际命中率 的系统性偏差判定 过度自信/欠自信/校准良好。
仅用于自评与可视化，**不**自动改动治理天花板（保持治理规则的确定性）。
"""
import numpy as np


def assess(points, bins=10):
    """points: list[(confidence∈[0,1], correct∈{0,1})]。样本为空返回 None。"""
    pts = [(float(c), int(o)) for c, o in (points or [])
           if c is not None and o is not None]
    if not pts:
        return None
    confs = np.array([p[0] for p in pts], dtype=float)
    outs = np.array([p[1] for p in pts], dtype=float)
    n = len(pts)

    brier = float(np.mean((confs - outs) ** 2))

    edges = np.linspace(0.0, 1.0, bins + 1)
    reliability = []
    ece = 0.0
    for i in range(bins):
        lo, hi = edges[i], edges[i + 1]
        mask = (confs >= lo) & (confs <= hi) if i == bins - 1 else (confs >= lo) & (confs < hi)
        k = int(mask.sum())
        if k == 0:
            continue
        avg_conf = float(confs[mask].mean())
        acc = float(outs[mask].mean())
        ece += (k / n) * abs(avg_conf - acc)
        reliability.append({"lo": round(float(lo), 2), "hi": round(float(hi), 2),
                            "n": k, "avg_conf": round(avg_conf, 3), "accuracy": round(acc, 3)})

    mean_conf = float(confs.mean())
    accuracy = float(outs.mean())
    gap = mean_conf - accuracy
    verdict = "过度自信" if gap > 0.1 else ("欠自信" if gap < -0.1 else "校准良好")
    return {"brier": round(brier, 4), "ece": round(ece, 4), "reliability": reliability,
            "mean_confidence": round(mean_conf, 3), "accuracy": round(accuracy, 3),
            "gap": round(gap, 3), "verdict": verdict, "n": n}
