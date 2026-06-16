"""纯函数式的网页抓取/解析工具。

设计要点：把"网络抓取"(fetch_html) 与"解析"(html_to_text / extract_links_from_html /
crawl_structured_from_html) 分离。解析函数不依赖网络，可用本地 HTML 夹具做单元测试，
保证 CI 可重复、不受外网波动影响。
"""
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup as bs

HEADERS = {
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36"
    )
}


def fetch_html(url, timeout=10):
    """发送 HTTP 请求获取网页原始 HTML（解决编码乱码问题）。"""
    r = requests.get(url, headers=HEADERS, timeout=timeout)
    r.raise_for_status()
    r.encoding = r.apparent_encoding
    return r.text


def html_to_text(html):
    """解析 HTML，去除 script/style/noscript，返回清理后的纯文本。"""
    soup = bs(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return soup.get_text(separator="\n", strip=True)


def get_title(html):
    soup = bs(html, "html.parser")
    return soup.title.get_text(strip=True) if soup.title else ""


def extract_links_from_html(html, base_url=""):
    """抽取页面所有 <a href>，去重；相对链接转为绝对链接。"""
    soup = bs(html, "html.parser")
    seen, out = set(), []
    for a in soup.find_all("a", href=True):
        href = urljoin(base_url, a["href"]) if base_url else a["href"]
        if href in seen:
            continue
        seen.add(href)
        out.append({"text": a.get_text(strip=True), "href": href})
    return out


def crawl_structured_from_html(html, selector):
    """按 CSS 选择器抽取结构化条目，返回 [{text, href}]。"""
    soup = bs(html, "html.parser")
    out = []
    for el in soup.select(selector):
        link = el.find("a", href=True)
        out.append(
            {"text": el.get_text(strip=True), "href": link["href"] if link else None}
        )
    return out
