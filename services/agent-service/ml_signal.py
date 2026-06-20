"""XGBoost 弱信号校准器（不是预测器）。

回答："在相似技术形态/量价/波动下，历史 T+1 上涨概率是否高于基准？"
- 特征仅用截至 T 日数据（杜绝未来函数）。
- 时间切分（非随机）+ 概率校准（Platt/sigmoid）+ 样本外 AUC。
- 弃权机制：样本不足 / AUC≈0.5 / 特征异常 → 不输出方向。
- 可解释：feature_importance。
重库（xgboost/sklearn）惰性导入，便于无依赖环境下 import 本模块。
"""
import numpy as np

FEATURE_NAMES = ["ret_lag1", "ret_lag2", "ret_lag3", "ma5_dev", "ma20_dev",
                 "rsi14", "volatility", "vol_ratio", "abs_ret_lag1", "vol5_over_vol20"]


def _rsi(closes, n=14):
    if len(closes) < n + 1:
        return 50.0
    d = np.diff(closes[-(n + 1):])
    up = d[d > 0].sum()
    dn = -d[d < 0].sum()
    if dn == 0:
        return 100.0
    rs = (up / n) / (dn / n)
    return float(100 - 100 / (1 + rs))


def build_features(kline):
    """从 K 线（OHLCV dict 列表，时间升序）构造截至最后一日的特征向量。"""
    closes = np.array([r["close"] for r in kline], dtype=float)
    vols = np.array([r.get("volume", 0) or 0 for r in kline], dtype=float)
    if len(closes) < 21:
        return None
    rets = np.diff(closes) / closes[:-1]
    ma5 = closes[-5:].mean()
    ma20 = closes[-20:].mean()
    vol5 = float(np.std(rets[-5:]))
    vol20 = float(np.std(rets[-20:]))
    feat = [
        rets[-1], rets[-2], rets[-3],
        (closes[-1] - ma5) / ma5,
        (closes[-1] - ma20) / ma20,
        _rsi(closes) / 100.0,
        vol20,
        float(vols[-1] / (vols[-6:-1].mean() or 1)) if len(vols) >= 6 else 1.0,
        abs(float(rets[-1])),                       # 昨日绝对涨幅（波动聚集的直接信号）
        vol5 / (vol20 + 1e-9),                       # 短/长期波动比（波动是否正在放大）
    ]
    if any(np.isnan(feat)) or any(np.isinf(feat)):
        return None
    return feat


def build_dataset(kline):
    """滚动构造 (X, y)：预测「次日是否为大波动日」(|次日收益| 超过近 60 日 70 分位)。

    为何换成波动目标：短周期"涨跌方向"接近随机(AUC≈0.5)，而**波动具有聚集性**
    (volatility clustering，GARCH 效应)——今天波动大，明天大概率仍大——这是可学习的。
    特征仅用截至 T 日数据；阈值用过去窗口，均无未来函数。
    """
    closes = np.array([r["close"] for r in kline], dtype=float)
    if len(closes) < 3:
        return np.array([]), np.array([])
    rets = np.diff(closes) / closes[:-1]
    aret = np.abs(rets)
    X, y = [], []
    for i in range(21, len(kline) - 1):
        f = build_features(kline[:i + 1])
        if f is None:
            continue
        window = aret[max(0, i - 60):i]  # 仅过去窗口
        if len(window) < 20:
            continue
        thr = float(np.quantile(window, 0.7))
        X.append(f)
        y.append(1 if aret[i] > thr else 0)  # aret[i]=|ret(i->i+1)|，相对 day i 为"次日"
    return np.array(X), np.array(y)


def _make_calibrated():
    from sklearn.calibration import CalibratedClassifierCV
    from xgboost import XGBClassifier
    base = XGBClassifier(n_estimators=60, max_depth=3, learning_rate=0.1,
                         eval_metric="logloss", verbosity=0)
    return CalibratedClassifierCV(base, method="sigmoid", cv=3)  # Platt 校准


def walk_forward_auc(X, y, groups=None, embargo=3, test_frac=0.3):
    """**按标的(group)内时间序**做留出：训练池=各标的早期(1-test_frac)，
    测试池=各标的近期 test_frac（组内测试严格晚于训练，无未来泄漏）；带 embargo
    禁运隔离 T+1 标签重叠。在全训练池拟合一次，对汇集的样本外测试集打分。

    替代原"跨标的 70/30"切分（vstack 后实为跨标的泄漏）。训练用满数据(更公平)、
    评估在样本外(更诚实)。返回 {auc(pooled OOS), fold_aucs(逐标的诊断), fold_auc_std, oos_prob, n_oos}。
    """
    from sklearn.metrics import roc_auc_score
    X = np.asarray(X, dtype=float)
    y = np.asarray(y)
    n = len(X)
    groups = np.zeros(n, dtype=int) if groups is None else np.asarray(groups)
    tr_all, te_groups = [], []  # te_groups: list[(g, te_idx)]
    for g in np.unique(groups):
        idx = np.where(groups == g)[0]  # 组内按时间升序（build_dataset 即如此）
        ng = len(idx)
        if ng < 40:
            continue
        cut = int(ng * (1 - test_frac))
        tr_all.extend(idx[:max(1, cut - embargo)].tolist())
        te_groups.append((g, idx[cut:]))
    te_all = [int(i) for _, te in te_groups for i in te]
    if len(tr_all) < 60 or len(te_all) < 20 \
            or len(set(y[tr_all].tolist())) < 2 or len(set(y[te_all].tolist())) < 2:
        return {"auc": None, "fold_aucs": [], "fold_auc_std": None, "oos_prob": [],
                "n_oos": len(te_all)}
    clf = _make_calibrated()
    clf.fit(X[tr_all], y[tr_all])
    prob_te = clf.predict_proba(X[te_all])[:, 1]
    pooled_auc = float(roc_auc_score(y[te_all], prob_te))
    # 逐标的样本外 AUC（诊断：稳定性 / 是否仅个别标的贡献）
    fold_aucs = []
    for g, te in te_groups:
        if len(te) < 5 or len(set(y[te].tolist())) < 2:
            continue
        pg = clf.predict_proba(X[te])[:, 1]
        try:
            fold_aucs.append(float(roc_auc_score(y[te], pg)))
        except ValueError:
            pass
    return {"auc": pooled_auc, "fold_aucs": fold_aucs,
            "fold_auc_std": float(np.std(fold_aucs)) if fold_aucs else None,
            "oos_prob": [float(v) for v in prob_te], "n_oos": len(te_all)}


