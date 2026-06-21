"""委员会自主工具调用循环 + §3.4 offline 硬拒（agent-service/agentic.py）。

DI 的 llm 与 tool-caller，使其完全脱网可测（不依赖 mcp SDK / openai 网络）。
"""
import asyncio
import importlib.util


def _ag():
    s = importlib.util.spec_from_file_location("ag", "services/agent-service/agentic.py")
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


# ---- 假 openai 响应对象 ----
class _Fn:
    def __init__(self, name, args): self.name, self.arguments = name, args


class _TC:
    def __init__(self, id, name, args): self.id, self.function = id, _Fn(name, args)


class _Msg:
    def __init__(self, content=None, tool_calls=None): self.content, self.tool_calls = content, tool_calls


class _Resp:
    def __init__(self, msg): self.choices = [type("C", (), {"message": msg})()]


class FakeLLM:
    """按预设脚本逐次返回响应（先要求调一个工具，再给最终结论）。"""
    def __init__(self, scripted): self._s = list(scripted); self.calls = 0

    class _Chat:
        def __init__(self, outer): self._o = outer

        class _Comp:
            def __init__(self, outer): self._o = outer

            async def create(self, **kw):
                o = self._o
                r = o._s[min(o.calls, len(o._s) - 1)]
                o.calls += 1
                return r
        @property
        def completions(self): return FakeLLM._Chat._Comp(self._o)

    @property
    def chat(self): return FakeLLM._Chat(self)


def test_offline_tool_is_rejected():
    ag = _ag()
    assert ag.is_offline_tool("efficient_frontier") is True
    assert ag.is_offline_tool("mine_llm_factors") is True
    assert ag.is_offline_tool("get_quote") is False
    assert ag.is_offline_tool("read_factor_eval") is False


def test_guarded_caller_blocks_offline():
    ag = _ag()
    seen = []

    async def raw(name, args):
        seen.append(name)
        return {"ok": True}

    call = ag.make_guarded_caller(raw)
    out_ok = asyncio.run(call("get_quote", {"symbol": "x"}))
    out_block = asyncio.run(call("build_portfolio", {}))
    assert out_ok == {"ok": True}
    assert out_block["error"] == "offline_tool_not_callable_in_committee"
    assert seen == ["get_quote"]          # offline 工具根本没到 raw 执行层


def test_run_agentic_calls_tool_then_finalizes():
    ag = _ag()
    scripted = [
        _Resp(_Msg(content=None, tool_calls=[_TC("c1", "get_quote", '{"symbol":"ASHARE:600519"}')])),
        _Resp(_Msg(content="结论：偏多，证据来自实时报价。", tool_calls=None)),
    ]
    llm = FakeLLM(scripted)
    executed = []

    async def call_fn(name, args):
        executed.append((name, args))
        return {"price": 1700, "change_pct": 1.2}

    out = asyncio.run(ag.run_agentic(llm, "deepseek-chat",
                                     [{"role": "user", "content": "研判该股"}],
                                     tools=[{"type": "function", "function": {"name": "get_quote"}}],
                                     call_fn=call_fn, max_rounds=3))
    assert out["final"].startswith("结论")
    assert ("get_quote", {"symbol": "ASHARE:600519"}) in executed
    assert len(out["trace"]) == 1 and out["trace"][0]["tool"] == "get_quote"


def test_run_agentic_caps_rounds():
    """LLM 一直要求调工具 → 命中 max_rounds 后强制收尾，不无限循环（成本护栏）。"""
    ag = _ag()
    loop_resp = _Resp(_Msg(content=None, tool_calls=[_TC("c", "get_quote", "{}")]))
    final_resp = _Resp(_Msg(content="被迫收尾", tool_calls=None))
    llm = FakeLLM([loop_resp, loop_resp, final_resp])

    async def call_fn(name, args):
        return {"x": 1}

    out = asyncio.run(ag.run_agentic(llm, "m", [{"role": "user", "content": "go"}],
                                     tools=[{"type": "function", "function": {"name": "get_quote"}}],
                                     call_fn=call_fn, max_rounds=2))
    assert out["hit_cap"] is True and out["rounds"] == 2
