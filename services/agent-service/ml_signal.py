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
                 "rsi14", "volatility", "vol_ratio"]


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
    feat = [
        rets[-1], rets[-2], rets[-3],
        (closes[-1] - ma5) / ma5,
        (closes[-1] - ma20) / ma20,
        _rsi(closes) / 100.0,
        float(np.std(rets[-20:])),
        float(vols[-1] / (vols[-6:-1].mean() or 1)) if len(vols) >= 6 else 1.0,
    ]
    if any(np.isnan(feat)) or any(np.isinf(feat)):
        return None
    return feat


def build_dataset(kline):
    """滚动构造 (X, y)：每个窗口的特征 + 次日涨跌标签（仅用历史，无未来函数）。"""
    closes = [r["close"] for r in kline]
    X, y = [], []
    for i in range(21, len(kline) - 1):
        f = build_features(kline[:i + 1])
        if f is None:
            continue
        X.append(f)
        y.append(1 if closes[i + 1] > closes[i] else 0)
    return np.array(X), np.array(y)


def train(X, y):
    """时间切分训练 + 校准 + 样本外 AUC。返回 metrics（含 model 对象用于保存）。"""
    n = len(X)
    if n < 200:
        return {"auc": None, "baseline": 0.5, "abstain": True,
                "abstain_reason": "样本不足(<200)", "feature_importance": None, "model": None}
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.metrics import roc_auc_score
    from xgboost import XGBClassifier

    cut = int(n * 0.7)
    Xtr, Xte, ytr, yte = X[:cut], X[cut:], y[:cut], y[cut:]
    base = XGBClassifier(n_estimators=60, max_depth=3, learning_rate=0.1,
                         eval_metric="logloss", verbosity=0)
    clf = CalibratedClassifierCV(base, method="sigmoid", cv=3)  # Platt 校准
    clf.fit(Xtr, ytr)
    proba = clf.predict_proba(Xte)[:, 1]
    try:
        auc = float(roc_auc_score(yte, proba))
    except ValueError:
        auc = 0.5
    abstain = auc < 0.55
    imp_model = XGBClassifier(n_estimators=60, max_depth=3, eval_metric="logloss", verbosity=0)
    imp_model.fit(X, y)
    imp = dict(zip(FEATURE_NAMES, [float(v) for v in imp_model.feature_importances_]))
    return {"auc": auc, "baseline": 0.5, "abstain": bool(abstain),
            "abstain_reason": "AUC≈0.5(无统计优势)" if abstain else None,
            "feature_importance": imp, "model": clf}


def save_model(metrics, path):
    import pickle
    with open(path, "wb") as f:
        pickle.dump({"model": metrics.get("model"), "auc": metrics.get("auc"),
                     "abstain": metrics.get("abstain"),
                     "feature_importance": metrics.get("feature_importance")}, f)


class SignalCalibrator:
    def __init__(self, model=None, auc=None, abstain=True, importance=None, reason="无模型"):
        self.model = model
        self.auc = auc
        self.abstain_default = abstain
        self.importance = importance
        self.reason = reason

    @classmethod
    def load(cls, path):
        import pickle
        try:
            with open(path, "rb") as f:
                d = pickle.load(f)
            ab = bool(d.get("abstain") or d.get("model") is None)
            return cls(d.get("model"), d.get("auc"), ab, d.get("feature_importance"),
                       "AUC≈0.5" if ab else "")
        except Exception:
            return cls(reason="模型文件缺失")

    def predict(self, features):
        if self.model is None or self.abstain_default or features is None:
            return {"prob_up": None, "abstain": True,
                    "abstain_reason": self.reason or "模型弃权",
                    "auc": self.auc, "feature_importance": self.importance}
        prob = float(self.model.predict_proba([features])[0][1])
        return {"prob_up": prob, "abstain": False, "abstain_reason": None,
                "auc": self.auc, "feature_importance": self.importance}
