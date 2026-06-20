# 智策 ZhiCe — 可信·可解释的多智能体金融分析平台

一个具备数据爬取能力、配备 **MCP（Model Context Protocol）** 服务的金融分析智能体微服务系统。
自动采集 A股 / 美股 / 加密货币的行情与新闻，由 **DeepSeek** 大模型组成「投研委员会」并经
**证据治理引擎** 与 **XGBoost 波动信号** 给出带置信度、可解释、可复盘的研判。

> 微服务架构实践大作业。课程报告见 `报告/`，设计与实现计划见 `docs/superpowers/`。
> 《MCP实验指导书》原样基线保留于 `guide-baseline/`。

## 架构（5 个微服务）

```
浏览器 → api-gateway(:8080, 金融仪表盘) → agent-service(:8001, DeepSeek 委员会+治理+ML, MCP 客户端)
                                              → mcp-tool-service(:8002, FastMCP, stdio+SSE)
                                              → storage-service(:8003, SQLite)
            ingestion-service(:8004, APScheduler 周期采集/复盘/告警) → storage-service
```

| 服务 | 技术 | 端口 | 职责 |
|---|---|---|---|
| api-gateway | FastAPI + ECharts 仪表盘 | 8080 | 唯一入口、金融仪表盘、转发、/metrics |
| agent-service | FastAPI + openai + mcp + xgboost | 8001 | 投研委员会、证据治理、ML 风险信号、MCP 客户端 |
| mcp-tool-service | FastMCP | 8002 | 7 个金融 MCP 工具：报价/K线/指标/新闻/信号/回测/大盘 |
| storage-service | FastAPI + SQLite | 8003 | 行情/新闻/研判/复盘/告警/自选股持久化 |
| ingestion-service | FastAPI + APScheduler | 8004 | 周期性行情采集 + 研判复盘 + 异动告警 |

## 快速开始

```bash
# 1) 配置 DeepSeek 密钥
cd deploy
cp .env.example .env        # 编辑 .env 填入 LLM_API_KEY

# 2) 构建并启动
docker compose build
docker compose up -d
docker compose ps           # 5 个服务应为 healthy

# 3) 打开金融仪表盘
#    http://localhost:8080
```

## 测试

```bash
# 单元测试（无需联网/密钥）
python -m pytest tests/ -v

# 端到端金融冒烟测试（需先 up；含 MCP 工具与委员会研判）
export $(grep -v '^#' deploy/.env | grep LLM_ | xargs)
python scripts/smoke_finance.py
```

## MCP 服务（指导书第三~五步）

7 个金融工具通过 FastMCP 暴露，双传输：`stdio`（供 Inspector/Cline）与 `sse`（供跨容器调用）。

```bash
# MCP Inspector（stdio）。Inspector v0.22 需允许浏览器来源
cd services/mcp-tool-service
ALLOWED_ORIGINS=http://127.0.0.1:6274 mcp dev mcp_server.py
# 容器内 SSE 端点：http://localhost:8002/sse

# 《MCP实验指导书》原样基线（web 爬虫）单独保留备查
ALLOWED_ORIGINS=http://127.0.0.1:6274 mcp dev guide-baseline/web_content_mcp_stdio.py
```

## 推送阿里云（指导书第七步）

```bash
bash scripts/push_aliyun.sh <registry> <namespace> [tag]
# 例: bash scripts/push_aliyun.sh registry.cn-hangzhou.aliyuncs.com myns latest
```

## 项目结构

```
services/{api-gateway,agent-service,mcp-tool-service,storage-service,ingestion-service}/
guide-baseline/   # 《MCP实验指导书》原样基线 + stdio 演示变体 + Cline 配置（备查）
deploy/           # docker-compose.yml, .env.example
tests/  scripts/  docs/  报告/
```
