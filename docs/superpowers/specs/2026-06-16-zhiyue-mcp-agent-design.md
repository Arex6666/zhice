# 设计规格说明书：智阅 (ZhiYue) — 基于 MCP 的智能网页采集与分析智能体平台

> WebSage — an MCP-powered intelligent web-content collection & analysis agent platform.
> 日期：2026-06-16 ｜ 课程：微服务架构实践（大作业）

---

## 1. 概述与目标 (Overview & Goals)

构建一个**具有明确业务功能的微服务系统**：一个"智能体（AI Agent）"，用户用自然语言提出网页采集/分析需求，智能体借助**真实大模型（DeepSeek）**进行规划，调用一组以 **MCP（Model Context Protocol）**协议暴露的工具（爬虫、结构化抽取、链接提取、存储、检索）完成任务，并将结果持久化、可检索。

### 设计目标
- **G1 微服务架构**：核心功能由多个可独立部署、独立运行、通过明确接口通信的服务组成。
- **G2 MCP 加分项**：核心工具以标准 MCP 服务暴露，可被 MCP Inspector 与 Cline 直接使用，亦可被本系统的智能体通过 MCP 客户端跨容器调用。
- **G3 容器化 + 阿里云**：所有服务 Docker 化，`docker-compose` 一键编排，镜像推送至阿里云容器镜像服务（ACR）。
- **G4 智能体（真实 LLM）**：使用 DeepSeek 进行工具规划（function-calling / tool-use 循环）。
- **G5 完整可运行可验证**：端到端可跑通，含单元测试、集成测试、真实运行截图。
- **G6 严格覆盖《MCP实验指导书》全部步骤**：确保 80 分基础分，并在其上叠加加分。

### 非目标 (Out of scope，列入未来展望)
- 服务注册中心 / 配置中心（Nacos/Consul）、消息队列、Kubernetes、Prometheus+Grafana 全套可观测性 —— 仅做轻量替代（健康检查 + `/metrics` 文本端点），重型基础设施列为未来工作。
- 分布式数据库 / 高可用 —— 使用 SQLite + 卷持久化，足够演示，Postgres 列为未来工作。
- 用户鉴权 / 多租户。

---

## 2. 需求溯源矩阵 (Requirements Traceability)

### 2.1 课程要求 → 实现
| 课程要求 | 实现方式 |
|---|---|
| 具有明确业务功能的微服务系统 | 智能网页采集分析智能体，4 个微服务 |
| 核心功能以微服务架构完成 | api-gateway / agent-service / mcp-tool-service / storage-service |
| 封装为 MCP 服务（加分项） | mcp-tool-service 为标准 FastMCP 服务，双传输（stdio + SSE/HTTP） |
| Docker 容器化 + 推送阿里云 | 每服务独立 Dockerfile + docker-compose + ACR 推送 |
| 完整报告（设计/实现/部署/测试） | 按模板生成 `学号+姓名.docx` |

### 2.2 《MCP实验指导书》步骤 → 实现（保 80 分）
| 指导书步骤 | 本系统对应 |
|---|---|
| 第一步 环境准备（Python 3.8+，pip 安装 requests/bs4） | 实验环境章节 + requirements.txt |
| 第二步 创建 MCP 服务（FastMCP，`get_web_content`，stdio） | mcp-tool-service 内含**与指导书一致**的 `get_web_content(url)` 工具；`guide-baseline/` 另存一份指导书原样单文件版本 |
| 第三步 测试（`mcp dev`，MCP Inspector，Connect，运行工具） | 用 `mcp dev` 启动，截图 Inspector 运行 `get_web_content` |
| 第四步 配置 Cline（`cline_mcp_settings.json`，绿点） | 提供配置文件并截图绿点 |
| 第五步 在 Cline 中使用（自然语言获取网页） | 截图 Cline 调用工具 |
| 第六步 封装 Docker（python:3.11-slim，非 root mcpuser，requirements，build/run） | `guide-baseline/Dockerfile` 与指导书一致；各服务亦遵循同样模式 |
| 第七步 上传阿里云 | `scripts/push_aliyun.sh` + 文档化命令 + 截图 |

