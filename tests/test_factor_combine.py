"""L3 因子合成（线性基线）单测——脱网纯函数。

范式参照 tests/test_finance_adapter.py：用 importlib.util.spec_from_file_location
直接按文件路径加载被测模块，避免依赖包导入路径/共享注册文件。

被测：services/mcp-tool-service/factor_combine.py
  - equal_weight_combine(clean_by_factor, directions) -> dict
  - ic_weighted_combine(clean_by_factor, rolling_ic, directions) -> dict
返回结构统一：{'scores':[...], 'weights':{...}, 'method':.., 'fallback':bool}
"""
import importlib.util
import math


def _fc():
    s = importlib.util.spec_from_file_location(
        "factor_combine", "services/mcp-tool-service/factor_combine.py"
    )
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


# ----------------------------------------------------------------------------
# 等权合成
# ----------------------------------------------------------------------------
def test_equal_weight_basic_positive_direction():
    """单因子、正方向：合成打分 == 原值（等权 = 自身）。"""
    fc = _fc()
    out = fc.equal_weight_combine({"f1": [1.0, 2.0, 3.0]}, {"f1": "+"})
    assert out["method"] == "equal_weight"
    assert out["fallback"] is False
    assert out["scores"] == [1.0, 2.0, 3.0]
    assert out["weights"] == {"f1": 1.0}


def test_equal_weight_negative_direction_takes_negative():
    """方向 '-' 必须对该因子取负后再平均。"""
    fc = _fc()
    out = fc.equal_weight_combine(
        {"a": [1.0, 2.0, 4.0], "b": [1.0, 2.0, 4.0]},
        {"a": "+", "b": "-"},
    )
    # (a + (-b))/2 = 0 逐元素
    assert out["scores"] == [0.0, 0.0, 0.0]
    # 等权两因子各 0.5
    assert out["weights"] == {"a": 0.5, "b": 0.5}


def test_equal_weight_two_factors_mean():
    """两因子均正方向：逐元素平均。"""
    fc = _fc()
    out = fc.equal_weight_combine(
        {"a": [0.0, 4.0], "b": [2.0, 0.0]}, {"a": "+", "b": "+"}
    )
    assert out["scores"] == [1.0, 2.0]
    assert out["method"] == "equal_weight"


def test_equal_weight_missing_direction_defaults_positive():
    """directions 缺该因子键 → 默认正方向，不崩。"""
    fc = _fc()
    out = fc.equal_weight_combine({"f1": [3.0, -1.0]}, {})
    assert out["scores"] == [3.0, -1.0]


# ----------------------------------------------------------------------------
# NaN 安全（nanmean）
# ----------------------------------------------------------------------------
def test_equal_weight_nan_safe_partial_missing():
    """某因子在某股缺失（NaN）→ 用 nanmean 跳过该缺失，不污染整列。"""
    fc = _fc()
    nan = float("nan")
    out = fc.equal_weight_combine(
        {"a": [2.0, nan], "b": [4.0, 6.0]}, {"a": "+", "b": "+"}
    )
    # 股0: mean(2,4)=3 ; 股1: a 缺 → nanmean(NaN,6)=6
    assert out["scores"][0] == 3.0
    assert out["scores"][1] == 6.0


def test_equal_weight_all_missing_yields_nan():
    """某股在所有因子上全缺 → 该股得分必须是 NaN（绝不编造 0）。"""
    fc = _fc()
    nan = float("nan")
    out = fc.equal_weight_combine(
        {"a": [nan, 1.0], "b": [nan, 3.0]}, {"a": "+", "b": "+"}
    )
    assert math.isnan(out["scores"][0])
    assert out["scores"][1] == 2.0


# ----------------------------------------------------------------------------
# IC 加权合成
# ----------------------------------------------------------------------------
def test_ic_weighted_proportional_and_normalized():
    """w_j ∝ max(0, 方向校正后滚动 mean RankIC)，并归一到和为 1。"""
    fc = _fc()
    out = fc.ic_weighted_combine(
        {"a": [1.0, 0.0], "b": [0.0, 1.0]},
        rolling_ic={"a": 0.06, "b": 0.02},
        directions={"a": "+", "b": "+"},
    )
    assert out["method"] == "ic_weighted"
    assert out["fallback"] is False
    # 权重正比 0.06 : 0.02 = 3:1 → 0.75 / 0.25，归一
    assert abs(out["weights"]["a"] - 0.75) < 1e-9
    assert abs(out["weights"]["b"] - 0.25) < 1e-9
    assert abs(sum(out["weights"].values()) - 1.0) < 1e-9
    # 打分 = 0.75*a + 0.25*b
    assert abs(out["scores"][0] - 0.75) < 1e-9
    assert abs(out["scores"][1] - 0.25) < 1e-9


