# 智阅 (ZhiYue) MCP 智能体平台 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a runnable 4-service microservice platform — an AI agent (DeepSeek) that plans and calls MCP-exposed web-crawling/storage tools — containerized with Docker and pushable to Aliyun ACR, fully covering《MCP实验指导书》.

**Architecture:** `api-gateway` (FastAPI + web UI) → `agent-service` (LLM tool-use loop + MCP client) → `mcp-tool-service` (FastMCP, dual stdio+SSE transport, hosts all tools) → `storage-service` (FastAPI + SQLite). Agent reaches all capabilities only through MCP.

**Tech Stack:** Python 3.11, FastAPI, uvicorn, `mcp` (FastMCP + client), `openai` SDK (DeepSeek), requests, BeautifulSoup4, httpx, SQLite, pytest, Docker, docker-compose.

---

## File Structure

```
services/
  storage-service/   db.py, app.py, requirements.txt, Dockerfile
  mcp-tool-service/  tools.py, mcp_server.py, requirements.txt, Dockerfile
  agent-service/     mcp_client.py, agent.py, app.py, requirements.txt, Dockerfile
  api-gateway/       app.py, static/index.html, requirements.txt, Dockerfile
guide-baseline/      web_content_mcp.py, requirements.txt, Dockerfile, cline_mcp_settings.json
deploy/              docker-compose.yml, .env.example
tests/               conftest.py, fixtures/sample.html, test_tools.py, test_storage.py, test_agent.py
scripts/             push_aliyun.sh, smoke_test.py
报告/                 (生成的 docx + 截图)
```

Build order = dependency order: storage → tools → agent → gateway → guide-baseline → containerization → integration/verify → aliyun → report.

---

## Phase 0 — Scaffolding

### Task 0: Create directory tree + top-level files

**Files:** create all dirs under `services/`, `guide-baseline/`, `deploy/`, `tests/fixtures/`, `scripts/`, `报告/`.

- [ ] **Step 1:** Create directories.
```bash
mkdir -p services/storage-service services/mcp-tool-service services/agent-service services/api-gateway/static guide-baseline deploy tests/fixtures scripts 报告
```
- [ ] **Step 2:** Commit.
```bash
git add -A && git commit -m "chore: scaffold project directories"
```

---

## Phase 1 — storage-service (TDD)

### Task 1: SQLite data layer (`db.py`)

**Files:**
- Create: `services/storage-service/db.py`
- Test: `tests/test_storage.py`

- [ ] **Step 1: Write failing test** (`tests/test_storage.py`)
```python
import os, tempfile
import importlib.util

def _load_db(path):
    spec = importlib.util.spec_from_file_location("zdb", "services/storage-service/db.py")
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    m.init_db(path)
    return m

def test_add_and_get(tmp_path):
    db = _load_db(str(tmp_path/"t.db"))
    rid = db.add_document(str(tmp_path/"t.db"), "http://a", "T", "hello world")
    doc = db.get_document(str(tmp_path/"t.db"), rid)
    assert doc["url"] == "http://a" and doc["content"] == "hello world"
    assert doc["content_length"] == 11

def test_search(tmp_path):
    p = str(tmp_path/"t.db"); db = _load_db(p)
    db.add_document(p, "http://a", "AI news", "machine learning rocks")
    db.add_document(p, "http://b", "Cooking", "pasta recipe")
    res = db.search_documents(p, "machine", 10)
    assert len(res) == 1 and res[0]["url"] == "http://a"

def test_stats(tmp_path):
    p = str(tmp_path/"t.db"); db = _load_db(p)
    db.add_document(p, "http://a", "T", "x")
    s = db.stats(p)
    assert s["count"] == 1
```
- [ ] **Step 2: Run, verify FAIL** — `python -m pytest tests/test_storage.py -v` → FAIL (module/functions missing).
- [ ] **Step 3: Implement** (`services/storage-service/db.py`)
```python
"""SQLite data-access layer for the storage-service."""
import sqlite3
from datetime import datetime, timezone

DEFAULT_DB = "/data/zhiyue.db"

def _conn(path):
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    return c

def init_db(path=DEFAULT_DB):
    with _conn(path) as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT NOT NULL,
                title TEXT,
                content TEXT,
                content_length INTEGER,
                created_at TEXT NOT NULL
            )""")

def add_document(path, url, title, content):
    now = datetime.now(timezone.utc).isoformat()
    with _conn(path) as c:
        cur = c.execute(
            "INSERT INTO documents(url,title,content,content_length,created_at) VALUES(?,?,?,?,?)",
            (url, title, content, len(content or ""), now))
        return cur.lastrowid

def get_document(path, doc_id):
    with _conn(path) as c:
        row = c.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
        return dict(row) if row else None

def search_documents(path, query, limit=5):
    like = f"%{query}%"
    with _conn(path) as c:
        rows = c.execute(
            "SELECT * FROM documents WHERE content LIKE ? OR title LIKE ? OR url LIKE ? "
            "ORDER BY id DESC LIMIT ?", (like, like, like, limit)).fetchall()
        return [dict(r) for r in rows]

def stats(path):
    with _conn(path) as c:
        row = c.execute("SELECT COUNT(*) n, MAX(created_at) last FROM documents").fetchone()
        return {"count": row["n"], "last_crawled_at": row["last"]}
```
- [ ] **Step 4: Run, verify PASS** — `python -m pytest tests/test_storage.py -v`.
- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat(storage): sqlite data layer + tests"`

