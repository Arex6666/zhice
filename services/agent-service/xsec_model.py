"""L3 横截面 ML 诚实层（agent-service / py3.12，与 ml_signal 同栈）。

两个诚实关键件（训练管线 train_xsec 是其薄包装）：
1. promote_then_prove：ML 只有在 purged-CV OOS RankIC 严格优于线性基线（块自助 CI 下界>0）时才接管，
   否则弃权回退线性基线 —— 杜绝"in-sample 好就用"。
2. 工件版本契约：ML pickle 随 artifact_meta；加载侧环境不一致 → model_load_failed（绝不伪装成统计弃权）。
"""
import numpy as np


class ArtifactContractError(RuntimeError):
    """ML 工件环境指纹与运行环境不一致（跨容器/跨版本 pickle 不可信）。"""


def _make_gbdt(max_depth, n_estimators, learning_rate, reg_lambda, subsample, seed):
    """浅层 GBDT 后端：优先 xgboost(spec 默认)，缺失回退 sklearn GradientBoosting（标 model_class）。"""
    try:
        from xgboost import XGBRegressor
        return XGBRegressor(max_depth=max_depth, n_estimators=n_estimators,
                            learning_rate=learning_rate, reg_lambda=reg_lambda,
                            subsample=subsample, min_child_weight=5, random_state=seed,
                            n_jobs=1, objective="reg:squarederror"), "xgboost.XGBRegressor"
    except Exception:  # noqa: BLE001 - 环境无 xgboost → sklearn 回退
        from sklearn.ensemble import GradientBoostingRegressor
        return GradientBoostingRegressor(max_depth=max_depth, n_estimators=n_estimators,
                                         learning_rate=learning_rate, subsample=subsample,
                                         random_state=seed), "sklearn.GradientBoostingRegressor"


class XSecRanker:
    """横截面 GBDT 排序器（GKX：浅树 max_depth 3–5 + 强正则）。

    训练目标为未来收益，预测分用于截面排序。pickle 随包写 sidecar artifact_meta.json，
    加载侧强制校验环境一致（§3.3 工件契约）；不一致抛 ArtifactContractError / 软接口 model_load_failed。
    """

    def __init__(self, max_depth=4, n_estimators=200, learning_rate=0.05, reg_lambda=1.0,
                 subsample=0.8, seed=42):
        self.params = dict(max_depth=max_depth, n_estimators=n_estimators,
                           learning_rate=learning_rate, reg_lambda=reg_lambda,
                           subsample=subsample, seed=seed)
        self.model = None
        self.model_class = None
        self.feature_names = None

    def fit(self, X, y, feature_names=None, eval_set=None):
        X = np.asarray(X, dtype=float)
        y = np.asarray(y, dtype=float)
        self.feature_names = list(feature_names) if feature_names is not None \
            else [f"f{i}" for i in range(X.shape[1])]
        self.model, self.model_class = _make_gbdt(**self.params)
        # early stopping 仅当显式给 eval_set 且后端支持；否则常规拟合（保持可移植）
        try:
            if eval_set is not None and "xgboost" in self.model_class:
                self.model.fit(X, y, eval_set=eval_set, verbose=False)
            else:
                self.model.fit(X, y)
        except TypeError:
            self.model.fit(X, y)
        return self

    def predict(self, X):
        if self.model is None:
            raise RuntimeError("model not fitted")
        return self.model.predict(np.asarray(X, dtype=float))

    def predict_scores(self, clean_by_factor):
        """按 self.feature_names 从 clean 因子 dict 组装 X 再预测；缺任一因子列 → None(弃权)。"""
        if self.feature_names is None:
            return None
        if any(f not in clean_by_factor for f in self.feature_names):
            return None
        cols = [np.asarray(clean_by_factor[f], dtype=float) for f in self.feature_names]
        n = min(len(c) for c in cols)
        X = np.column_stack([c[:n] for c in cols])
        return list(map(float, self.predict(X)))

    def _meta(self):
        names = self.feature_names or []
        h = hash(tuple(names)) & 0xFFFFFFFF
        return {**artifact_meta(), "model_class": self.model_class,
                "feature_names": names, "feature_names_hash": h, "params": self.params}

    def save(self, path):
        import json
        import pickle
        with open(path, "wb") as f:
            pickle.dump({"model": self.model, "model_class": self.model_class,
                         "feature_names": self.feature_names, "params": self.params}, f)
        with open(path + ".meta.json", "w", encoding="utf-8") as f:
            json.dump(self._meta(), f, ensure_ascii=False, indent=2)
        return path

    @classmethod
    def load(cls, path, current_env=None):
        """加载 pickle + 校验 sidecar 环境契约；不一致 → ArtifactContractError。"""
        import json
        import pickle
        with open(path + ".meta.json", encoding="utf-8") as f:
            meta = json.load(f)
        chk = check_artifact(meta, current_env)
        if not chk["ok"]:
            raise ArtifactContractError(f"artifact env mismatch: {chk['mismatch']}")
        with open(path, "rb") as f:
            blob = pickle.load(f)
        obj = cls(**{k: v for k, v in (blob.get("params") or {}).items()})
        obj.model = blob["model"]
        obj.model_class = blob.get("model_class")
        obj.feature_names = blob.get("feature_names")
        return obj

    @classmethod
    def load_or_abstain(cls, path, current_env=None):
        """软加载：契约不过/文件缺失 → {model:None, abstain_reason}，绝不静默降级。"""
        try:
            return {"model": cls.load(path, current_env=current_env), "abstain_reason": None}
        except ArtifactContractError:
            return {"model": None, "abstain_reason": "model_load_failed"}
        except (FileNotFoundError, OSError):
            return {"model": None, "abstain_reason": "model_load_failed"}


def load_or_abstain(path, current_env=None):
    """模块级软加载入口（finance_agent 推理侧用）。"""
    return XSecRanker.load_or_abstain(path, current_env=current_env)


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
