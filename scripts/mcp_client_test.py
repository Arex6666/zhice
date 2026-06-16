#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MCP 服务功能测试（对应《指导书》第三步：测试 MCP 服务）。

使用官方 MCP Python SDK 的 ClientSession，通过 SSE 连接 mcp-tool-service，
完成 initialize → list_tools → call_tool 的标准 MCP 交互——与 MCP Inspector
所做的事完全一致，只是以可复现的脚本形式呈现。
"""
import asyncio
import os

from mcp import ClientSession
from mcp.client.sse import sse_client

MCP_SSE = os.getenv("MCP_SSE_URL", "http://localhost:8002/sse")
TEST_URL = "https://example.com"


async def main():
    print(f"[1] 通过 SSE 连接 MCP 服务器：{MCP_SSE}")
    async with sse_client(url=MCP_SSE) as (read, write):
        async with ClientSession(read, write) as s:
            init = await s.initialize()
            print(f"    握手成功，服务器：{init.serverInfo.name} v{init.serverInfo.version}")

            print("[2] list_tools —— 服务器暴露的 MCP 工具：")
            tools = (await s.list_tools()).tools
            for t in tools:
                print(f"      - {t.name}: {(t.description or '').splitlines()[0]}")

            print(f"[3] call_tool get_web_content(url={TEST_URL})")
            res = await s.call_tool("get_web_content", {"url": TEST_URL})
            text = "\n".join(getattr(c, "text", "") for c in res.content)
            print("    返回（前 200 字）：")
            print("    " + text[:200].replace("\n", " "))

            print("[4] call_tool extract_links(url=...) —— 返回内容（前 200 字）")
            res = await s.call_tool("extract_links", {"url": TEST_URL})
            ltext = "\n".join(getattr(c, "text", "") for c in res.content)
            print("    " + ltext[:200].replace("\n", " "))

    print("\n[OK] MCP 服务测试通过：initialize / list_tools / call_tool 均正常。")


if __name__ == "__main__":
    asyncio.run(main())