### Task 2: storage-service FastAPI app (`app.py`)

**Files:** Create `services/storage-service/app.py`, `services/storage-service/requirements.txt`; append to `tests/test_storage.py`.

- [ ] **Step 1: Write failing API test** (append to `tests/test_storage.py`)
```python
def test_api(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path/"api.db"))
    import importlib, sys
    sys.path.insert(0, "services/storage-service")
    app_mod = importlib.import_module("app"); importlib.reload(app_mod)
    from fastapi.testclient import TestClient
    cli = TestClient(app_mod.app)
    assert cli.get("/health").json()["status"] == "ok"
    r = cli.post("/documents", json={"url":"http://a","title":"T","content":"deep learning"})
    assert r.status_code == 200; doc_id = r.json()["id"]
    assert cli.get(f"/documents/{doc_id}").json()["content"] == "deep learning"
    assert len(cli.get("/documents", params={"q":"deep"}).json()) == 1
    assert cli.get("/stats").json()["count"] == 1
```
- [ ] **Step 2: Run, verify FAIL**.
- [ ] **Step 3: Implement** (`services/storage-service/app.py`)
```python
"""storage-service: persistence & search API (FastAPI + SQLite)."""
import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import db

DB_PATH = os.getenv("DB_PATH", db.DEFAULT_DB)
app = FastAPI(title="zhiyue-storage-service")

@app.on_event("startup")
def _startup():
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    db.init_db(DB_PATH)

class DocIn(BaseModel):
    url: str
    title: str = ""
    content: str = ""

@app.get("/health")
def health():
    return {"status": "ok", "service": "storage-service"}

@app.post("/documents")
def create(doc: DocIn):
    rid = db.add_document(DB_PATH, doc.url, doc.title, doc.content)
    return db.get_document(DB_PATH, rid)

@app.get("/documents")
def search(q: str = "", limit: int = 5):
    return db.search_documents(DB_PATH, q, limit)

@app.get("/documents/{doc_id}")
def get_one(doc_id: int):
    d = db.get_document(DB_PATH, doc_id)
    if not d:
        raise HTTPException(404, "not found")
    return d

@app.get("/stats")
def stats():
    return db.stats(DB_PATH)
```
- [ ] **Step 4:** `requirements.txt`:
```
fastapi>=0.110.0
uvicorn[standard]>=0.27.0
pydantic>=2.0.0
```
- [ ] **Step 5: Run, verify PASS**.
- [ ] **Step 6: Commit** — `git add -A && git commit -m "feat(storage): FastAPI CRUD+search API"`

---

## Phase 2 — mcp-tool-service (TDD)

### Task 3: Pure crawler functions (`tools.py`)

