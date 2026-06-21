"""L3 横截面 ML 诚实层（agent-service / py3.12，与 ml_signal 同栈）。

两个诚实关键件（训练管线 train_xsec 是其薄包装）：
1. promote_then_prove：ML 只有在 purged-CV OOS RankIC 严格优于线性基线（块自助 CI 下界>0）时才接管，
   否则弃权回退线性基线 —— 杜绝"in-sample 好就用"。
2. 工件版本契约：ML pickle 随 artifact_meta；加载侧环境不一致 → model_load_failed（绝不伪装成统计弃权）。
"""
import numpy as np


def promote_then_prove(ml_ic_series, baseline_ic_series, n_boot=1000, seed=42, alpha=0.05,
                       min_folds=5):
    """ML(OOS RankIC) − 基线(OOS RankIC) 的块自助 CI 下界 >0 才启用 ML。"""
    ml = np.asarray(ml_ic_series, dtype=float)
    base = np.asarray(baseline_ic_series, dtype=float)
    n = min(len(ml), len(base))
    if n < min_folds:
        return {"enable_ml": False, "abstain_reason": "insufficient_history",
                "mean_diff": None, "ci_low": None, "n_folds": int(n)}
    diff = ml[:n] - base[:n]
    rng = np.random.RandomState(seed)
    block = max(2, int(round(np.sqrt(n))))
    n_blocks = int(np.ceil(n / block))
    means = np.empty(n_boot)
    for b in range(n_boot):
        starts = rng.randint(0, n, size=n_blocks)
        idx = np.concatenate([(s + np.arange(block)) % n for s in starts])[:n]
        means[b] = diff[idx].mean()
    ci_low = float(np.quantile(means, alpha / 2))
    enable = bool(ci_low > 0)
    return {"enable_ml": enable, "mean_diff": round(float(diff.mean()), 5),
            "ci_low": round(ci_low, 5),
            "abstain_reason": None if enable else "statistical_abstain", "n_folds": int(n)}


def artifact_meta():
    """ML pickle 随包写入的环境指纹（跨容器/跨版本加载校验）。"""
    import sys
    import sklearn
    meta = {"python_version": f"{sys.version_info.major}.{sys.version_info.minor}",
            "sklearn_version": sklearn.__version__, "numpy_version": np.__version__}
    try:
        import xgboost
        meta["xgboost_version"] = xgboost.__version__
    except Exception:  # noqa: BLE001
        meta["xgboost_version"] = None
    return meta


def check_artifact(meta, current=None):
    """校验工件环境与运行环境一致；不一致 → model_load_failed（非 statistical_abstain）。"""
    cur = current or artifact_meta()
    mismatch = [k for k in ("python_version", "sklearn_version")
                if meta.get(k) != cur.get(k)]
    return {"ok": not mismatch, "mismatch": mismatch,
            "abstain_reason": None if not mismatch else "model_load_failed"}
