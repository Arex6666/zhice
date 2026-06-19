"""证据治理引擎（确定性规则层，非 LLM）。

在委员发言之后、主席汇总之前运行，对每条研判强制施加治理规则 R1–R6，
产出 governance_report（哪些规则触发、为何降级）供审计，并给出：
  - ceiling：置信度天花板（数据质量 × 一致度 × 证据强度）。
  - allowed_verdicts：主席最终"方向"的允许集合（治理对方向、而非仅对置信度生效）。

规则执行顺序很关键：先跑降级类规则(R1 无证据 / R6 仅情绪) 把不达标的强结论降为中性，
再在**降级后的** verdict 上计算 R3 冲突与 ceiling，避免自相矛盾的治理态。
"""
STRONG = ("偏多", "偏空")
VALID_TYPES = ("indicator", "news_fact", "news_sentiment", "news_inference", "backtest", "market")
SENTIMENT = ("news_sentiment", "news_inference")


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


def govern(members, data_status, ml, backtest_stable):
    """members: list[委员 dict]；data_status；ml: XGBoost 票或 None；backtest_stable: bool。
    返回 {members_adjusted, ceiling, conflict, report, allowed_verdicts}。
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

    # —— 置信度天花板 ——
    ceiling = 0.85
    if data_status in ("stale", "error"):
        ceiling = min(ceiling, 0.4)
        report.append(f"R2: 数据{data_status}→置信度≤0.4")
    if conflict:
        ceiling = min(ceiling, 0.55)
        report.append("R3: 委员意见冲突→暴露分歧、置信度≤0.55")
    if ml is not None and ml.get("abstain"):
        report.append("R4: XGBoost 弃权（AUC≈0.5/样本不足）→该票剔除，不参与投票")
    if not backtest_stable:
        ceiling = min(ceiling, 0.6)
        report.append("R5: 回测参数敏感性不稳→置信度≤0.6")

    # —— 主席方向的允许集合：治理对"方向"生效，杜绝无据强结论 ——
    if not actives:
        allowed = {"中性"}  # 无存活强结论委员 → 强制中性
        report.append("治理: 无存活强结论委员→最终方向限定为中性")
    elif conflict:
        allowed = {"偏多", "偏空", "中性"}  # 允许主席裁决，但置信度已被 R3 封顶
    else:
        allowed = {next(iter(verdicts)), "中性"}  # 一致方向 D → 仅允许 D 或中性

    return {"members_adjusted": adj, "ceiling": ceiling, "conflict": conflict,
            "report": report, "allowed_verdicts": allowed}