**Files:** Create `services/mcp-tool-service/tools.py`, `tests/fixtures/sample.html`, `tests/test_tools.py`.

- [ ] **Step 1: Fixture** (`tests/fixtures/sample.html`)
```html
<!DOCTYPE html><html><head><title>Sample Page</title><style>.x{}</style>
<script>var a=1;</script></head><body>
<h1>Hello World</h1><p>This is a test paragraph about microservices.</p>
<ul class="items"><li class="item">Alpha</li><li class="item">Beta</li></ul>
<a href="/about">About</a><a href="https://ext.com/x">External</a></body></html>
```
- [ ] **Step 2: Failing test** (`tests/test_tools.py`)
```python
import importlib.util
def _tools():
    spec = importlib.util.spec_from_file_location("ztools", "services/mcp-tool-service/tools.py")
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m

HTML = open("tests/fixtures/sample.html", encoding="utf-8").read()

def test_clean_text():
    t = _tools()
    out = t.html_to_text(HTML)
    assert "Hello World" in out and "microservices" in out
    assert "var a=1" not in out  # script stripped

def test_extract_links():
    t = _tools()
    links = t.extract_links_from_html(HTML, base_url="http://site.com/page")
    hrefs = {l["href"] for l in links}
    assert "http://site.com/about" in hrefs       # relative -> absolute
    assert "https://ext.com/x" in hrefs

def test_crawl_structured():
    t = _tools()
    items = t.crawl_structured_from_html(HTML, ".item")
    assert [i["text"] for i in items] == ["Alpha", "Beta"]
```
- [ ] **Step 3: Run, verify FAIL**.
- [ ] **Step 4: Implement** (`services/mcp-tool-service/tools.py`)
```python
"""Pure, unit-testable crawling/parsing helpers (no network in the pure ones)."""
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup as bs

HEADERS = {"user-agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
           "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36")}

def fetch_html(url, timeout=10):
    r = requests.get(url, headers=HEADERS, timeout=timeout)
    r.raise_for_status()
    r.encoding = r.apparent_encoding
    return r.text

def html_to_text(html):
    soup = bs(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return soup.get_text(separator="\n", strip=True)

def get_title(html):
    soup = bs(html, "html.parser")
    return soup.title.get_text(strip=True) if soup.title else ""

def extract_links_from_html(html, base_url=""):
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
    soup = bs(html, "html.parser")
    out = []
    for el in soup.select(selector):
        link = el.find("a", href=True)
        out.append({"text": el.get_text(strip=True),
                    "href": link["href"] if link else None})
    return out
```
- [ ] **Step 5: Run, verify PASS**.
- [ ] **Step 6: Commit** — `git add -A && git commit -m "feat(mcp): pure crawler/parser helpers + tests"`

### Task 4: FastMCP server (`mcp_server.py`)

**Files:** Create `services/mcp-tool-service/mcp_server.py`, `services/mcp-tool-service/requirements.txt`.

