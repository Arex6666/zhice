# 设计规格说明书：智策 ZhiCe — 多智能体金融分析平台

> ZhiCe — a multi-agent financial analysis platform (extends the 智阅 MCP agent platform).
> 日期：2026-06-19 ｜ 一次性整体交付（A股 + 美股 + 加密货币 + 投研委员会 + ML 信号）

---

## 1. 概述与定位

在现有「智阅」MCP 智能体微服务平台上**原地扩展**出金融垂直能力：自动化采集 A股 / 美股 / 加密货币的行情与新闻，计算技术指标，由**多智能体投研委员会**（多个 LLM 分析师 + 一个轻量 XGBoost 信号）产出**带置信度与免责声明的多空研判**，并提供 K线仪表盘与策略回测。

**诚实定位（贯穿全程）**：本平台做的是**分析与研判**，不是"保证准确的涨跌预测"。短周期价格方向接近随机游走；所有输出强制附 **"仅供学习研究，不构成投资建议"**，回测只报历史表现并标注未来函数/过拟合/幸存者偏差风险。

### 目标
- G1：市场无关的数据层，同时支持 A股(akshare/新浪/东财)、美股(yfinance)、加密货币(Binance/CoinGecko)。
- G2：金融能力以 **MCP 工具**暴露（延续加分项），可被智能体与 Inspector 调用。
- G3：**自动化采集**（ingestion-service 定时入库，含交易日历/休市判断）。
- G4：**多智能体投研委员会**：技术面/资金面/新闻情绪面/宏观面四位 LLM 分析师 + XGBoost 信号 → 主席智能体汇总。
- G5：**K线仪表盘**（ECharts 本地化、离线可用）+ 新闻流 + 研判面板 + 回测。
- G6：可运行、可验证（单元 + 集成 + 冒烟），全部容器化、可推阿里云，延续现有架构与报告。

### 非目标
- 真·tick/Level-2 实时（免费拿不到）；高频交易；自动下单；个性化荐股。
- 生产级分布式时序库（MVP 用 SQLite；Postgres/TimescaleDB 列为未来）。

---

## 2. 架构（在现有 4 服务上加法）

```
浏览器
 ├─ 聊天台 (原 智阅)            ┌────────────────────────────┐
 └─ 金融仪表盘 finance.html ──▶ │ api-gateway :8080            │
                                │  /api/chat /api/finance/*    │
                                └───────────┬──────────────────┘
                                            │ HTTP
                                            ▼
                                ┌────────────────────────────┐
                                │ agent-service :8001          │
                                │  分析师 + 投研委员会(LLM x4) │
                                │  + XGBoost 信号 + 主席汇总    │
                                │  (MCP 客户端)                │
                                └───────────┬──────────────────┘
                                            │ MCP (SSE)
                                            ▼
                ┌────────────────────────────┐      ┌──────────────────────┐
                │ mcp-tool-service :8002       │      │ storage-service :8003 │
                │  通用网页工具 + 金融工具      │─HTTP▶│ documents/quotes/news │
                │  finance.py 市场无关适配器    │      │ /analysis (SQLite)    │
                │  Ashare/US/Crypto Adapter    │      └──────────────────────┘
                └────────────────────────────┘                ▲
                                                                │ HTTP 写入
                                ┌────────────────────────────┐ │
                                │ ingestion-service            │─┘
                                │  APScheduler 定时拉行情+新闻  │
                                └────────────────────────────┘
```

### 服务清单（新增/改动）
| 服务 | 端口 | 改动 |
|---|---|---|
| api-gateway | 8080 | ➕ `/api/finance/*` 转发；➕ 金融仪表盘静态页；保留聊天台 |
| agent-service | 8001 | ➕ 分析师 + 投研委员会(committee.py) + XGBoost 信号(ml_signal.py) + 主席汇总 |
| mcp-tool-service | 8002 | ➕ 金融 MCP 工具 + `finance.py`（市场无关适配器） |
| storage-service | 8003 | ➕ `quotes`/`news`/`analysis` 表与接口 |
| **ingestion-service** | 8004 | **新增**：APScheduler 定时采集行情+新闻入库 |

---

## 3. 市场无关数据层 (finance.py)

抽象基类 `MarketAdapter`，统一符号格式 `MARKET:CODE`（如 `ASHARE:600519`、`US:AAPL`、`CRYPTO:BTCUSDT`）：
- `get_quote(symbol) -> dict`：{name, price, change_pct, ts}
- `get_kline(symbol, period, count) -> list[OHLCV]`
- `get_news(symbol, limit) -> list[{title, url, ts, source}]`

