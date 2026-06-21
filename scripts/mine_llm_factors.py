#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""L7 LLM 因子挖掘（离线 propose-then-prove 证伪机；LLM 永不持最终决策权）。

LLM 只在受限 DSL 内**提议**公式型候选因子，系统逐关**证伪**：
  DSL 安全解析 → AlphaEval 五维 → 原创性(与库 |corr|) → (下一关: panel_cv/factor_gate)。
任一关失败即弃权并记原因。`mine_one` 为依赖注入的纯编排(脱 LLM 可测)；`main` 接真实 DeepSeek。
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_PROMPT = (
    "你是量化因子研究员。只用如下受限算子提出**一个** A股日频价量因子公式(只输出公式字符串, 不要解释)：\n"
    "变量: C(收盘) O(开) H(高) L(低) V(量)\n"
    "算子: ts_mean/ts_std/ts_max/ts_min/delay(或Ref)/delta/ema/corr/slope/scale/Abs/Log/Sign/If, 及 + - * /\n"
    "禁止: 任何上述以外的函数、属性访问、横截面排名(交由系统逐截面处理)。\n"
    "示例: Ref(C,21)/Ref(C,252)-1\n"
)


def _extract_formula(text):
    """从 LLM 回复里抽公式：剥 ``` 代码块/反引号/前缀说明，取最后一段非空。"""
    t = str(text or "").strip()
    if "```" in t:
        parts = [p for p in t.split("```") if p.strip()]
        t = parts[-1] if parts else t
        t = re.sub(r"^\s*\w+\s*\n", "", t)            # 去 ```python 之类语言标签
    m = re.findall(r"`([^`]+)`", t)
    if m:
        t = m[-1]
    if "：" in t or ":" in t:                          # 去"公式: xxx"前缀
        t = re.split(r"[:：]", t)[-1]
    return t.strip().splitlines()[-1].strip() if t.strip() else ""


def mine_one(llm_propose, compute_factor, alpha_evaluate, originality_check, library):
    """单轮闯关(依赖注入)。返回 {accepted, stage, formula, ...}；任一关失败即弃权。"""
    formula = llm_propose()
    try:
        vals = compute_factor(formula)                # 闸门0: DSL 安全解析+求值
    except Exception as e:  # noqa: BLE001
        return {"accepted": False, "stage": "dsl_parse", "formula": formula, "reason": str(e)[:100]}
    ae = alpha_evaluate(vals)                          # 闸门1: AlphaEval 五维
    if not ae.get("passes"):
        return {"accepted": False, "stage": "alpha_eval", "formula": formula, "evals": ae}
    orig = originality_check(vals, library)            # 闸门2: 原创性
    if not orig.get("original"):
        return {"accepted": False, "stage": "originality", "formula": formula,
                "max_corr": orig.get("max_corr")}
    return {"accepted": True, "formula": formula, "evals": ae, "originality": orig,
            "note": "通过 DSL+AlphaEval+原创性; 仍需 panel_cv/factor_gate 严格证伪后方可落库"}


# ---------------------------------------------------------------- 真实 DeepSeek 运行入口
def _load_env():
    envp = os.path.join(ROOT, "deploy", ".env")
    if os.path.exists(envp):
        for line in open(envp, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"\''))


def _deepseek_propose():
    from openai import OpenAI
    c = OpenAI(base_url=os.getenv("LLM_BASE_URL", "https://api.deepseek.com"),
               api_key=os.getenv("LLM_API_KEY", ""))
    r = c.chat.completions.create(model=os.getenv("LLM_MODEL", "deepseek-chat"), temperature=0.7,
                                  messages=[{"role": "user", "content": _PROMPT}])
    return _extract_formula(r.choices[0].message.content)


def main(symbol="600519", rounds=3):
    """真实挖掘 PoC：DeepSeek 提公式 → DSL 求值 → AlphaEval/原创性 闯关。"""
    import asyncio

    import numpy as np
    _load_env()
    sys.path.insert(0, os.path.join(ROOT, "services", "mcp-tool-service"))
    import factor_dsl
    import alpha_eval
    import finance

    kline = asyncio.run(finance.get_adapter("ASHARE").get_kline(symbol, "daily", 300))
    data = {"C": np.array([r["close"] for r in kline], dtype=float),
            "O": np.array([r["open"] for r in kline], dtype=float),
            "H": np.array([r["high"] for r in kline], dtype=float),
            "L": np.array([r["low"] for r in kline], dtype=float),
            "V": np.array([r["volume"] for r in kline], dtype=float)}
    closes = data["C"]
    fwd = np.append(np.diff(closes) / closes[:-1], np.nan)        # 次日收益(末位 NaN)
    library = []
    for i in range(rounds):
        out = mine_one(
            llm_propose=_deepseek_propose,
            compute_factor=lambda f: factor_dsl.evaluate(f, data),
            alpha_evaluate=lambda v: alpha_eval.evaluate(v[:-1], fwd[:-1]),
            originality_check=lambda v, lib: alpha_eval.originality(v[:-1], lib),
            library=library)
        print(f"[{i+1}] {out.get('stage', 'ACCEPTED')}: {out['formula']!r} "
              f"accepted={out['accepted']} evals={out.get('evals')}")
        if out["accepted"]:
            library.append(factor_dsl.evaluate(out["formula"], data)[:-1])


if __name__ == "__main__":
    main()