- [ ] **Step 1: Implement** (`services/mcp-tool-service/mcp_server.py`)
```python
"""mcp-tool-service: FastMCP server exposing crawler + data tools.

Dual transport:
  MCP_TRANSPORT=stdio  -> for `mcp dev` / MCP Inspector / Cline (指导书第三~五步)
  MCP_TRANSPORT=sse    -> HTTP/SSE on :8002 for the agent-service (microservice mode)
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
    用于：用户想阅读/总结某个网页时。"""
    try:
        text = tools.html_to_text(tools.fetch_html(url))
        return text[:4000]
    except Exception as e:
        return f"Error: {e}"

@mcp.tool()
def extract_links(url: str) -> list:
    """提取网页中的所有超链接，返回 [{text, href}]，相对链接会被转为绝对链接。"""
    try:
        return tools.extract_links_from_html(tools.fetch_html(url), base_url=url)
    except Exception as e:
        return [{"error": str(e)}]

@mcp.tool()
def crawl_structured(url: str, selector: str) -> list:
    """按 CSS 选择器抽取结构化条目，返回 [{text, href}]。
    例：selector='.item' 抽取列表项；用于结构化爬取。"""
    try:
        return tools.crawl_structured_from_html(tools.fetch_html(url), selector)
    except Exception as e:
        return [{"error": str(e)}]

@mcp.tool()
def save_document(url: str, title: str, content: str) -> dict:
    """把一篇网页内容保存到智能体的记忆库（storage-service），返回文档 id。"""
    try:
        r = httpx.post(f"{STORAGE_URL}/documents",
                       json={"url": url, "title": title, "content": content}, timeout=15)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"error": str(e)}

@mcp.tool()
def search_documents(query: str, limit: int = 5) -> list:
    """在记忆库中检索此前抓取过的网页（按关键词模糊匹配标题/正文/URL）。"""
    try:
        r = httpx.get(f"{STORAGE_URL}/documents", params={"q": query, "limit": limit}, timeout=15)
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
```
- [ ] **Step 2:** `requirements.txt`:
```
mcp>=1.2.0
requests>=2.31.0
beautifulsoup4>=4.12.0
httpx>=0.27.0
uvicorn[standard]>=0.27.0
```
- [ ] **Step 3: Smoke check import** — `cd services/mcp-tool-service && python -c "import mcp_server; print([t for t in dir(mcp_server) if not t.startswith('_')])"` (expects no import error; needs `pip install -r requirements.txt`).
- [ ] **Step 4: Commit** — `git add -A && git commit -m "feat(mcp): FastMCP server w/ crawler+data tools, dual transport"`

---

## Phase 3 — agent-service (LLM tool-use loop + MCP client)

### Task 5: MCP client wrapper (`mcp_client.py`)

**Files:** Create `services/agent-service/mcp_client.py`.

- [ ] **Step 1: Implement** (`services/agent-service/mcp_client.py`)
```python
"""Async MCP client: connect to mcp-tool-service over SSE, list & call tools."""
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
    """Return MCP tools as OpenAI function-calling schema list."""
    resp = await session.list_tools()
    out = []
    for t in resp.tools:
        out.append({"type": "function", "function": {
            "name": t.name,
            "description": t.description or "",
            "parameters": t.inputSchema or {"type": "object", "properties": {}},
        }})
    return out

async def call_tool(session, name, arguments):
    res = await session.call_tool(name, arguments or {})
    parts = []
    for c in res.content:
        parts.append(getattr(c, "text", str(c)))
    return "\n".join(parts)
```
- [ ] **Step 2: Commit** — `git add -A && git commit -m "feat(agent): async MCP SSE client wrapper"`

### Task 6: Agent loop (`agent.py`) — TDD with fakes

**Files:** Create `services/agent-service/agent.py`, `tests/test_agent.py`.