---

## 3. 系统架构 (Architecture)

```
                         ┌──────────────────────────┐
        浏览器  ───────▶  │  api-gateway (FastAPI)    │  :8080
       (Web Chat UI)      │  · 静态聊天界面            │
                          │  · POST /api/chat ─────────┼──HTTP──┐
                          │  · GET  /api/documents ────┼──HTTP──┼──┐ (历史浏览)
                          │  · /health /metrics       │        │  │
                          └───────────────────────────┘        │  │
                                                                ▼  │
                                          ┌──────────────────────────┐
                                          │  agent-service (FastAPI)  │  :8001
                                          │  · LLM 规划循环 (DeepSeek) │
                                          │  · MCP 客户端 (仅经 MCP)   │
                                          └───────────┬──────────────┘
                                                      │ MCP (SSE/HTTP)
                                                      ▼
                          ┌────────────────────────────┐
                          │ mcp-tool-service (FastMCP)  │ :8002  (stdio + SSE 双传输)
                          │ · get_web_content           │
                          │ · crawl_structured          │
                          │ · extract_links             │
                          │ · save_document ────────────┼──HTTP──┐
                          │ · search_documents ─────────┼──HTTP──┤
                          └────────────────────────────┘        │
                                                                 ▼
                                          ┌──────────────────────────┐
                          (gateway 历史浏览也指向此) ──────────────▶ │ storage-service :8003     │
                                          │ (FastAPI + SQLite, 持久卷)│
                                          │ · /documents CRUD + 搜索  │
                                          └──────────────────────────┘
```
说明：agent-service **只通过 MCP** 获取一切能力（包括存储/检索，它们是 mcp-tool-service 上的 MCP 工具，由该服务转调 storage-service）。api-gateway 的"历史浏览"面板可直连 storage-service 只读查询，不经过智能体。

### 服务清单
| 服务 | 技术 | 端口 | 职责 |
|---|---|---|---|
| api-gateway | FastAPI + 静态前端 | 8080 | 唯一入口，Web 聊天 UI，转发，CORS/日志/健康/指标 |
| agent-service | FastAPI + openai SDK + mcp SDK | 8001 | 智能体大脑：LLM 工具规划循环、MCP 客户端 |
| mcp-tool-service | FastMCP | 8002 | MCP 工具服务器：爬虫工具 + 数据工具 |
| storage-service | FastAPI + SQLite | 8003 | 文档持久化与检索（智能体的"记忆"） |

服务间通信：HTTP/REST（gateway↔agent↔storage）+ MCP over SSE（agent↔mcp-tool-service）。容器内通过 docker-compose 服务名互访。

---

## 4. MCP 设计 (MCP Design)

### 4.1 传输 (Dual transport)
- **stdio**：供 `mcp dev mcp_server.py`（MCP Inspector）与 Cline 使用 —— 直接满足指导书第三~五步。
- **SSE / streamable-HTTP**：供 agent-service 跨容器通过网络连接（`MCP_SSE_URL=http://mcp-tool-service:8002/sse`）。
- 通过环境变量 `MCP_TRANSPORT=stdio|sse` 切换入口。

### 4.2 工具清单 (MCP Tools)
| 工具 | 签名 | 说明 |
|---|---|---|
| `get_web_content` | `(url: str) -> str` | **指导书原样工具**：requests+bs4 抓取，清洗为纯文本，限制长度返回 |
| `crawl_structured` | `(url: str, selector: str) -> list[dict]` | 按 CSS 选择器抽取结构化条目（文本+链接） |
| `extract_links` | `(url: str) -> list[dict]` | 抽取页面所有链接（文本+href，去重，绝对化） |
| `save_document` | `(url: str, title: str, content: str) -> dict` | 调 storage-service 持久化文档，返回 id |
| `search_documents` | `(query: str, limit: int = 5) -> list[dict]` | 调 storage-service 全文检索历史文档 |

工具描述（docstring）面向 LLM 编写，清晰说明用途/参数/返回，便于模型正确选择。