def test_ic_weighted_direction_corrects_sign_of_ic():
    """方向 '-' 的因子：滚动 IC 用方向校正（取负 IC），负值的因子被截断为 0 权重。

    a: IC=+0.05 方向'+'→ 校正后 +0.05 → 入选
    b: IC=+0.05 方向'-'→ 校正后 -0.05 → max(0,·)=0 → 权重 0
    """
    fc = _fc()
    out = fc.ic_weighted_combine(
        {"a": [1.0, 2.0], "b": [9.0, 9.0]},
        rolling_ic={"a": 0.05, "b": 0.05},
        directions={"a": "+", "b": "-"},
    )
    assert out["fallback"] is False
    assert abs(out["weights"]["a"] - 1.0) < 1e-9
    assert abs(out["weights"]["b"] - 0.0) < 1e-9
    # b 权重 0 → 不影响打分；scores == a
    assert abs(out["scores"][0] - 1.0) < 1e-9
    assert abs(out["scores"][1] - 2.0) < 1e-9


def test_ic_weighted_negative_ic_only_drops_to_zero_weight():
    """方向校正后 IC<=0 的因子权重置 0（只用历史正贡献因子）。"""
    fc = _fc()
    out = fc.ic_weighted_combine(
        {"a": [1.0, 2.0], "b": [3.0, 4.0]},
        rolling_ic={"a": 0.04, "b": -0.10},
        directions={"a": "+", "b": "+"},
    )
    assert out["fallback"] is False
    assert abs(out["weights"]["a"] - 1.0) < 1e-9
    assert abs(out["weights"]["b"] - 0.0) < 1e-9


# ----------------------------------------------------------------------------
# 全负 → 回退等权
# ----------------------------------------------------------------------------
def test_ic_weighted_all_nonpositive_falls_back_to_equal_weight():
    """所有因子方向校正后 RankIC <= 0 → 无法 IC 加权 → 回退等权，fallback=True。"""
    fc = _fc()
    out = fc.ic_weighted_combine(
        {"a": [0.0, 4.0], "b": [2.0, 0.0]},
        rolling_ic={"a": -0.01, "b": -0.20},
        directions={"a": "+", "b": "+"},
    )
    assert out["fallback"] is True
    assert out["method"] == "equal_weight"
    # 退化为等权：逐元素平均
    assert out["scores"] == [1.0, 2.0]
    assert out["weights"] == {"a": 0.5, "b": 0.5}


def test_ic_weighted_missing_rolling_ic_treated_as_zero_then_fallback():
    """rolling_ic 完全缺失（None/空）→ 无历史可加权 → 回退等权。"""
    fc = _fc()
    out = fc.ic_weighted_combine(
        {"a": [1.0, 3.0], "b": [3.0, 1.0]},
        rolling_ic=None,
        directions={"a": "+", "b": "+"},
    )
    assert out["fallback"] is True
    assert out["method"] == "equal_weight"
    assert out["scores"] == [2.0, 2.0]


def test_ic_weighted_nan_safe_in_scores():
    """IC 加权也要 NaN 安全：全缺的股得 NaN，部分缺按存活因子加权。"""
    fc = _fc()
    nan = float("nan")
    out = fc.ic_weighted_combine(
        {"a": [nan, 2.0], "b": [nan, 4.0]},
        rolling_ic={"a": 0.06, "b": 0.02},
        directions={"a": "+", "b": "+"},
    )
    assert out["fallback"] is False
    assert math.isnan(out["scores"][0])  # 股0 全缺
    # 股1: 0.75*2 + 0.25*4 = 2.5
    assert abs(out["scores"][1] - 2.5) < 1e-9


# ----------------------------------------------------------------------------
# 弃权 / 不崩：空输入、形状不一致
# ----------------------------------------------------------------------------
def test_empty_panel_abstains_not_crash():
    """空 panel → 弃权返回空 scores，不抛异常。"""
    fc = _fc()
    eq = fc.equal_weight_combine({}, {})
    assert eq["scores"] == []
    assert eq["weights"] == {}
    icw = fc.ic_weighted_combine({}, {}, {})
    assert icw["scores"] == []
    assert icw["weights"] == {}


def test_shape_mismatch_abstains_not_crash():
    """因子向量长度不一致 → 弃权（abstain）而非崩溃。"""
    fc = _fc()
    out = fc.equal_weight_combine(
        {"a": [1.0, 2.0, 3.0], "b": [1.0, 2.0]}, {"a": "+", "b": "+"}
    )
    assert out["scores"] == []
    assert out.get("fallback") in (True, False)
    out2 = fc.ic_weighted_combine(
        {"a": [1.0, 2.0, 3.0], "b": [1.0, 2.0]},
        rolling_ic={"a": 0.05, "b": 0.05},
        directions={"a": "+", "b": "+"},
    )
    assert out2["scores"] == []