- [ ] **Step 1: Failing test** (`tests/test_agent.py`) — drives the loop with a fake LLM + fake MCP session so it runs offline.
```python
import asyncio, importlib.util, types

def _agent():
    spec = importlib.util.spec_from_file_location("zagent", "services/agent-service/agent.py")
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m

class FakeMsg:
    def __init__(self, content=None, tool_calls=None):
        self.content = content; self.tool_calls = tool_calls
class FakeTC:
    def __init__(self, name, args, idx="c1"):
        self.id = idx; self.type="function"
        self.function = types.SimpleNamespace(name=name, arguments=args)

class FakeLLM:
    """First reply asks to call get_web_content, second returns final answer."""
    def __init__(self): self.n = 0
    class chat:
        pass
    def __init__(self):
        self.n = 0
        self.chat = types.SimpleNamespace(completions=types.SimpleNamespace(create=self._create))
    def _create(self, **kw):
        self.n += 1
        if self.n == 1:
            tc = FakeTC("get_web_content", '{"url":"http://x"}')
            return types.SimpleNamespace(choices=[types.SimpleNamespace(message=FakeMsg(None,[tc]))])
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=FakeMsg("最终答案：页面讲微服务",None))])

class FakeSession:
    async def list_tools_openai(self): return []
    async def call_tool(self, name, args): return "页面正文：微服务架构"

def test_agent_loop_runs_offline():
    agent = _agent()
    tools_schema = [{"type":"function","function":{"name":"get_web_content","description":"d","parameters":{"type":"object","properties":{"url":{"type":"string"}}}}}]
    async def fake_list(session): return tools_schema
    async def fake_call(session, name, args): return "页面正文：微服务架构"
    out = asyncio.run(agent.run_loop(
        message="抓取并总结 http://x",
        llm=FakeLLM(), model="m", session=object(),
        list_tools=fake_list, call_tool=fake_call, max_iters=5))
    assert "最终答案" in out["answer"]
    assert out["tool_calls"][0]["name"] == "get_web_content"
```
- [ ] **Step 2: Run, verify FAIL**.
- [ ] **Step 3: Implement** (`services/agent-service/agent.py`) — note: `run_loop` takes injectable `llm/list_tools/call_tool` for testability; `run_agent` wires the real ones.
```python
"""The agent brain: an LLM tool-use loop over MCP tools."""
import os, json

SYSTEM_PROMPT = (
    "你是'智阅'智能网页助手。你可以调用工具来抓取网页(get_web_content)、提取链接(extract_links)、"
    "结构化爬取(crawl_structured)、把内容存入记忆库(save_document)、检索历史(search_documents)。"
    "规划合理的工具调用来完成用户请求；抓取到正文后，如用户要求总结/分析，请基于正文作答，并在合适时用 "
    "save_document 保存。用中文简洁作答，并在末尾标注信息来源 URL。"
)

async def run_loop(message, llm, model, session, list_tools, call_tool, max_iters=5):
    tools_schema = await list_tools(session)
    messages = [{"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": message}]
    used = []
    for _ in range(max_iters):
        resp = llm.chat.completions.create(
            model=model, messages=messages, tools=tools_schema or None,
            tool_choice="auto" if tools_schema else "none", temperature=0.3)
        msg = resp.choices[0].message
        tool_calls = getattr(msg, "tool_calls", None)
        if not tool_calls:
            return {"answer": msg.content or "", "tool_calls": used,
                    "sources": [u["args"].get("url") for u in used if "url" in u.get("args", {})]}
        messages.append({"role": "assistant", "content": msg.content,
                         "tool_calls": [{"id": tc.id, "type": "function",
                            "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                            for tc in tool_calls]})
        for tc in tool_calls:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except Exception:
                args = {}
            result = await call_tool(session, tc.function.name, args)
            used.append({"name": tc.function.name, "args": args})
            messages.append({"role": "tool", "tool_call_id": tc.id,
                             "name": tc.function.name, "content": str(result)[:4000]})
    return {"answer": "（已达到最大工具调用轮数，请缩小问题范围）", "tool_calls": used, "sources": []}

async def run_agent(message):
    from openai import OpenAI
    import mcp_client
    llm = OpenAI(base_url=os.getenv("LLM_BASE_URL", "https://api.deepseek.com"),
                 api_key=os.getenv("LLM_API_KEY", ""))
    model = os.getenv("LLM_MODEL", "deepseek-chat")
    async with mcp_client.open_session() as session:
        return await run_loop(message, llm, model, session,
                              mcp_client.list_tools_openai, mcp_client.call_tool)
```
- [ ] **Step 4: Run, verify PASS** — `python -m pytest tests/test_agent.py -v`.
- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat(agent): LLM tool-use loop (injectable, tested offline)"`

### Task 7: agent-service FastAPI app (`app.py`)

**Files:** Create `services/agent-service/app.py`, `services/agent-service/requirements.txt`.

- [ ] **Step 1: Implement** (`services/agent-service/app.py`)
```python
"""agent-service: HTTP front for the agent brain."""
from fastapi import FastAPI
from pydantic import BaseModel
import agent

app = FastAPI(title="zhiyue-agent-service")

class ChatIn(BaseModel):
    message: str
    session_id: str = "default"

@app.get("/health")
def health():
    return {"status": "ok", "service": "agent-service"}

@app.post("/chat")
async def chat(body: ChatIn):
    try:
        return await agent.run_agent(body.message)
    except Exception as e:
        return {"answer": f"智能体出错：{e}", "tool_calls": [], "sources": []}
```
- [ ] **Step 2:** `requirements.txt`:
```
fastapi>=0.110.0
uvicorn[standard]>=0.27.0
pydantic>=2.0.0
openai>=1.30.0
mcp>=1.2.0
httpx>=0.27.0
```
- [ ] **Step 3: Commit** — `git add -A && git commit -m "feat(agent): FastAPI /chat endpoint"`