适配器实现：
| 市场 | 适配器 | 数据源 | 已实测/备注 |
|---|---|---|---|
| A股 | `AshareAdapter` | akshare；新浪 `hq.sinajs.cn`(需 Referer)、东财 `push2`(字段需换算 价 f43/100) | ✅ 实测可用，秒级 |
| 美股 | `UsAdapter` | yfinance(Yahoo) | 国内可能慢/需代理；15 分钟延迟；超时+缓存兜底 |
| 加密货币 | `CryptoAdapter` | Binance 公共 REST `api.binance.com`，回退 CoinGecko | Binance 在 CN 可能被墙→CoinGecko 兜底；真·实时无需券商 |

**降级原则**：任一源失败 → 重试 → 回退源 → 明确报错（不静默造假）。所有抓取带 UA、超时、缓存（短 TTL）。

---

## 4. 金融 MCP 工具 (mcp-tool-service)

延续 FastMCP，异步实现（不阻塞事件循环），错误抛出由 MCP 置 isError：
| 工具 | 签名 | 说明 |
|---|---|---|
| `get_quote` | `(symbol) -> dict` | 实时/近实时报价 |
| `get_kline` | `(symbol, period='daily', count=120) -> list` | OHLCV 历史 |
| `get_indicators` | `(symbol, period='daily') -> dict` | MA(5/10/20/60)、MACD、RSI、BOLL、量能 |
| `get_stock_news` | `(symbol, limit=8) -> list` | 个股相关新闻 |
| `compute_signals` | `(symbol) -> dict` | 规则技术信号（金叉/死叉、超买超卖、放量等）+ 简短解读 |
| `backtest_ma` | `(symbol, short=5, long=20) -> dict` | 双均线交叉回测：累计收益、最大回撤、胜率、交易次数（附未来函数/过拟合声明） |
| `market_overview` | `(market) -> dict` | 指数/板块概览 |

指标与回测纯函数放 `indicators.py`/`backtest.py`（pandas/numpy，可脱网单测）。

---

## 5. ingestion-service（自动化采集，新增）

- APScheduler（默认间隔可由环境变量覆盖）：A股交易时段(9:30–11:30,13:00–15:00)每 **5 分钟**拉关注列表行情；新闻每 **15 分钟**；美股(美东盘中)同 5 分钟；加密货币 7×24 每 **5 分钟**。
- 交易日历/休市判断（akshare 交易日历；周末/节假日跳过）。
- 写入 storage 的 `quotes`/`news`；失败重试 + 退避；记录采集日志。
- 关注列表(watchlist)可配置（环境变量/配置文件）。
- 暴露 `/health`、`/status`(上次采集时间、计数)。

---

## 6. 存储扩展 (storage-service, SQLite)

新增表：
- `quotes(id, symbol, price, change_pct, ts, raw_json)`
- `news(id, symbol, title, url, source, ts, sentiment, summary)`
- `analysis(id, symbol, verdict, confidence, committee_json, created_at)`
新增接口：`POST/GET /quotes`、`POST/GET /news`、`POST/GET /analysis`、`GET /watchlist`。沿用卷持久化。

---

## 7. 多智能体投研委员会 (agent-service)

`committee.py`：对给定 symbol 编排五位"委员"，并发执行，再由主席汇总：
| 委员 | 视角 | 输入 | 输出 |
|---|---|---|---|
| 技术面分析师 | 指标/形态 | get_indicators + compute_signals + backtest | 多空/置信度/理由 |
| 资金面分析师 | 量价/资金流 | kline 量能、（A股）资金流向 | 多空/置信度/理由 |
| 新闻情绪分析师 | 利好/利空 | get_stock_news → LLM 情绪 | 多空/置信度/理由 |
| 宏观面分析师 | 大盘/板块/宏观 | market_overview + 宏观新闻 | 多空/置信度/理由 |
| **XGBoost 信号** | 历史特征统计 | 指标特征向量 | 涨/跌概率(一票) + 回测指标 |
| **主席（汇总）** | 综合裁决 | 上述五票 | 委员会研判 + 置信度 + 分歧点 + **免责声明** |

- 实现：四位 LLM 委员 = DeepSeek 不同 system prompt，**并发调用**（asyncio.gather）；主席再一次 LLM 汇总。按需触发（用户对某 symbol 请求研判时），不持续全市场跑（控成本）。
- 结构化输出（JSON schema：verdict∈{偏多,偏空,中性}, confidence∈0..1, reasons[], risks[]）。

