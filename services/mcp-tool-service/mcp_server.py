"""mcp-tool-service: 暴露爬虫 + 数据工具的 FastMCP 服务器。

双传输 (dual transport):
  MCP_TRANSPORT=stdio  -> 供 `mcp dev` / MCP Inspector / Cline 使用（指导书第三~五步）
  MCP_TRANSPORT=sse    -> 在 :8002 暴露 HTTP/SSE，供 agent-service 跨容器调用（微服务模式）

设计：所有工具均为 async，网络 I/O 用 httpx.AsyncClient，避免阻塞 FastMCP 的事件循环；
HTML 解析复用 tools.py 中的纯函数（可脱网单元测试）。工具内部不吞异常——出错时抛出，
由 FastMCP 自动置 isError=True，使客户端/智能体能感知失败。
"""
import os

import httpx
from mcp.server.fastmcp import FastMCP

import tools

STORAGE_URL = os.getenv("STORAGE_URL", "http://storage-service:8003")
HOST = os.getenv("MCP_HOST", "0.0.0.0")
PORT = int(os.getenv("MCP_PORT", "8002"))

mcp = FastMCP("ZhiYue Web Tools", host=HOST, port=PORT)


async def _fetch_html(url: str) -> str:
    """异步抓取网页 HTML（带浏览器 UA、跟随跳转、合理超时）。"""
    async with httpx.AsyncClient(headers=tools.HEADERS, timeout=15,
                                 follow_redirects=True) as c:
        r = await c.get(url)
        r.raise_for_status()
        return r.text


@mcp.tool()
async def get_web_content(url: str) -> str:
    """获取网页内容：抓取给定 URL 的网页，去除脚本/样式后返回纯文本（最多 4000 字）。
    用于：用户想阅读、总结或分析某个网页时。"""
    return tools.html_to_text(await _fetch_html(url))[:4000]


@mcp.tool()
async def extract_links(url: str) -> list:
    """提取网页中的所有超链接，返回 [{text, href}]，相对链接会被转为绝对链接。
    用于：用户想知道某页面上有哪些链接/导航时。"""
    return tools.extract_links_from_html(await _fetch_html(url), base_url=url)


@mcp.tool()
async def crawl_structured(url: str, selector: str) -> list:
    """按 CSS 选择器抽取结构化条目，返回 [{text, href}]（href 已转为绝对链接）。
    例：selector='.item' 抽取列表项。用于：结构化爬取（如榜单、商品列表）。"""
    return tools.crawl_structured_from_html(await _fetch_html(url), selector, base_url=url)


@mcp.tool()
async def save_document(url: str, title: str, content: str) -> dict:
    """把一篇网页内容保存到智能体的记忆库（storage-service），返回文档 id。
    用于：抓取到有价值的内容后做持久化，以便后续检索。"""
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(f"{STORAGE_URL}/documents",
                         json={"url": url, "title": title, "content": content})
        r.raise_for_status()
        return r.json()


@mcp.tool()
async def search_documents(query: str, limit: int = 5) -> list:
    """在记忆库中检索此前抓取过的网页（按关键词模糊匹配标题/正文/URL）。
    用于：用户问"我之前抓过哪些关于X的页面"。"""
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(f"{STORAGE_URL}/documents", params={"q": query, "limit": limit})
        r.raise_for_status()
        return r.json()


if __name__ == "__main__":
    transport = os.getenv("MCP_TRANSPORT", "stdio")
    if transport == "sse":
        print(f"启动 MCP 服务器 (SSE) on {HOST}:{PORT} ...")
        mcp.run(transport="sse")
    else:
        print("启动 MCP 服务器 (stdio) ...")
        mcp.run(transport="stdio")
