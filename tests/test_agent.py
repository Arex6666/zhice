import asyncio
import importlib.util
import types


def _agent():
    spec = importlib.util.spec_from_file_location(
        "zagent", "services/agent-service/agent.py"
    )
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _msg(content=None, tool_calls=None):
    return types.SimpleNamespace(content=content, tool_calls=tool_calls)


def _resp(message):
    return types.SimpleNamespace(choices=[types.SimpleNamespace(message=message)])


def _toolcall(name, args, tid="c1"):
    return types.SimpleNamespace(
        id=tid, type="function",
        function=types.SimpleNamespace(name=name, arguments=args),
    )


class FakeLLM:
    """第一轮要求调用 get_web_content，第二轮返回最终答案。"""

    def __init__(self):
        self.n = 0
        self.chat = types.SimpleNamespace(
            completions=types.SimpleNamespace(create=self._create)
        )

    def _create(self, **kw):
        self.n += 1
        if self.n == 1:
            return _resp(_msg(None, [_toolcall("get_web_content", '{"url":"http://x"}')]))
        return _resp(_msg("最终答案：该页面讲微服务架构。来源：http://x", None))


def test_agent_loop_runs_offline():
    agent = _agent()
    tools_schema = [{
        "type": "function",
        "function": {
            "name": "get_web_content", "description": "d",
            "parameters": {"type": "object", "properties": {"url": {"type": "string"}}},
        },
    }]

    async def fake_list(session):
        return tools_schema

    async def fake_call(session, name, args):
        return "页面正文：微服务架构介绍"

    out = asyncio.run(
        agent.run_loop(
            message="抓取并总结 http://x",
            llm=FakeLLM(), model="m", session=object(),
            list_tools=fake_list, call_tool=fake_call, max_iters=5,
        )
    )
    assert "最终答案" in out["answer"]
    assert out["tool_calls"][0]["name"] == "get_web_content"
    assert out["sources"] == ["http://x"]


def test_agent_loop_no_tools_direct_answer():
    agent = _agent()

    class DirectLLM:
        def __init__(self):
            self.chat = types.SimpleNamespace(
                completions=types.SimpleNamespace(
                    create=lambda **kw: _resp(_msg("你好，我是智阅助手", None))
                )
            )

    async def fake_list(session):
        return []

    async def fake_call(session, name, args):
        raise AssertionError("should not be called")

    out = asyncio.run(
        agent.run_loop(
            message="你好", llm=DirectLLM(), model="m", session=object(),
            list_tools=fake_list, call_tool=fake_call, max_iters=5,
        )
    )
    assert out["answer"] == "你好，我是智阅助手"
    assert out["tool_calls"] == []
