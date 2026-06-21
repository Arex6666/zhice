"""证据治理引擎（确定性规则层，非 LLM）。

在委员发言之后、主席汇总之前运行，对每条研判强制施加治理规则 R1–R6，
产出 governance_report（哪些规则触发、为何降级）供审计，并给出：
  - ceiling：置信度天花板（数据质量 × 一致度 × 证据强度）。
  - allowed_verdicts：主席最终"方向"的允许集合（治理对方向、而非仅对置信度生效）。

规则执行顺序很关键：先跑降级类规则(R1 无证据 / R6 仅情绪) 把不达标的强结论降为中性，
再在**降级后的** verdict 上计算 R3 冲突与 ceiling，避免自相矛盾的治理态。
"""
STRONG = ("偏多", "偏空")
VALID_TYPES = ("indicator", "news_fact", "news_sentiment", "news_inference", "backtest",
               "market", "model", "stat")
SENTIMENT = ("news_sentiment", "news_inference")


def _conf(m):
    """委员置信度的容错读取（缺失/非数值 → 0.5）。"""
    try:
        return float(m.get("confidence"))
    except (TypeError, ValueError):
        return 0.5


def _valid_evidence(evidence):
    """仅保留实质性证据：type 合法、source 与 value 非空。"""
    out = []
    for e in (evidence or []):
        if not isinstance(e, dict):
            continue
        if e.get("type") in VALID_TYPES and str(e.get("source", "")).strip() \
                and str(e.get("value", "")).strip():
            out.append(e)
    return out


