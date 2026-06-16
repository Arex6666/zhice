#!/usr/bin/env python3
"""guide-baseline 的 stdio 演示变体：与 web_content_mcp.py 完全相同的爬虫逻辑，
唯一区别是把启动日志输出到 stderr（而非 stdout）。

原因：stdio 传输下 stdout 是 JSON-RPC 通道，向 stdout 打印普通文本会污染协议流、
导致 MCP Inspector 握手失败。本文件用于 `mcp dev` / MCP Inspector 的 stdio 演示。
（web_content_mcp.py 保持《指导书》原样，仅作教学基线对照。）
"""
import sys

import requests
from bs4 import BeautifulSoup as bs
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Web Scraper")


@mcp.tool()
def get_web_content(url: str) -> str:
    """获取网页内容"""
    header = {"user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36"}
    try:
        r = requests.get(url, headers=header, timeout=10)
        r.raise_for_status()
        r.encoding = r.apparent_encoding
        return bs(r.text, "html.parser").get_text(separator='\n', strip=True)[:1000]
    except Exception as e:
        return f"Error: {e}"


if __name__ == "__main__":
    print("启动 MCP 服务器...", file=sys.stderr)  # 关键：日志走 stderr，避免污染 stdio
    mcp.run(transport='stdio')