---

## Phase 4 — api-gateway + Web UI

### Task 8: Gateway app (`app.py`)

**Files:** Create `services/api-gateway/app.py`, `services/api-gateway/requirements.txt`.

- [ ] **Step 1: Implement** (`services/api-gateway/app.py`)
```python
"""api-gateway: single entry, serves Web UI, forwards to agent & storage."""
import os
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

AGENT_URL = os.getenv("AGENT_URL", "http://agent-service:8001")
STORAGE_URL = os.getenv("STORAGE_URL", "http://storage-service:8003")
HERE = os.path.dirname(__file__)

app = FastAPI(title="zhiyue-api-gateway")
_metrics = {"requests": 0, "chat": 0}

@app.get("/health")
def health():
    return {"status": "ok", "service": "api-gateway"}

@app.get("/metrics")
def metrics():
    return JSONResponse(_metrics)

@app.post("/api/chat")
async def chat(req: Request):
    _metrics["requests"] += 1; _metrics["chat"] += 1
    body = await req.json()
    async with httpx.AsyncClient(timeout=120) as c:
        r = await c.post(f"{AGENT_URL}/chat", json=body)
        return JSONResponse(r.json(), status_code=r.status_code)

@app.get("/api/documents")
async def documents(q: str = "", limit: int = 10):
    _metrics["requests"] += 1
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(f"{STORAGE_URL}/documents", params={"q": q, "limit": limit})
        return JSONResponse(r.json(), status_code=r.status_code)

@app.get("/")
def index():
    return FileResponse(os.path.join(HERE, "static", "index.html"))

app.mount("/static", StaticFiles(directory=os.path.join(HERE, "static")), name="static")
```
- [ ] **Step 2:** `requirements.txt`:
```
fastapi>=0.110.0
uvicorn[standard]>=0.27.0
httpx>=0.27.0
```
- [ ] **Step 3: Commit** — `git add -A && git commit -m "feat(gateway): entry + forwarding + metrics"`

### Task 9: Web chat UI (`static/index.html`)

**Files:** Create `services/api-gateway/static/index.html`.

- [ ] **Step 1: Implement** a clean single-page chat UI (vanilla HTML/CSS/JS): a header, a scrollable message list, an input box + send button, a side panel showing tool calls/sources, calls `POST /api/chat`. (Full file written during execution; must: render user+assistant bubbles, show `tool_calls` and `sources`, handle loading state, be visually polished — dark/clean theme, system font stack, no external CDN so it works offline.)
- [ ] **Step 2: Commit** — `git add -A && git commit -m "feat(gateway): web chat UI"`

---

## Phase 5 — guide-baseline (指导书原样复现)

### Task 10: Exact guide single-file MCP + Docker

**Files:** Create `guide-baseline/web_content_mcp.py`, `guide-baseline/requirements.txt`, `guide-baseline/Dockerfile`, `guide-baseline/cline_mcp_settings.json`.

- [ ] **Step 1:** `web_content_mcp.py` — the guide's exact server.
```python
#!/usr/bin/env python3
"""测试 MCP 服务器 (指导书第二步原样)"""
import requests
from bs4 import BeautifulSoup as bs
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Web Scraper")

@mcp.tool()
def get_web_content(url: str) -> str:
    """获取网页内容"""
    header = {"user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36"}
    try:
        r = requests.get(url, headers=header, timeout=10)
        r.raise_for_status()
        r.encoding = r.apparent_encoding
        soup = bs(r.text, "html.parser")
        return soup.get_text(separator='\n', strip=True)[:1000]
    except Exception as e:
        return f"Error: {e}"

if __name__ == "__main__":
    print("启动 MCP 服务器...")
    mcp.run(transport='stdio')
```
- [ ] **Step 2:** `requirements.txt`:
```
requests>=2.31.0
beautifulsoup4>=4.12.0
mcp>=1.0.0
```
- [ ] **Step 3:** `Dockerfile` (指导书第六步原样模式):
```dockerfile
FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY web_content_mcp.py .
RUN useradd -m -u 1000 mcpuser && chown -R mcpuser:mcpuser /app
USER mcpuser
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
CMD ["python", "web_content_mcp.py"]
```
- [ ] **Step 4:** `cline_mcp_settings.json` (第四步模板):
```json
{
  "mcpServers": {
    "web-content-fetcher": {
      "command": "python",
      "args": ["D:/微服务架构2/guide-baseline/web_content_mcp.py"]
    }
  }
}
```
- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat(guide): exact 指导书 baseline MCP + Dockerfile + cline config"`

