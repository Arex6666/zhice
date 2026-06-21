"""L1 另类/风险闸因子（纯函数, spec §5.5/§5.6）。

均为**纯函数核心**：接收已取好的序列/数值（真实 akshare 网络调用放薄包装层，不在此），
可脱网单测。诚实约束：数据/历史/方差不足 → 返回 None（弃权），**绝不编造**（不除零、不伪造分布）。
所有因子均为 forward_pit_only（北向/EPS修正/PEAD/股东户数）——冷启动 history_depth<252
强制弃权（with_pit_guard）；绝不用今日快照回填历史。

方向语义（FACTOR_DIRECTIONS）：
  '+'         分数越大越看多
  '-'         分数越大越看空
  'risk_gate' 风险闸，**只降权不产 alpha**（score<=0），不作方向证据。
"""
import numpy as np

MIN_HISTORY = 252

# 北向口径变更点（regime break）：跨此点的差分/标准化语义不连续，应弃权或分段。
# 2024-08 起沪深港通对个股持股明细的披露口径调整（见 spec §5.5 caveat）。
NORTHBOUND_REGIME_BREAKS = ["2024-08"]


# ----------------------------------------------------------------- PEAD / SUE
def pead_sue(actual, expected, std_hist):
    """PEAD 标准化盈余惊喜 SUE = (actual − expected) / std_hist。

    actual=真预告/快报净利中值, expected=一致预期, std_hist=历史净利标准差。
    std_hist=0（或不足 1e-12）→ 无法标准化 → None（弃权，绝不除零编造）。
    任一输入缺失 → None。方向 '+'（正惊喜→看多，PEAD 漂移）。
    """
    if actual is None or expected is None or std_hist is None:
        return None
    std = float(std_hist)
    if abs(std) < 1e-12:
        return None
    return (float(actual) - float(expected)) / std


# ----------------------------------------------------------------- EPS revision
def eps_revision(eps_estimates):
    """EPS 修正 = 近端均值 − 远端均值（Jung 2019：**未缩放或滞后均值缩放**）。

    eps_estimates 为按时间升序的一致预期 EPS 序列。把序列对半分（远端在前、近端在后），
    取 (近端均值 − 远端均值) 作为修正方向与幅度。**绝不除以当期 EPS 或股价**——
    Jung(2019) 指出常见的"除当期 EPS/股价"缩放会使因子失效，故此处只做未缩放差分。
    序列为空/None/不足 2 点（无法分近/远端）→ None（弃权）。方向 '+'（上修→看多）。
    """
    if eps_estimates is None:
        return None
    arr = np.asarray(eps_estimates, dtype=float)
    if arr.size < 2 or not np.all(np.isfinite(arr)):
        return None
    mid = arr.size // 2
    far = arr[:mid]          # 远端（较早）
    recent = arr[mid:]       # 近端（较新）
    return float(recent.mean() - far.mean())


# ----------------------------------------------------------------- Chip 股东户数
def chip_factor(holder_counts):
    """筹码集中 Chip = −Δln(户数)（户数减少=集中=看多）。

    holder_counts 为按时间升序的股东户数序列；用首尾两端的对数差：
        Chip = −(ln(end) − ln(start)) = ln(start) − ln(end)
    户数下降 → ln(end)<ln(start) → Chip>0（集中，看多）。
    空/None/不足两期/含非正户数（ln 不可计算）→ None（弃权）。方向 '+'。
    """
    if holder_counts is None:
        return None
    arr = np.asarray(holder_counts, dtype=float)
    if arr.size < 2 or not np.all(np.isfinite(arr)):
        return None
    if np.any(arr <= 0):
        return None
    return float(np.log(arr[0]) - np.log(arr[-1]))


# ----------------------------------------------------------------- 北向资金流
def northbound_flow(net_inflows):
    """北向净流入标准化：末期净流入相对历史的 z-score。

    net_inflows 为按时间升序的北向净流入序列。返回
        z = (last − mean) / std
    使"近期净流入高于历史均值"→ 正分（看多）。空/None/单点/零方差(std=0)→ None。
    regime_breaks 注记见 NORTHBOUND_REGIME_BREAKS（2024-08 口径变更，跨期差分需谨慎）。
    方向 '+'。
    """
    if net_inflows is None:
        return None
    arr = np.asarray(net_inflows, dtype=float)
    if arr.size < 2 or not np.all(np.isfinite(arr)):
        return None
    std = float(arr.std(ddof=0))
    if std < 1e-12:
        return None
    return float((arr[-1] - arr.mean()) / std)


# ----------------------------------------------------------------- 质押风险闸
def pledge_risk_gate(pledge_ratio):
    """股权质押风险闸（risk_gate，只降权不产 alpha）。

    返回 {'score', 'direction':'risk_gate', 'flag'}：
      flag='high'   质押比 > 0.5（高危，见 spec §5.6）
      flag='normal' 否则
    score 为非正降权强度（−pledge_ratio）：质押越高，降权越多，永不产正 alpha。
    pledge_ratio=None → 返回 unknown 闸（不编造，保守标 unknown）。
    """
    if pledge_ratio is None:
        return {"score": 0.0, "direction": "risk_gate", "flag": "unknown"}
    r = float(pledge_ratio)
    flag = "high" if r > 0.5 else "normal"
    return {"score": -r, "direction": "risk_gate", "flag": flag}


# ----------------------------------------------------------------- 限售解禁闸
def restricted_release_gate(days_to_release, release_ratio, near_days=30, ratio_thresh=0.05):
    """限售解禁风险闸（risk_gate，只降权）。

    临近大额解禁（days_to_release ≤ near_days 且 release_ratio ≥ ratio_thresh）→ flag='high'。
    返回 {'score', 'direction':'risk_gate', 'flag'}；score 非正（临近大额→更负的降权）。
    任一输入 None → unknown 闸（不编造）。spec §5.6：解禁只作可投性/降权约束，非 alpha。
    """
    if days_to_release is None or release_ratio is None:
        return {"score": 0.0, "direction": "risk_gate", "flag": "unknown"}
    d = float(days_to_release)
    ratio = float(release_ratio)
    high = (d <= near_days) and (ratio >= ratio_thresh)
    flag = "high" if high else "normal"
    # 降权强度：仅当临近大额时按比例降权，否则不降权。
    score = -ratio if high else 0.0
    return {"score": score, "direction": "risk_gate", "flag": flag}


# ----------------------------------------------------------------- 冷启动守门
def with_pit_guard(values, history_depth_days, min_history=MIN_HISTORY):
    """冷启动守门：forward_pit_only 因子历史深度<min_history → 弃权(insufficient_history)。

    诚实约束：PIT 历史不足时返回弃权标记而非编造曲线（spec §0/§14.2 PIT 成熟度门）。
    """
    if history_depth_days < min_history:
        return {"abstain": True, "abstain_reason": "insufficient_history",
                "history_depth_days": history_depth_days, "values": None}
    return {"abstain": False, "abstain_reason": None,
            "history_depth_days": history_depth_days,
            "values": None if values is None else list(values)}


# 方向汇总（随因子值穿全链路的诚实标签；risk_gate 只降权）。
FACTOR_DIRECTIONS = {
    "pead_sue": "+",
    "eps_revision": "+",
    "chip_factor": "+",
    "northbound_flow": "+",
    "pledge_risk_gate": "risk_gate",
    "restricted_release_gate": "risk_gate",
}