def govern(members, data_status, ml, backtest_stable, vol_regime=None,
           factor_flags=None, regime_scale=None, portfolio_flags=None):
    """members: list[委员 dict]；data_status；ml: XGBoost 票或 None；backtest_stable: bool；
    vol_regime: 已实现波动区间(或 None)。
    factor_flags: list[因子证据旗标 dict]（pit_status/history_depth/risk_gate/ic_verdict/bh_passed/
      stale/incremental_ic/missing_metadata）→ R10–R12；regime_scale: 仓位乘子(仅记录, 不压 ceiling)；
    portfolio_flags: {beats_1overN, capacity_flag} → R13。新参数默认 None 向后兼容。
    返回 {members_adjusted, ceiling, conflict, disagreement, report, allowed_verdicts}。
    """
    report = []
    adj = []

    # —— 先跑降级类规则 R1 / R6（对每位委员） ——
    for m in members:
        m = dict(m)
        if not m.get("abstain") and m.get("verdict") in STRONG:
            ev = _valid_evidence(m.get("evidence"))
            substantive = [e for e in ev if e["type"] not in SENTIMENT]
            if not ev:
                m["verdict"] = "中性"
                report.append("R1: 委员无有效证据→降为中性")
            elif not substantive:
                m["verdict"] = "中性"
                report.append("R6: 仅情绪/推断证据→降为中性")
        adj.append(m)

    # —— 在降级后的 verdict 上计算冲突与方向 ——
    actives = [m for m in adj if not m.get("abstain") and m.get("verdict") in STRONG]
    verdicts = {m["verdict"] for m in actives}
    conflict = ("偏多" in verdicts) and ("偏空" in verdicts)

    # —— 连续分歧指数 ∈[0,1]：置信度加权方向散度（0=方向一致，1=势均力敌对立） ——
    # 置信度下限钳制 0.1：避免 0 置信度异议委员把分歧指数吞为 0、真实多空冲突仍携满额天花板
    scores = [(1 if m["verdict"] == "偏多" else -1) * max(_conf(m), 0.1) for m in actives]
    gross = sum(abs(s) for s in scores)
    disagreement = round(1 - abs(sum(scores)) / gross, 3) if gross else 0.0

    # —— 置信度天花板 ——
    ceiling = 0.85
    if data_status in ("stale", "error"):
        ceiling = min(ceiling, 0.4)
        report.append(f"R2: 数据{data_status}→置信度≤0.4")
    elif data_status in ("delayed", "fallback"):
        # 延迟/备份源数据：未完全失效，但不应携带满额置信度（中间档）
        ceiling = min(ceiling, 0.65)
        report.append(f"R2: 数据{data_status}→置信度≤0.65")
    if conflict:
        # 梯度天花板随分歧平滑下降：势均力敌对立(index=1)→0.55，轻微异议→更接近 0.85
        r3 = round(0.85 - 0.30 * disagreement, 3)
        ceiling = min(ceiling, r3)
        report.append(f"R3: 委员意见冲突(分歧指数={disagreement})→暴露分歧、置信度≤{r3}")
    if ml is not None and ml.get("abstain"):
        report.append("R4: XGBoost 弃权（AUC≈0.5/样本不足）→该票剔除，不参与投票")
    if not backtest_stable:
        ceiling = min(ceiling, 0.6)
        report.append("R5: 回测不稳健或边际不显著(自助检验)→置信度≤0.6")
    # R7：模型预警高波动 → 不确定性高 → 封顶置信度（波动信号是可学习、有效的）。
    # 阈值优先用模型自身的极端分位 q_extreme（数据驱动；弱模型校准概率被压缩，绝对阈值不可达），
    # 旧模型无分位时回退绝对 0.6，保证向后兼容。
    if ml is not None and not ml.get("abstain"):
        pbm = ml.get("prob_big_move")
        q_ext = ml.get("q_extreme")
        thr = q_ext if isinstance(q_ext, (int, float)) else 0.6
        if isinstance(pbm, (int, float)) and pbm >= thr:
            ceiling = min(ceiling, 0.6)
            report.append(f"R7: 模型预警次日高波动(p={pbm:.2f}≥阈值{thr:.2f})→不确定性升高、置信度≤0.6")
    # R8：已实现波动处于高分位区间（市场实际波动放大）→ 方向更难判定 → 封顶置信度
    if vol_regime in ("elevated", "extreme"):
        cap = 0.6 if vol_regime == "extreme" else 0.7
        ceiling = min(ceiling, cap)
        report.append(f"R8: 已实现波动处于{vol_regime}区间→不确定性升高、置信度≤{cap}")

    # —— R10–R12：因子证据治理（DAG：R12 剔无效 → R11 封顶不可靠 → R10 因子降权） ——
    for ff in (factor_flags or []):
        name = ff.get("factor", "?")
        # R12：未过 BH / 已陈旧 / 无增量 IC / 缺元数据 → 排除该证据（不再参与后续）
        if (ff.get("bh_passed") is False or ff.get("stale")
                or (ff.get("incremental_ic") is not None and ff["incremental_ic"] <= 0)
                or ff.get("missing_metadata")):
            report.append(f"R12: 因子「{name}」未过BH/已陈旧/无增量IC/缺元数据→排除该证据")
            continue
        # R11：IC 衰减/失效 → 封顶
        if ff.get("ic_verdict") in ("衰减中", "失效"):
            ceiling = min(ceiling, 0.6)
            report.append(f"R11: 因子「{name}」IC{ff['ic_verdict']}→估计不可靠、置信度≤0.6")
        # R10：非 PIT / 历史不足 / 风险闸 → 封顶因子证据贡献
        hd = ff.get("history_depth")   # 显式 None/缺失=未知深度→保守按历史不足封顶(勿用 or 1e9, 会放行 0)
        if (ff.get("pit_status") in ("forward_pit_only", "lagged_fixed", "lagged_legal_deadline")
                or hd is None or hd < 252 or ff.get("risk_gate")):
            ceiling = min(ceiling, 0.65)
            report.append(f"R10: 因子「{name}」非PIT/历史不足/风险闸→置信度≤0.65")
    if regime_scale is not None and regime_scale < 1.0:
        report.append(f"治理: 仓位乘子 regime_scale={regime_scale}（仅缩 net-exposure，不压方向天花板）")
    # R13：组合级独立审计（未跑赢 1/N 或容量不可投 → 仅展示风险均衡、不主张 alpha）
    if portfolio_flags is not None:
        beats = portfolio_flags.get("beats_1overN")
        cap = portfolio_flags.get("capacity_flag")
        if beats is None or beats is False or cap == "infeasible":
            report.append("R13: 组合样本外未跑赢1/N或容量受限→仅展示风险均衡(ERC)、不主张alpha、研究型不可实盘")

    # —— 主席方向的允许集合：治理对"方向"生效，杜绝无据强结论 ——
    if not actives:
        allowed = {"中性"}  # 无存活强结论委员 → 强制中性
        report.append("治理: 无存活强结论委员→最终方向限定为中性")
    elif conflict:
        allowed = {"偏多", "偏空", "中性"}  # 允许主席裁决，但置信度已被 R3 封顶
    else:
        allowed = {next(iter(verdicts)), "中性"}  # 一致方向 D → 仅允许 D 或中性

    return {"members_adjusted": adj, "ceiling": ceiling, "conflict": conflict,
            "disagreement": disagreement, "report": report, "allowed_verdicts": allowed}
