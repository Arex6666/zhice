#!/usr/bin/env python3
"""端到端冒烟测试：对运行中的 zhiyue 技术栈做集成验证。

分两部分：
  A. 不依赖 LLM 的核心链路（gateway 健康检查 + 经 MCP 调用爬虫/存储/检索）。
  B. 若设置了可用的 LLM_API_KEY，则额外验证经 gateway 的完整智能体对话。

用法：先 `docker compose up -d`，再 `python scripts/smoke_test.py`。
依赖：pip install mcp httpx
"""
import asyncio
import os
import sys

import httpx
from mcp import ClientSession
from mcp.client.sse import sse_client

GATEWAY = os.getenv("GATEWAY_URL", "http://localhost:8080")
MCP_SSE = os.getenv("MCP_SSE_URL", "http://localhost:8002/sse")
TEST_URL = os.getenv("TEST_URL", "https://example.com")

ok = []
fail = []


def check(name, cond, detail=""):
    (ok if cond else fail).append(name)
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f"  -> {detail}" if detail else ""))


async def part_a():
    print("== A. 核心链路（无需 LLM）==")
    # 1. gateway 健康
    r = httpx.get(f"{GATEWAY}/health", timeout=10)
    check("gateway /health == ok", r.json().get("status") == "ok")

    # 2. 经 MCP 列举工具并调用爬虫 + 存储 + 检索
    async with sse_client(url=MCP_SSE) as (read, write):
        async with ClientSession(read, write) as s:
            await s.initialize()
            tools = (await s.list_tools()).tools
            names = {t.name for t in tools}
            check("MCP 暴露 5 个工具", len(tools) == 5, ",".join(sorted(names)))

            res = await s.call_tool("get_web_content", {"url": TEST_URL})
            text = "\n".join(getattr(c, "text", "") for c in res.content)
            check("get_web_content 抓取成功", "Example Domain" in text or len(text) > 50,
                  text[:60].replace("\n", " "))

            res = await s.call_tool("save_document",
                                    {"url": TEST_URL, "title": "Example", "content": text[:500]})
            saved = "\n".join(getattr(c, "text", "") for c in res.content)
            check("save_document 写入记忆库", '"id"' in saved, saved[:60])

            res = await s.call_tool("search_documents", {"query": "Example", "limit": 5})
            found = "\n".join(getattr(c, "text", "") for c in res.content)
            check("search_documents 检索命中", "Example" in found)

    # 3. 经 gateway 读取历史（验证 gateway -> storage）
    r = httpx.get(f"{GATEWAY}/api/documents", params={"q": "Example"}, timeout=15)
    check("gateway /api/documents 命中已存文档", any("Example" in str(d) for d in r.json()))


async def part_b():
    key = os.getenv("LLM_API_KEY", "")
    if not key or "REPLACE" in key:
        print("== B. 智能体对话（跳过：未配置 LLM_API_KEY）==")
        return
    print("== B. 智能体完整对话（经 gateway 调用 DeepSeek）==")
    payload = {"message": f"帮我抓取 {TEST_URL} 的内容并用一句话总结"}
    r = httpx.post(f"{GATEWAY}/api/chat", json=payload, timeout=120)
    data = r.json()
    check("/api/chat 返回非空回答", bool(data.get("answer")), (data.get("answer") or "")[:60])
    check("智能体至少调用了一个 MCP 工具", len(data.get("tool_calls", [])) >= 1,
          ",".join(t["name"] for t in data.get("tool_calls", [])))


async def main():
    try:
        await part_a()
        await part_b()
    except Exception as e:
        print(f"\n!! 冒烟测试异常: {type(e).__name__}: {e}")
        fail.append(f"exception:{e}")
    print(f"\n结果：{len(ok)} 通过, {len(fail)} 失败")
    sys.exit(1 if fail else 0)


if __name__ == "__main__":
    asyncio.run(main())
