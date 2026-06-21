"""L1 另类/风险闸因子（spec §5.5/§5.6）纯函数脱网单测。

覆盖每因子：正常 + 弃权(空/0方差/不足) + risk_gate 阈值。
按 test_finance_adapter.py 范式用 importlib.util.spec_from_file_location 加载被测模块。
诚实约束：数据/方差不足 → None（弃权），绝不编造；风险闸只降权（direction='risk_gate'）。
"""
import importlib.util

import numpy as np


def _af():
    s = importlib.util.spec_from_file_location("af", "services/mcp-tool-service/altfactors.py")
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


# ---------------------------------------------------------------- PEAD / SUE
def test_pead_sue_normal():
    af = _af()
    # SUE = (actual - expected) / std_hist = (1.5 - 1.0) / 0.25 = 2.0
    v = af.pead_sue(1.5, 1.0, 0.25)
    assert abs(v - 2.0) < 1e-9


def test_pead_sue_negative_surprise():
    af = _af()
    # 不及预期 → 负 SUE
    v = af.pead_sue(0.8, 1.0, 0.5)
    assert v < 0


def test_pead_sue_zero_std_abstains():
    af = _af()
    # std_hist=0 → 不可标准化 → 弃权(None)，绝不除零编造
    assert af.pead_sue(1.5, 1.0, 0.0) is None


def test_pead_sue_none_inputs_abstain():
    af = _af()
    assert af.pead_sue(None, 1.0, 0.25) is None
    assert af.pead_sue(1.5, None, 0.25) is None
    assert af.pead_sue(1.5, 1.0, None) is None


def test_pead_sue_direction():
    af = _af()
    assert af.FACTOR_DIRECTIONS["pead_sue"] == "+"


# ---------------------------------------------------------------- EPS revision
def test_eps_revision_unscaled_recent_above_far():
    af = _af()
    # 近端均值 > 远端均值 → 上修 → 正；绝不除当期 EPS/股价
    estimates = [1.0, 1.0, 1.2, 1.4]   # 远端低、近端高
    v = af.eps_revision(estimates)
    assert v is not None and v > 0


def test_eps_revision_downward():
    af = _af()
    estimates = [1.5, 1.4, 1.0, 0.8]   # 下修 → 负
    v = af.eps_revision(estimates)
    assert v is not None and v < 0


def test_eps_revision_value_is_unscaled_difference():
    af = _af()
    # 半窗划分：远端均值 vs 近端均值之差，未除以当期 EPS（Jung 2019）
    estimates = [2.0, 2.0, 3.0, 3.0]   # 远端均值=2.0, 近端均值=3.0 → 差=1.0
    v = af.eps_revision(estimates)
    assert abs(v - 1.0) < 1e-9


def test_eps_revision_insufficient_abstains():
    af = _af()
    assert af.eps_revision([]) is None
    assert af.eps_revision([1.0]) is None          # 不足以分近/远端
    assert af.eps_revision(None) is None


def test_eps_revision_direction():
    af = _af()
    assert af.FACTOR_DIRECTIONS["eps_revision"] == "+"


# ---------------------------------------------------------------- Chip (股东户数)
def test_chip_factor_concentration_bullish():
    af = _af()
    # 户数下降 = 筹码集中 = 看多 → Chip = -Δln(户数) > 0
    counts = [100000, 90000, 80000]
    v = af.chip_factor(counts)
    assert v is not None and v > 0


def test_chip_factor_dispersion_bearish():
    af = _af()
    counts = [80000, 90000, 100000]   # 户数增加=分散 → 负
    v = af.chip_factor(counts)
    assert v is not None and v < 0


def test_chip_factor_value():
    af = _af()
    # -Δln：用首尾 -ln(end/start) = -ln(80000/100000)
    counts = [100000, 80000]
    v = af.chip_factor(counts)
    assert abs(v - (-np.log(80000 / 100000))) < 1e-9


def test_chip_factor_abstain():
    af = _af()
    assert af.chip_factor([]) is None
    assert af.chip_factor([100000]) is None        # 不足两期无法差分
    assert af.chip_factor(None) is None
    assert af.chip_factor([0, 80000]) is None       # 户数=0 → ln 不可计算 → 弃权
    assert af.chip_factor([100000, 0]) is None


def test_chip_factor_direction():
    af = _af()
    assert af.FACTOR_DIRECTIONS["chip_factor"] == "+"


