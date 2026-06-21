"""委员会自主工具调用（agentic tool-use）+ §3.4 offline 硬隔离。

把 MCP 工具目录交给 LLM，让它在研判时**自主决定调哪个实时工具**取证（而非编排器预取喂数据）。
护栏：
1. **§3.4 物理隔离**：offline 重计算工具（CPCV/组合优化/因子全量重算/LLM 挖掘/训练）一律硬拒，
   返回 offline_tool_not_callable_in_committee —— 离线工具绝不进委员会 SSE 热路径。
2. **轮次上限**：max_rounds 命中即强制收尾，杜绝工具调用死循环（成本/延迟护栏）。
3. **单调用超时 + 失败隔离**：交由注入的 call_fn 负责（finance_agent 侧绑定带超时的 guarded 调用）。

本模块不 import mcp SDK / openai，纯编排（llm 与 call_fn 依赖注入）→ 脱网可单测。
"""
import json

# §10.2 标 offline 的重计算工具：绝不可在委员会会话中调用（§3.4）。
OFFLINE_TOOLS = {
    "panel_cv", "evaluate_factor_cv", "factor_report", "factor_family_gate",
    "build_factor_panel", "build_portfolio", "efficient_frontier", "shrink_cov_report",
    "deflated_sharpe", "mine_llm_factors", "train_xsec",
}


def is_offline_tool(name):
    return name in OFFLINE_TOOLS


def make_guarded_caller(raw_call):
    """包装真实工具执行器：offline 工具直接拒绝（不下达到执行层），其余透传。"""
    async def call(name, args):
        if is_offline_tool(name):
            return {"error": "offline_tool_not_callable_in_committee",
                    "execution_mode": "offline", "tool": name}
        return await raw_call(name, args)
    return call


def _serialize_tool_calls(tcs):
    return [{"id": tc.id, "type": "function",
             "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
            for tc in tcs]


async def run_agentic(llm, model, messages, tools, call_fn, max_rounds=3, result_cap=4000):
    """让 LLM 在 max_rounds 内自主调用工具取证，最后产出结论文本。

    返回 {final, trace:[{tool,args,...}], rounds, hit_cap}。call_fn 应为 guarded（已挡 offline）。
    """
    msgs = list(messages)
    trace = []
    for r in range(max_rounds):
        resp = await llm.chat.completions.create(
            model=model, messages=msgs, tools=tools, tool_choice="auto")
        msg = resp.choices[0].message
        tcs = getattr(msg, "tool_calls", None)
        if not tcs:
            return {"final": msg.content, "trace": trace, "rounds": r, "hit_cap": False}
        msgs.append({"role": "assistant", "content": msg.content or "",
                     "tool_calls": _serialize_tool_calls(tcs)})
        for tc in tcs:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments or "{}")
            except (ValueError, TypeError):
                args = {}
            data = await call_fn(name, args)
            blocked = isinstance(data, dict) and data.get("error") == "offline_tool_not_callable_in_committee"
            trace.append({"tool": name, "args": args, "blocked": blocked})
            msgs.append({"role": "tool", "tool_call_id": tc.id,
                         "content": json.dumps(data, ensure_ascii=False)[:result_cap]})
    # 命中轮次上限 → 去工具再要一次最终结论（成本护栏）
    resp = await llm.chat.completions.create(model=model, messages=msgs)
    return {"final": resp.choices[0].message.content, "trace": trace,
            "rounds": max_rounds, "hit_cap": True}
