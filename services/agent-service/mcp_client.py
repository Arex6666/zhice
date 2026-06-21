"""异步 MCP 客户端：通过 SSE 连接 mcp-tool-service，列出并调用工具。

这是智能体作为 MCP Host 的核心：它用官方 mcp SDK 的 ClientSession 与远端 MCP
服务器握手 (initialize)、发现工具 (list_tools)、调用工具 (call_tool)。
"""
import os
from contextlib import asynccontextmanager

from mcp import ClientSession
from mcp.client.sse import sse_client

MCP_SSE_URL = os.getenv("MCP_SSE_URL", "http://mcp-tool-service:8002/sse")


@asynccontextmanager
async def open_session():
    async with sse_client(url=MCP_SSE_URL) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


async def list_tools_openai(session):
    """把 MCP 工具列表转换为 OpenAI function-calling 的 tools schema。"""
    resp = await session.list_tools()
    out = []
    for t in resp.tools:
        out.append(
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description or "",
                    "parameters": t.inputSchema or {"type": "object", "properties": {}},
                },
            }
        )
    return out


async def realtime_tools_openai(session):
    """委员会自主工具调用只暴露 **realtime** 工具（§3.4：offline 重计算工具不进 SSE 热路径）。"""
    import agentic
    return [t for t in await list_tools_openai(session)
            if not agentic.is_offline_tool(t["function"]["name"])]


async def call_tool(session, name, arguments):
    """调用一个 MCP 工具，把返回内容拼成纯文本（供回填给 LLM）。

    若 MCP 返回 isError（工具内部抛出异常），以 [工具调用失败] 前缀标注，
    让上层智能体能区分成功与失败，而不是把错误当正文。
    """
    res = await session.call_tool(name, arguments or {})
    text = "\n".join(getattr(c, "text", str(c)) for c in res.content)
    if getattr(res, "isError", False):
        return f"[工具调用失败] {text}"
    return text


async def call_tool_data(session, name, arguments):
    """调用 MCP 工具并返回结构化数据（dict/list），失败时返回 {'error':...}。

    优先用 structuredContent（FastMCP 对返回值的结构化封装，dict 会包成 {'result':...}）。
    """
    import json

    res = await session.call_tool(name, arguments or {})
    if getattr(res, "isError", False):
        return {"error": "\n".join(getattr(c, "text", "") for c in res.content)}
    sc = getattr(res, "structuredContent", None)
    if isinstance(sc, dict) and "result" in sc:
        return sc["result"]
    if isinstance(sc, dict) and sc:
        return sc
    # 逐个解析 content 文本块（list 返回值会被拆成多个 TextContent 块）
    blocks = [getattr(c, "text", "") for c in res.content if getattr(c, "text", "")]
    parsed = []
    for b in blocks:
        try:
            parsed.append(json.loads(b))
        except Exception:
            parsed.append(b)
    if len(parsed) == 1:
        v = parsed[0]
        return v.get("result", v) if isinstance(v, dict) else v
    return parsed