---

## 5. 智能体设计 (Agent / LLM Design)

### 5.1 规划循环 (Tool-use loop)
```
1. 接收用户自然语言 query
2. 组装 system prompt + 工具 schema（从 MCP list_tools 动态获取）
3. 调用 DeepSeek chat.completions（tools=工具schema，tool_choice=auto）
4. 若返回 tool_calls：逐个经 MCP client 调用 mcp-tool-service，收集结果，回填为 tool message，回到 3
5. 若返回最终文本：作为答案返回（附带本轮使用的工具与来源）
6. 设 max_iters 防循环（默认 5 轮）
```

### 5.2 LLM 配置
- OpenAI 兼容：`openai` Python SDK。
- 环境变量：`LLM_BASE_URL=https://api.deepseek.com`、`LLM_API_KEY=<secret>`、`LLM_MODEL=deepseek-chat`。
- 安全网：LLM 调用异常时返回友好错误并记录日志（不让现场演示崩溃）；主路径始终为真实 LLM。

### 5.3 接口
- `POST /chat` body `{ "message": str, "session_id": str? }` → `{ "answer": str, "tool_calls": [...], "sources": [...] }`
- `GET /health`

---

## 6. 各服务接口规格 (Service Specs)

### 6.1 api-gateway (:8080)
- `GET /` → 聊天 Web UI（单页，原生 HTML/CSS/JS，简洁专业风）
- `POST /api/chat` → 转发至 agent-service `/chat`
- `GET /api/documents?q=` → 转发至 storage-service
- `GET /health`、`GET /metrics`（文本计数：请求数、各下游可用性）

### 6.2 agent-service (:8001)
- 见 §5.3。环境：`MCP_SSE_URL`、`LLM_BASE_URL`、`LLM_API_KEY`、`LLM_MODEL`。
- **不直连 storage**：存储/检索通过 mcp-tool-service 的 MCP 工具完成。

### 6.3 mcp-tool-service (:8002)
- FastMCP 应用；工具见 §4.2。环境：`STORAGE_URL`、`MCP_TRANSPORT`。

### 6.4 storage-service (:8003)
- `POST /documents` `{url,title,content}` → `{id,...}`
- `GET /documents?q=&limit=` → 列表（按内容/标题/url 模糊匹配）
- `GET /documents/{id}` → 单条
- `GET /stats` → `{count, last_crawled_at}`
- `GET /health`

---

## 7. 数据模型 (Data Model — SQLite)

表 `documents`：
| 字段 | 类型 | 说明 |
|---|---|---|
| id | INTEGER PK AUTOINCREMENT | |
| url | TEXT | 来源 URL |
| title | TEXT | 标题 |
| content | TEXT | 清洗后的正文 |
| content_length | INTEGER | 正文长度 |
| created_at | TEXT (ISO) | 抓取时间 |

数据库文件位于卷 `zhiyue-data:/data/zhiyue.db`，容器重启数据不丢。

---

## 8. 容器化 (Containerization)

- 每服务一个 `Dockerfile`：`FROM python:3.11-slim`，`WORKDIR /app`，装系统依赖（curl），`COPY requirements.txt` 后 `pip install`，复制代码，创建非 root 用户 `mcpuser`（与指导书第六步一致），`ENV PYTHONUNBUFFERED=1`，`CMD` 启动各自服务（uvicorn / mcp）。
- `deploy/docker-compose.yml`：4 服务 + 自定义网络 `zhiyue-net` + 卷 `zhiyue-data`；`env_file: .env`；`depends_on` + healthcheck。
- `deploy/.env.example`：占位的 `LLM_API_KEY` 等（真实 `.env` 不入库，`.gitignore` 排除）。
- `guide-baseline/`：指导书原样单文件 `web_content_mcp.py` + `Dockerfile` + `requirements.txt`，用于复现第六步 `docker build -t mcp-web-scraper .` / `docker run`。

---

## 9. 阿里云部署计划 (Aliyun ACR)

