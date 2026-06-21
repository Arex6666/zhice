"""L6 因子家族闸门（纯函数）：对一族因子 IC 的 BH-FDR + Harvey 联合判定。

输入为 L2 factor_eval 报告列表（含 ic_block_boot_p / ic_t_hac / significant）。
弃权(None)的因子直接判"样本不足"；其余按 BH 校正后的 p 与 Harvey t≥3 联合给 passed/verdict。
"""
import multi_test


def family_gate(reports, alpha=0.05):
    pvals = [r.get("ic_block_boot_p") for r in reports]
    valid_idx = [i for i, p in enumerate(pvals) if p is not None]
    adj = {}
    if valid_idx:
        adj_list = multi_test.bh([pvals[i] for i in valid_idx])
        adj = {i: adj_list[k] for k, i in enumerate(valid_idx)}
    out = []
    for i, r in enumerate(reports):
        p = pvals[i]
        if p is None or r.get("significant") is None:
            out.append({**r, "bh_adj_p": None, "bh_passed": False,
                        "harvey_passed": False, "passed": False, "family_verdict": "样本不足"})
            continue
        bh_passed = adj.get(i, 1.0) < alpha
        harvey = multi_test.harvey_passed(r.get("ic_t_hac", 0.0))
        passed = bool(bh_passed and r.get("significant"))
        verdict = "有效稳定" if (passed and harvey) else ("衰减中" if passed else "失效")
        out.append({**r, "bh_adj_p": round(adj.get(i, 1.0), 4), "bh_passed": bh_passed,
                    "harvey_passed": harvey, "passed": passed, "family_verdict": verdict})
    return out
