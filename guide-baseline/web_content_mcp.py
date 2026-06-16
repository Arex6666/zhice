#!/usr/bin/env python3
"""测试 MCP 服务器（《MCP实验指导书》第二步原样实现）。

将 requests + BeautifulSoup 的网页爬取代码，通过 fastmcp 封装为标准 MCP 服务，
可被 `mcp dev` / MCP Inspector / Cline 直接调用。
"""
import requests
from bs4 import BeautifulSoup as bs
from mcp.server.fastmcp import FastMCP

# 创建 MCP 服务器实例
mcp = FastMCP("Web Scraper")


@mcp.tool()
def get_web_content(url: str) -> str:
    """获取网页内容"""
    header = {
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36"
    }
    try:
        r = requests.get(url, headers=header, timeout=10)
        r.raise_for_status()
        r.encoding = r.apparent_encoding
        soup = bs(r.text, "html.parser")
        text_content = soup.get_text(separator='\n', strip=True)
        return text_content[:1000]  # 限制返回长度
    except Exception as e:
        return f"Error: {e}"


if __name__ == "__main__":
    print("启动 MCP 服务器...")
    mcp.run(transport='stdio')