### XGBoost 信号 (ml_signal.py)
- 特征：滞后收益、MA 偏离、RSI、MACD、波动率、量比等（全部用**截至 T 日**数据，杜绝未来函数）。
- 标签：T+1 日涨/跌（二分类）。训练/测试按时间切分（非随机），报告**样本外**准确率/AUC + 简单回测收益/回撤。
- 诚实呈现：明确标注"近随机、仅作委员会一票、易过拟合"；模型缺失/数据不足时该票弃权。
- 训练脚本 `scripts/train_signal.py`，模型存 `models/`（首次可用合成/历史数据训练）。

---

## 8. 金融仪表盘 (api-gateway/static/finance.html)

- 原生 HTML + ECharts（**本地 vendored**，离线可用），延续 青瓷 暗色风。
- 组件：市场/代码搜索；K线图(蜡烛+成交量)+MA/BOLL 叠加+MACD/RSI 副图；个股新闻流；**投研委员会研判面板**（五票 + 主席结论 + 置信度环 + 免责声明横幅）；回测结果卡片。
- 网关 `/api/finance/quote|kline|indicators|news|analyze|backtest` 转发到 agent/mcp/storage。

---

## 9. 合规与诚实

- 全站显著免责声明；研判/回测页固定横幅 "仅供学习研究，不构成投资建议"。
- 不出现"保证/必涨/稳赚"等措辞；委员会输出含"分歧点/风险"。
- 尊重数据源 ToS、限频；不在投资决策场景误导。

---

## 10. 测试策略

- 单元（不联网）：indicators 在合成 OHLCV 上确定性验证；backtest 在合成序列验证；适配器解析用本地夹具；XGBoost 在合成可分数据上验证训练/预测管道；committee 用 fake LLM 验证编排与汇总。
- 集成：ingestion 写库；agent 对某 symbol 产出研判（committee 经 MCP 取数据）；冒烟脚本 `scripts/smoke_finance.py`。
- 实测产物：仪表盘截图、委员会研判截图、回测截图、docker ps、阿里云镜像。

---

## 11. 技术新增

akshare、yfinance、pandas、numpy、APScheduler、xgboost、scikit-learn、（crypto）requests/httpx 直连 Binance/CoinGecko；前端 ECharts(本地)。镜像新增 ingestion-service；compose 增该服务 + 健康检查 + restart。

---

## 12. 仓库结构（新增）

```
services/
  mcp-tool-service/   ➕ finance.py indicators.py backtest.py
  agent-service/      ➕ committee.py ml_signal.py finance_agent.py
  ingestion-service/  ★新增 app.py scheduler.py Dockerfile requirements.txt
  api-gateway/        ➕ static/finance.html static/vendor/echarts.min.js
  storage-service/    ➕ db.py(扩表)
scripts/              ➕ train_signal.py smoke_finance.py gen_finance_diagram.py
tests/                ➕ test_indicators.py test_backtest.py test_finance_adapter.py
                       test_committee.py test_ml_signal.py
models/               XGBoost 模型产物
```

---

## 13. 风险与对策

- **预测不可靠**（最大）→ 诚实定位为"分析/研判+一票ML"，全程免责声明，回测标注偏差。
- **美股/crypto 在 CN 网络受限**（Yahoo/Binance 慢或墙）→ 多源+回退(CoinGecko)+超时+缓存；仪表盘对失败市场显式提示。
- **数据源不稳/限频/改接口**（akshare 上游变动）→ 缓存、重试、回退、优雅降级。
- **数据质量**（复权/停牌/涨跌停/交易日历/时区/代码格式）→ 适配器内统一规整。
- **未来函数/过拟合**（ML 与回测）→ 时间切分、样本外评估、特征只用 T 日及以前、显式声明。
- **LLM 成本**（委员会 5+ 次调用）→ 按需触发、缓存研判、并发执行降时延。
- **资源**（多容器+ML）→ 训练离线、推理轻量；compose 健康检查。

---

## 14. 验收

- A股/美股/crypto 各能取到行情+K线+新闻（美股/crypto 允许降级提示）。
- 金融 MCP 工具经 Inspector/客户端可调用。
- 仪表盘展示 K线+指标+新闻+委员会研判+回测。
- 投研委员会五票 + 主席结论 + 免责声明完整产出。
- 单元/集成/冒烟测试通过；全栈 docker compose healthy。