# ---------------------------------------------------------------- Northbound flow
def test_northbound_flow_normal_standardized():
    af = _af()
    # 末期净流入显著高于历史均值 → 标准化后为正
    flows = [0.0, 0.0, 0.0, 0.0, 5.0]
    v = af.northbound_flow(flows)
    assert v is not None and v > 0


def test_northbound_flow_below_mean_negative():
    af = _af()
    flows = [5.0, 5.0, 5.0, 5.0, -5.0]
    v = af.northbound_flow(flows)
    assert v is not None and v < 0


def test_northbound_flow_zero_variance_abstains():
    af = _af()
    # 全相同 → std=0 → 无法标准化 → 弃权
    assert af.northbound_flow([3.0, 3.0, 3.0, 3.0]) is None


def test_northbound_flow_empty_abstains():
    af = _af()
    assert af.northbound_flow([]) is None
    assert af.northbound_flow(None) is None
    assert af.northbound_flow([1.0]) is None        # 单点无方差


def test_northbound_flow_direction():
    af = _af()
    assert af.FACTOR_DIRECTIONS["northbound_flow"] == "+"


def test_northbound_flow_regime_break_noted():
    af = _af()
    # 2024-08 口径变更点应作为模块级注记可被发现
    assert "2024-08" in af.NORTHBOUND_REGIME_BREAKS


# ---------------------------------------------------------------- Pledge risk gate
def test_pledge_gate_high():
    af = _af()
    out = af.pledge_risk_gate(0.6)   # >0.5
    assert out["direction"] == "risk_gate"
    assert out["flag"] == "high"


def test_pledge_gate_normal():
    af = _af()
    out = af.pledge_risk_gate(0.3)
    assert out["direction"] == "risk_gate"
    assert out["flag"] == "normal"


def test_pledge_gate_threshold_boundary():
    af = _af()
    # 阈值是严格 >0.5：恰好 0.5 仍为 normal
    assert af.pledge_risk_gate(0.5)["flag"] == "normal"
    assert af.pledge_risk_gate(0.51)["flag"] == "high"


def test_pledge_gate_score_only_downweights():
    af = _af()
    # 风险闸只降权：高质押 score 不应为正 alpha（<=0 的降权语义）
    high = af.pledge_risk_gate(0.8)
    assert high["score"] <= 0
    normal = af.pledge_risk_gate(0.1)
    assert high["score"] <= normal["score"]


def test_pledge_gate_abstain():
    af = _af()
    out = af.pledge_risk_gate(None)
    assert out is None or out.get("flag") == "unknown"


def test_pledge_gate_direction_registry():
    af = _af()
    assert af.FACTOR_DIRECTIONS["pledge_risk_gate"] == "risk_gate"


# ---------------------------------------------------------------- Restricted release gate
def test_restricted_release_high_risk():
    af = _af()
    # 临近(天数小) + 大额(比例高) → high risk
    out = af.restricted_release_gate(days_to_release=5, release_ratio=0.3)
    assert out["direction"] == "risk_gate"
    assert out["flag"] == "high"


def test_restricted_release_far_or_small_normal():
    af = _af()
    far = af.restricted_release_gate(days_to_release=200, release_ratio=0.3)
    assert far["flag"] == "normal"
    small = af.restricted_release_gate(days_to_release=5, release_ratio=0.001)
    assert small["flag"] == "normal"


def test_restricted_release_score_downweights():
    af = _af()
    out = af.restricted_release_gate(days_to_release=3, release_ratio=0.5)
    assert out["score"] <= 0


def test_restricted_release_abstain():
    af = _af()
    out = af.restricted_release_gate(None, 0.3)
    assert out is None or out.get("flag") == "unknown"
    out2 = af.restricted_release_gate(5, None)
    assert out2 is None or out2.get("flag") == "unknown"


def test_restricted_release_direction_registry():
    af = _af()
    assert af.FACTOR_DIRECTIONS["restricted_release_gate"] == "risk_gate"


# ---------------------------------------------------------------- registry coherence
def test_factor_directions_complete():
    af = _af()
    expected = {"pead_sue", "eps_revision", "chip_factor", "northbound_flow",
                "pledge_risk_gate", "restricted_release_gate"}
    assert expected.issubset(set(af.FACTOR_DIRECTIONS))
    for d in af.FACTOR_DIRECTIONS.values():
        assert d in ("+", "-", "risk_gate")