def permutation_null_auc(X, y, groups=None, n_perm=20, seed=42):
    """随机游走零假设：打乱标签后重复 walk-forward，得到"无信息"AUC 分布。

    用于诚实地回答"该 AUC 是否优于随机"。返回 {null_mean, null_std, n_perm}。
    """
    y = np.asarray(y)
    rng = np.random.RandomState(seed)
    aucs = []
    for _ in range(n_perm):
        yp = rng.permutation(y)
        wf = walk_forward_auc(X, yp, groups)
        if wf["auc"] is not None:
            aucs.append(wf["auc"])
    if not aucs:
        return {"null_mean": None, "null_std": None, "n_perm": 0}
    return {"null_mean": float(np.mean(aucs)), "null_std": float(np.std(aucs)),
            "n_perm": int(n_perm)}


def train(X, y, groups=None):
    """purged walk-forward 训练评估 + 全量校准模型 + 样本外概率分位。

    返回 metrics（含 model 对象用于保存；auc 为 pooled OOS AUC，更诚实）。
    """
    from xgboost import XGBClassifier
    n = len(X)
    if n < 200:
        return {"auc": None, "baseline": 0.5, "abstain": True,
                "abstain_reason": "样本不足(<200)", "feature_importance": None,
                "fold_aucs": [], "prob_quantiles": None, "model": None}
    wf = walk_forward_auc(X, y, groups)
    auc = wf["auc"] if wf["auc"] is not None else 0.5
    abstain = auc < 0.55
    # 推理用模型：全量数据上拟合（评估已由 walk-forward 在样本外完成）
    clf = _make_calibrated()
    clf.fit(X, y)
    imp_model = XGBClassifier(n_estimators=60, max_depth=3, eval_metric="logloss", verbosity=0)
    imp_model.fit(X, y)
    imp = dict(zip(FEATURE_NAMES, [float(v) for v in imp_model.feature_importances_]))
    # 分位来自**样本外**池化概率（数据驱动的 R7/风险分级阈值）；缺失时回退全量预测
    src = wf["oos_prob"] if wf["oos_prob"] else clf.predict_proba(X)[:, 1].tolist()
    quantiles = {"q_elevated": float(np.quantile(src, 0.70)),
                 "q_extreme": float(np.quantile(src, 0.85))}
    return {"auc": auc, "baseline": 0.5, "abstain": bool(abstain),
            "abstain_reason": "AUC≈0.5(无统计优势)" if abstain else None,
            "feature_importance": imp, "fold_aucs": wf["fold_aucs"],
            "fold_auc_std": wf["fold_auc_std"], "n_oos": wf["n_oos"],
            "prob_quantiles": quantiles, "model": clf}


def save_model(metrics, path):
    import pickle
    with open(path, "wb") as f:
        pickle.dump({"model": metrics.get("model"), "auc": metrics.get("auc"),
                     "abstain": metrics.get("abstain"),
                     "feature_importance": metrics.get("feature_importance"),
                     "prob_quantiles": metrics.get("prob_quantiles")}, f)


class SignalCalibrator:
    def __init__(self, model=None, auc=None, abstain=True, importance=None, reason="无模型",
                 quantiles=None):
        self.model = model
        self.auc = auc
        self.abstain_default = abstain
        self.importance = importance
        self.reason = reason
        self.quantiles = quantiles or {}

    @classmethod
    def load(cls, path):
        import pickle
        try:
            with open(path, "rb") as f:
                d = pickle.load(f)
            ab = bool(d.get("abstain") or d.get("model") is None)
            return cls(d.get("model"), d.get("auc"), ab, d.get("feature_importance"),
                       "AUC≈0.5" if ab else "", d.get("prob_quantiles"))
        except Exception:
            return cls(reason="模型文件缺失")

    def predict(self, features):
        """返回 prob_big_move：次日为"大波动日"的校准概率（非涨跌方向）。

        附带模型自身经验分位 q_elevated/q_extreme（若已训练），供治理 R7 与委员风险分级
        用作数据驱动阈值；旧模型无分位时下游回退绝对阈值。
        """
        q = self.quantiles or {}
        if self.model is None or self.abstain_default or features is None:
            return {"prob_big_move": None, "abstain": True,
                    "abstain_reason": self.reason or "模型弃权",
                    "auc": self.auc, "feature_importance": self.importance,
                    "q_elevated": q.get("q_elevated"), "q_extreme": q.get("q_extreme")}
        prob = float(self.model.predict_proba([features])[0][1])
        return {"prob_big_move": prob, "abstain": False, "abstain_reason": None,
                "auc": self.auc, "feature_importance": self.importance,
                "q_elevated": q.get("q_elevated"), "q_extreme": q.get("q_extreme")}