- 仓库：阿里云容器镜像服务（个人版即可），命名空间 `<namespace>`，registry 形如 `registry.cn-hangzhou.aliyuncs.com`。
- 流程（`scripts/push_aliyun.sh`，参数化 registry/namespace/tag）：
  1. `docker login --username=<account> registry.cn-hangzhou.aliyuncs.com`
  2. 对每个镜像：`docker tag zhiyue/<svc>:latest registry.cn-hangzhou.aliyuncs.com/<ns>/<svc>:latest`
  3. `docker push registry.cn-hangzhou.aliyuncs.com/<ns>/<svc>:latest`
- 报告含登录、push、阿里云控制台镜像列表截图。
- **需用户提供**：ACR registry 地址、命名空间、账号；或由用户用 `!` 在会话内执行 push 并截图。

---

## 10. 测试策略 (Testing)

- **单元测试 (pytest)**：
  - mcp-tool-service：`get_web_content`/`extract_links`/`crawl_structured` 对本地 HTML 夹具解析正确（用 `requests-mock` 或本地静态文件，避免外网依赖）。
  - storage-service：CRUD + 搜索。
- **集成测试**：`docker-compose up` 后，对 gateway 发一个端到端 chat 请求，断言：调用了 MCP 工具、文档被存储、返回非空答案。LLM 部分用可注入的 mock planner 以保证 CI 可重复。
- **手动验收**：MCP Inspector 截图、Cline 截图、`docker ps`、Web UI 对话、阿里云镜像列表。

---

## 11. 报告计划 (Report — 按模板 8 节)

`报告/学号+姓名.docx`：
- 一 实验目的 → G1–G6
- 二 实验环境 → Win11、Python 3.13、Docker Desktop、FastAPI、FastMCP、DeepSeek、SQLite
- 三 实验内容 → 业务场景、架构、技术选型
- 四 实验步骤 → 需求分析 → 架构设计 → 四服务实现 → MCP 封装（指导书第二~五步） → 容器化（第六步） → 阿里云推送（第七步）
- 五 结果展示 → Web UI 对话、MCP Inspector、Cline、docker ps、阿里云仓库、测试输出
- 六 结论与未来展望 → 总结 + Nacos/K8s/更多工具
- 七 参考资料 → MCP 规范、FastMCP、FastAPI、阿里云 ACR 文档、BeautifulSoup
- 八 附录 → 全量源码、docker-compose、关键截图

---

## 12. 项目结构 (Repo Layout)

```
微服务架构2/
  services/
    api-gateway/        (app.py, static/, Dockerfile, requirements.txt)
    agent-service/      (app.py, agent.py, mcp_client.py, Dockerfile, requirements.txt)
    mcp-tool-service/   (mcp_server.py, tools.py, Dockerfile, requirements.txt)
    storage-service/    (app.py, db.py, Dockerfile, requirements.txt)
  guide-baseline/       (web_content_mcp.py, Dockerfile, requirements.txt)  # 指导书原样
  deploy/               (docker-compose.yml, .env.example)
  tests/                (unit + integration)
  scripts/              (build_all.sh, push_aliyun.sh)
  docs/                 (本规格、架构图)
  报告/                  (学号+姓名.docx, 截图素材)
```

---

## 13. 待用户提供的输入 (Open inputs)
1. **DeepSeek API Key**（写入 `.env`，不入库）—— 运行/验证 LLM 智能体所需。
2. **阿里云 ACR** registry 地址 / 命名空间 / 账号 —— 或由用户自行 push 并截图。
3. **封面信息**：学号、姓名、学年学期、课程名称、课程编号、课程序号、任课教师。

## 14. 风险与对策 (Risks)
- 外网抓取不稳定 → 测试用本地夹具；演示用稳定站点（example.com / 指定页面）。
- LLM 无网/无 key → 安全网兜底，且保留可注入 mock planner 供测试。
- 阿里云需账号 → 命令全部参数化、文档化，用户一键执行。
- Windows 下 Docker/MCP 路径差异 → compose 统一环境；`mcp dev` 在宿主机执行。
```
