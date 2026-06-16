"""mcp-tool-service: 暴露爬虫 + 数据工具的 FastMCP 服务器。

双传输 (dual transport):
  MCP_TRANSPORT=stdio  -> 供 `mcp dev` / MCP Inspector / Cline 使用（指导书第三~五步）
  MCP_TRANSPORT=sse    -> 在 :8002 暴露 HTTP/SSE，供 agent-service 跨容器调用（微服务模式）

数据类工具 (save_document / search_documents) 通过 HTTP 转调 storage-service，
使本服务成为"智能体能力的统一 MCP 入口"。
"""
import os

import httpx
from mcp.server.fastmcp import FastMCP

import tools

STORAGE_URL = os.getenv("STORAGE_URL", "http://storage-service:8003")
HOST = os.getenv("MCP_HOST", "0.0.0.0")
PORT = int(os.getenv("MCP_PORT", "8002"))

mcp = FastMCP("ZhiYue Web Tools", host=HOST, port=PORT)


@mcp.tool()
def get_web_content(url: str) -> str:
    """获取网页内容：抓取给定 URL 的网页，去除脚本/样式后返回纯文本（最多 4000 字）。
    用于：用户想阅读、总结或分析某个网页时。"""
    try:
        text = tools.html_to_text(tools.fetch_html(url))
        return text[:4000]
    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
def extract_links(url: str) -> list:
    """提取网页中的所有超链接，返回 [{text, href}]，相对链接会被转为绝对链接。
    用于：用户想知道某页面上有哪些链接/导航时。"""
    try:
        return tools.extract_links_from_html(tools.fetch_html(url), base_url=url)
    except Exception as e:
        return [{"error": str(e)}]


@mcp.tool()
def crawl_structured(url: str, selector: str) -> list:
    """按 CSS 选择器抽取结构化条目，返回 [{text, href}]。
    例：selector='.item' 抽取列表项。用于：结构化爬取（如榜单、商品列表）。"""
    try:
        return tools.crawl_structured_from_html(tools.fetch_html(url), selector)
    except Exception as e:
        return [{"error": str(e)}]


@mcp.tool()
def save_document(url: str, title: str, content: str) -> dict:
    """把一篇网页内容保存到智能体的记忆库（storage-service），返回文档 id。
    用于：抓取到有价值的内容后做持久化，以便后续检索。"""
    try:
        r = httpx.post(
            f"{STORAGE_URL}/documents",
            json={"url": url, "title": title, "content": content},
            timeout=15,
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def search_documents(query: str, limit: int = 5) -> list:
    """在记忆库中检索此前抓取过的网页（按关键词模糊匹配标题/正文/URL）。
    用于：用户问"我之前抓过哪些关于X的页面"。"""
    try:
        r = httpx.get(
            f"{STORAGE_URL}/documents",
            params={"q": query, "limit": limit},
            timeout=15,
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return [{"error": str(e)}]


if __name__ == "__main__":
    transport = os.getenv("MCP_TRANSPORT", "stdio")
    if transport == "sse":
        print(f"启动 MCP 服务器 (SSE) on {HOST}:{PORT} ...")
        mcp.run(transport="sse")
    else:
        print("启动 MCP 服务器 (stdio) ...")
        mcp.run(transport="stdio")