---

## Phase 6 — Containerization

### Task 11: Per-service Dockerfiles

**Files:** Create `Dockerfile` in each of the 4 services. Pattern (adapt `CMD` per service):

storage-service:
```dockerfile
FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN useradd -m -u 1000 mcpuser && chown -R mcpuser:mcpuser /app
USER mcpuser
ENV PYTHONUNBUFFERED=1
EXPOSE 8003
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8003"]
```
- mcp-tool-service: same, `EXPOSE 8002`, `ENV MCP_TRANSPORT=sse`, `CMD ["python","mcp_server.py"]`.
- agent-service: same, `EXPOSE 8001`, `CMD ["uvicorn","app:app","--host","0.0.0.0","--port","8001"]`.
- api-gateway: same, `EXPOSE 8080`, `CMD ["uvicorn","app:app","--host","0.0.0.0","--port","8080"]`.

- [ ] **Step 1:** Write all 4 Dockerfiles. **Step 2:** Commit `git add -A && git commit -m "feat: per-service Dockerfiles"`.

### Task 12: docker-compose + env

**Files:** Create `deploy/docker-compose.yml`, `deploy/.env.example`.

- [ ] **Step 1:** `deploy/.env.example`:
```
LLM_BASE_URL=https://api.deepseek.com
LLM_API_KEY=sk-REPLACE_ME
LLM_MODEL=deepseek-chat
```
- [ ] **Step 2:** `deploy/docker-compose.yml`:
```yaml
name: zhiyue
services:
  storage-service:
    build: ../services/storage-service
    image: zhiyue/storage-service:latest
    environment: { DB_PATH: /data/zhiyue.db }
    volumes: [ "zhiyue-data:/data" ]
    networks: [ zhiyue-net ]
    healthcheck:
      test: ["CMD","python","-c","import urllib.request;urllib.request.urlopen('http://localhost:8003/health')"]
      interval: 10s
      timeout: 5s
      retries: 5

  mcp-tool-service:
    build: ../services/mcp-tool-service
    image: zhiyue/mcp-tool-service:latest
    environment:
      MCP_TRANSPORT: sse
      MCP_HOST: 0.0.0.0
      MCP_PORT: "8002"
      STORAGE_URL: http://storage-service:8003
    depends_on: [ storage-service ]
    networks: [ zhiyue-net ]

  agent-service:
    build: ../services/agent-service
    image: zhiyue/agent-service:latest
    env_file: [ .env ]
    environment:
      MCP_SSE_URL: http://mcp-tool-service:8002/sse
    depends_on: [ mcp-tool-service ]
    networks: [ zhiyue-net ]

  api-gateway:
    build: ../services/api-gateway
    image: zhiyue/api-gateway:latest
    environment:
      AGENT_URL: http://agent-service:8001
      STORAGE_URL: http://storage-service:8003
    ports: [ "8080:8080" ]
    depends_on: [ agent-service ]
    networks: [ zhiyue-net ]

networks:
  zhiyue-net: {}
volumes:
  zhiyue-data: {}
```
- [ ] **Step 3: Commit** — `git add -A && git commit -m "feat: docker-compose orchestration + .env.example"`

---

## Phase 7 — Integration & Verification

### Task 13: Smoke test script

**Files:** Create `scripts/smoke_test.py`.

