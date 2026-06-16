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


async def call_tool(session, name, arguments):
    """调用一个 MCP 工具，把返回内容拼成纯文本（供回填给 LLM）。"""
    res = await session.call_tool(name, arguments or {})
    parts = []
    for c in res.content:
        parts.append(getattr(c, "text", str(c)))
    return "\n".join(parts)
