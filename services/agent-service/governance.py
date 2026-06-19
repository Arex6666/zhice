"""证据治理引擎（确定性规则层，非 LLM）。

在委员发言之后、主席汇总之前运行：对每条研判强制施加治理规则 R1–R6，
并产出 governance_report（哪些规则触发、为何降级）供审计。
置信度天花板 ceiling 由"数据质量 × 委员一致度 × 证据强度"推导，
使"高置信"必须有据。
"""

STRONG = ("偏多", "偏空")


def govern(members, data_status, ml, backtest_stable):
    """members: list[委员 dict]; data_status: 输入数据状态; ml: XGBoost 票或 None; backtest_stable: bool。
    返回 {members_adjusted, ceiling, conflict, report}。
    """
    report = []
    ceiling = 0.85
    adj = []

    # R1：无证据不出强结论
    for m in members:
        m = dict(m)
        if not m.get("abstain") and m.get("verdict") in STRONG and not m.get("evidence"):
            m["verdict"] = "中性"
            report.append("R1: 委员无证据→降为中性")
        adj.append(m)

    # R2：数据过期/错误必降置信
    if data_status in ("stale", "error"):
        ceiling = min(ceiling, 0.4)
        report.append(f"R2: 数据{data_status}→置信度≤0.4")

    # R3：证据冲突必暴露分歧
    actives = [m for m in adj if not m.get("abstain") and m.get("verdict") in STRONG]
    verdicts = {m["verdict"] for m in actives}
    conflict = ("偏多" in verdicts) and ("偏空" in verdicts)
    if conflict:
        ceiling = min(ceiling, 0.55)
        report.append("R3: 委员意见冲突→暴露分歧、置信度≤0.55")

    # R4：模型无效必弃权
    if ml is not None and ml.get("abstain"):
        report.append("R4: XGBoost 弃权（AUC≈0.5/样本不足）→该票剔除")

    # R5：回测不稳不支持高置信
    if not backtest_stable:
        ceiling = min(ceiling, 0.6)
        report.append("R5: 回测参数敏感性不稳→置信度≤0.6")

    # R6：仅情绪/推断证据→降级
    for m in adj:
        if not m.get("abstain") and m.get("verdict") in STRONG:
            ev = m.get("evidence", [])
            if ev and all(e.get("type") in ("news_sentiment", "news_inference") for e in ev):
                m["verdict"] = "中性"
                report.append("R6: 仅情绪/推断证据→降为中性")

    return {"members_adjusted": adj, "ceiling": ceiling, "conflict": conflict, "report": report}
