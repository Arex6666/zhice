"""自审计汇总（纯函数）：把 storage 的 review_stats 输出转成自评摘要。"""
import calibration


def summarize(stats):
    reviewed = stats.get("reviewed", 0)
    hit = stats.get("hit_rate")
    awc = stats.get("avg_confidence_when_wrong")
    overconf = bool(reviewed and hit is not None and hit < 0.5 and awc is not None and awc > 0.65)
    cal = calibration.assess(stats.get("confidence_points") or [])
    if not reviewed:
        note = "暂无已复盘的研判（尚未到期或未产生）。"
    elif overconf:
        note = (f"已复盘 {reviewed} 条，命中率 {hit:.0%}，但判错时平均置信度高达 {awc:.0%}"
                "——存在过度自信，建议下调置信度或加强证据治理。")
    else:
        note = (f"已复盘 {reviewed} 条，命中率 {hit:.0%}。"
                + ("置信度与表现基本匹配。" if hit is not None else ""))
    if cal and cal["verdict"] != "校准良好":
        note += f" 校准评估：{cal['verdict']}(Brier={cal['brier']}, ECE={cal['ece']})。"
    return {"reviewed": reviewed, "hit_rate": hit, "by_member": stats.get("by_member", {}),
            "chairman_overconfident": overconf, "calibration": cal, "note": note}