- [ ] **Step 1:** Implement a script that, against a running stack: GET `/health` on gateway, POST `/api/chat` with "抓取并总结 https://example.com 的内容", asserts non-empty answer + at least one tool_call, then GET `/api/documents?q=example` asserts the doc was stored. Prints a PASS/FAIL summary.
- [ ] **Step 2:** Run locally (requires `pip install -r` for each service or running compose).

### Task 14: End-to-end run (manual, needs DeepSeek key + Docker)
- [ ] `cp deploy/.env.example deploy/.env` and put the real `LLM_API_KEY`.
- [ ] `cd deploy && docker compose build` — expect 4 images built.
- [ ] `docker compose up -d` — expect 4 containers Up.
- [ ] `docker compose ps` (screenshot), `python ../scripts/smoke_test.py` (screenshot), open `http://localhost:8080` (screenshot chat).
- [ ] `mcp dev services/mcp-tool-service/mcp_server.py` on host → Inspector → run `get_web_content` (screenshot).
- [ ] Configure Cline with `guide-baseline/cline_mcp_settings.json` → green dot → ask for a page (screenshot).

---

## Phase 8 — Aliyun ACR

### Task 15: Push script

**Files:** Create `scripts/push_aliyun.sh`.

- [ ] **Step 1:** Implement parameterized push:
```bash
#!/usr/bin/env bash
set -e
REGISTRY="${1:?registry e.g. registry.cn-hangzhou.aliyuncs.com}"
NS="${2:?namespace}"
TAG="${3:-latest}"
SVCS="storage-service mcp-tool-service agent-service api-gateway"
echo ">> docker login $REGISTRY"; docker login "$REGISTRY"
for s in $SVCS; do
  docker tag "zhiyue/$s:latest" "$REGISTRY/$NS/$s:$TAG"
  docker push "$REGISTRY/$NS/$s:$TAG"
done
# 指导书第七步原样镜像
docker tag mcp-web-scraper:latest "$REGISTRY/$NS/mcp-web-scraper:$TAG" || true
docker push "$REGISTRY/$NS/mcp-web-scraper:$TAG" || true
echo ">> done"
```
- [ ] **Step 2: Run** (needs user's ACR creds) → screenshot push output + Aliyun console repo list.
- [ ] **Step 3: Commit** — `git add -A && git commit -m "feat: aliyun ACR push script"`

---

## Phase 9 — Report

### Task 16: Generate `报告/学号+姓名.docx`
- [ ] Collect cover info + all screenshots from Phase 7/8.
- [ ] Generate docx (python-docx) following the template's 8 sections, embedding architecture diagram, code excerpts, screenshots, test output, and the 指导书 step-by-step mapping. File named `学号+姓名.docx`.
- [ ] Final read-through against template + rubric.

---

## Self-Review (against spec)

- **Spec coverage:** §3 architecture → Tasks 1–9,11,12. §4 MCP tools → Tasks 3,4. §5 agent loop → Tasks 5–7. §6 service specs → Tasks 2,4,7,8. §7 data model → Task 1. §8 containerization → Tasks 10–12. §9 Aliyun → Task 15. §10 testing → Tasks 1–6,13,14. §11 report → Task 16. §2 traceability (指导书) → Task 10 (verbatim) + Tasks 3,4 (extended) + Task 14 (Inspector/Cline) + Task 15 (Aliyun). All covered.
- **Placeholder scan:** Task 9 (UI) and Task 13/16 describe behavior rather than full code — these are HTML/report artifacts written during execution where exact bytes are not load-bearing; all *service logic* has complete code. Acceptable.
- **Type consistency:** `run_loop(message, llm, model, session, list_tools, call_tool, max_iters)` consistent between Task 6 test, impl, and `run_agent`. Tool names (`get_web_content`, `extract_links`, `crawl_structured`, `save_document`, `search_documents`) consistent across Tasks 4/5/6 and system prompt. Storage funcs (`add_document`, `get_document`, `search_documents`, `stats`) consistent Task 1↔2. `DB_PATH`/`STORAGE_URL`/`MCP_SSE_URL`/`LLM_*` env names consistent across services and compose.
```
