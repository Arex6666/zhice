# 智阅 ZhiYue — 基于 MCP 的智能网页采集分析智能体平台

一个具备爬虫能力、配备 **MCP（Model Context Protocol）** 服务的智能体（AI Agent）微服务系统。
用户用自然语言下达任务，智能体经 **DeepSeek** 大模型规划并通过 MCP 调用爬虫 / 抽取 / 存储 / 检索工具完成任务。

> 微服务架构实践大作业。课程报告见 `报告/`，设计与实现计划见 `docs/superpowers/`。

## 架构（4 个微服务）

```
浏览器 → api-gateway(:8080) → agent-service(:8001, DeepSeek + MCP 客户端)
              → mcp-tool-service(:8002, FastMCP, stdio+SSE) → storage-service(:8003, SQLite)
```

| 服务 | 技术 | 端口 | 职责 |
|---|---|---|---|
| api-gateway | FastAPI + Web UI | 8080 | 唯一入口、聊天界面、转发、/metrics |
| agent-service | FastAPI + openai + mcp | 8001 | 智能体大脑：LLM 工具规划循环、MCP 客户端 |
| mcp-tool-service | FastMCP | 8002 | 5 个 MCP 工具：爬取/抽取/结构化/存储/检索 |
| storage-service | FastAPI + SQLite | 8003 | 文档持久化与检索（记忆库） |

## 快速开始

```bash
# 1) 配置 DeepSeek 密钥
cd deploy
cp .env.example .env        # 编辑 .env 填入 LLM_API_KEY

# 2) 构建并启动
docker compose build
docker compose up -d
docker compose ps           # 4 个服务应为 healthy

# 3) 打开 Web 界面
#    http://localhost:8080
```

## 测试

```bash
# 单元测试（无需联网/密钥）
python -m pytest tests/ -v

# 端到端冒烟测试（需先 up；配置密钥后含完整智能体对话）
export $(grep -v '^#' deploy/.env | grep LLM_ | xargs)
python scripts/smoke_test.py

# 仅验证 MCP 服务（等价于 Inspector：initialize/list_tools/call_tool）
python scripts/mcp_client_test.py
```

## MCP（指导书第三~五步）

```bash
# MCP Inspector（stdio）。注意：Inspector v0.22 需允许浏览器来源
ALLOWED_ORIGINS=http://127.0.0.1:6274 mcp dev guide-baseline/web_content_mcp_stdio.py
# Cline：导入 guide-baseline/cline_mcp_settings.json
```

## 推送阿里云（指导书第七步）

```bash
bash scripts/push_aliyun.sh <registry> <namespace> [tag]
# 例: bash scripts/push_aliyun.sh registry.cn-hangzhou.aliyuncs.com myns latest
```

## 项目结构

```
services/{api-gateway,agent-service,mcp-tool-service,storage-service}/
guide-baseline/   # 《MCP实验指导书》原样基线 + stdio 演示变体 + Cline 配置
deploy/           # docker-compose.yml, .env.example
tests/  scripts/  docs/  报告/
```
