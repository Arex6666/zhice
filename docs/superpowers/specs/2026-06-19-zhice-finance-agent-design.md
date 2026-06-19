# 设计规格说明书：智策 ZhiCe — 可信·可解释·可验收的多智能体金融分析平台

> ZhiCe — a trustworthy / explainable / auditable multi-agent financial analysis platform
> （扩展自「智阅」MCP 智能体平台）。日期：2026-06-19（v2，纳入数据质量/证据链/校准/可信回测/复盘/解释面板/任务模式/可观测性）。
> 一次性整体交付。**不再扩展市场/指标/模型广度，转而深化可信度。**

---

## 1. 概述与定位

在「智阅」MCP 智能体微服务平台上**原地扩展**金融垂直能力：自动采集 A股 / 美股 / 加密货币的行情与新闻，**先经数据质量层判定可信度**，计算技术指标，由**证据链驱动的多智能体投研委员会**（多 LLM 分析师 + XGBoost 弱信号校准器）产出**带证据、置信度、分歧与免责声明的多空研判**；提供 K线仪表盘 + 决策解释面板 + 可信回测，并对历史研判做**自动复盘**评估自身能力。

**诚实定位（贯穿全程）**：只做**分析与研判**，不做"保证准确的涨跌预测"。短周期方向接近随机游走；输出强制附 **"仅供学习研究，不构成投资建议"**；ML 与回测显式标注未来函数/过拟合/不可外推。

### 核心创新与定位 (Conceptual Positioning)
创新点不在"能分析股票"，而在把金融智能体推进到**可信研判范式**——一个**面向高不确定性金融场景的多智能体证据治理框架**。五个支柱：
- **证据治理 Evidence Governance**：对每条研判施加确定性治理规则（无证据不出强结论；数据过期必降置信；证据冲突必暴露分歧；模型无效必弃权；回测不稳不支持高置信；新闻须区分**事实/情绪/推断**）。由独立规则引擎强制执行——见 §7.5。
- **不确定性管理 Uncertainty Management**：系统回答的不是"明天涨不涨"，而是"有哪些支持/反对证据、证据质量如何、依据是否充分、置信度是否合理、是否应输出中性/证据不足"。即 *uncertainty-aware financial reasoning*。
- **弃权感知委员会 Abstention-aware Committee**：数据不可靠 / 证据不足 / 模型无统计优势时**主动弃权**，而非硬答。可演示：故意输入数据不足/无新闻/K线过短的标的，看系统降级或弃权。
- **自审计 Self-auditing**：每次研判落库，到期用真实市场结果**反向审计**自身（命中率、各委员有效性、主席是否过度自信）——见 §7.4。
- **反证感知解释 Counter-evidence-aware Explanation**：解释不仅说"为何如此"，更说"什么证据反对、什么条件会使结论失效、谁持异议、为何最终仍如此判断"——见 §9。

### 目标
- G1 市场无关数据层：A股(akshare/新浪/东财)、美股(yfinance)、加密货币(Binance→CoinGecko)。
- G2 金融能力以 **MCP 工具**暴露（延续加分项）。
- G3 **自动化采集**（ingestion 定时入库 + 复盘回填 + 异常提醒）。
- G4 **证据链投研委员会** + **XGBoost 信号校准器** + 主席结构化汇总。
- G5 仪表盘 + **决策解释面板** + 可信回测；6 种**智能体任务模式**。
- **G6 可信**：数据质量层 + `data_status` 全链路标注。
- **G7 可解释**：每条结论必须可追溯到工具/指标/新闻/回测证据。
- **G8 可验收**：历史研判复盘 + 可观测性面板，答辩可展示"非 demo、有监控、能自评"。

### 非目标
真·tick/Level-2、HFT、自动下单、个性化荐股；分布式时序库（用 SQLite，Postgres 列为未来）；**不再增加更多市场/指标/模型**。

---

## 2. 架构（在现有 4 服务上加法）

```
浏览器  ├─ 聊天台(原 智阅)   ┌────────────────────────────┐
        └─ 金融仪表盘 ───────▶│ api-gateway :8080            │
           (+决策解释面板)    │ /api/finance/* /status      │
                              └───────────┬──────────────────┘
                                          ▼ HTTP
                        ┌────────────────────────────┐
                        │ agent-service :8001          │
                        │ 任务模式路由(6种)             │
                        │ 证据链投研委员会(LLM x4)      │
                        │ + XGBoost 信号校准器 + 主席   │
                        └───────────┬──────────────────┘
                                    ▼ MCP(SSE)
        ┌────────────────────────────┐      ┌──────────────────────┐
        │ mcp-tool-service :8002       │      │ storage-service :8003 │
        │ 网页工具 + 金融工具           │─HTTP▶│ documents/quotes/news │
        │ finance.py(适配器)            │      │ /analysis(含复盘字段) │
        │ data_quality.py(质量层)       │      └──────────────────────┘
        │ indicators/backtest           │                ▲ HTTP
        └────────────────────────────┘                  │
                ┌────────────────────────────┐           │
                │ ingestion-service :8004      │───────────┘
                │ 定时采集 + 复盘回填 + 异常提醒 │
                │ + 可观测性指标               │
                └────────────────────────────┘
```

| 服务 | 端口 | 改动 |
|---|---|---|
| api-gateway | 8080 | ➕ `/api/finance/*`、`/api/finance/status`(可观测性)；➕ 金融仪表盘 + 决策解释面板 |
| agent-service | 8001 | ➕ 任务模式路由、证据链委员会(committee.py)、信号校准器(ml_signal.py)、主席汇总 |
| mcp-tool-service | 8002 | ➕ 金融工具 + finance.py(适配器) + **data_quality.py(质量层)** + indicators/backtest |
| storage-service | 8003 | ➕ quotes/news/analysis(含复盘字段) + watchlist |
| **ingestion-service** | 8004 | **新增**：定时采集 + 复盘回填(算研判后收益) + 异常提醒 + 指标暴露 |

---

## 3. 市场无关数据层 + 数据质量层

### 3.1 适配器 (finance.py)
`MarketAdapter` 基类，统一符号 `MARKET:CODE`（`ASHARE:600519` / `US:AAPL` / `CRYPTO:BTCUSDT`）：`get_quote`、`get_kline`、`get_news`。
| 市场 | 适配器 | 源 | 备注 |
|---|---|---|---|
| A股 | `AshareAdapter` | akshare / 新浪(需 Referer) / 东财(价 f43/100) | ✅ 实测，秒级 |
| 美股 | `UsAdapter` | yfinance | CN 慢/需代理，15min 延迟，超时+缓存 |
| 加密 | `CryptoAdapter` | Binance REST → CoinGecko 兜底 | Binance 在 CN 可能被墙→回退 |

### 3.2 数据质量层 (data_quality.py) — **最重要**
所有行情/K线流经 `assess(quote, market, source) -> DataQualityResult`，附 `data_status`：
- `fresh`：时间戳在新鲜窗内（A股盘中≤数分钟；美股≤15min；crypto≤1min）。
- `delayed`：超出新鲜窗但合理。
- `stale`：明显过期（如非交易时段的旧值）。
- `fallback`：来自备用源（如 CoinGecko 替 Binance）。
- `error`：取数失败/字段缺失。

并处理金融"脏活"：
- **停牌/涨跌停**（A股）：volume=0 或价==涨跌停价 → 标注 `halted`/`limit_up`/`limit_down`。
- **复权**：K线显式 `adjust ∈ {qfq 前复权, hfq 后复权, none}`，默认前复权，结果标注所用口径。
- **时区统一**：所有 ts 归一到带时区 ISO（A股/美股各自交易所时区→UTC 存储，展示按市场本地时区）。
- **交易日历分离**：股票用交易日历（休市跳过）；crypto 7×24 独立逻辑。
- **跨源价差告警**：同标的多源价格偏差超阈值(如 1%) → `data_status` 降级 + 告警计数。
- **涨跌幅一致性**：统一用 `(price-prev_close)/prev_close`，避免各源口径不一致。

委员会拿到的每条数据都带 `data_status`：分析时**知道价格是否可信/延迟/来自备用源**；`stale/error` 数据触发委员弃权或降低置信度。

---

## 4. 金融 MCP 工具 (mcp-tool-service)

异步实现、错误抛出由 MCP 置 isError。返回均含 `data_status`。
| 工具 | 签名 | 说明 |
|---|---|---|
| `get_quote` | `(symbol)->dict` | 报价 + data_status |
| `get_kline` | `(symbol,period,count,adjust)->list` | OHLCV + 复权口径 |
| `get_indicators` | `(symbol,period)->dict` | MA(5/10/20/60)/MACD/RSI/BOLL/量能 |
| `get_stock_news` | `(symbol,limit)->list` | 个股新闻 |
| `compute_signals` | `(symbol)->dict` | 规则技术信号 + 解读 |
| `backtest` | `(symbol,strategy,params)->dict` | **可信回测**（见 §4.1） |
| `market_overview` | `(market)->dict` | 指数/板块概览 |

### 4.1 可信回测 (backtest.py)
双均线等策略，但输出**可信指标包**：累计/年化收益、**基准对比(买入持有)**、最大回撤、夏普比率、胜率、**最大连续亏损**、交易次数、**含手续费+滑点**（可配置 bps）、**样本内/样本外分段**、**参数敏感性**（如 5/20 有效但 6/21、8/30 无效 → 提示过拟合）、**分市场分别回测**。结果固定附 **"历史回测不可直接外推"** 风险标签。指标为纯函数，合成序列可单测。

---

## 5. ingestion-service（采集 + 复盘 + 异常，新增）

- **定时采集**（APScheduler，间隔可配）：A股盘中(9:30–11:30,13:00–15:00)每 5min 行情、新闻每 15min；美股美东盘中每 5min；crypto 7×24 每 5min。经数据质量层后写 storage。
- **复盘回填**：对 `analysis` 中到期(T+1/3/5)的研判，拉当时之后的实际收益回填 `ret_1d/3d/5d` 与 `correct`（见 §7.4）。
- **异常提醒**：watchlist 标的涨跌幅/放量/新闻突增触发告警事件入库。
- **可观测性**：累计采集条数、各源成功率、失败次数、上次采集时间，暴露 `/status`。
- 交易日历/休市判断；失败重试+退避。

---

## 6. 存储扩展 (storage-service, SQLite)

- `quotes(id,symbol,price,change_pct,ts,data_status,source,raw_json)`
- `news(id,symbol,title,url,source,ts,sentiment,summary)`
- `analysis(id,symbol,mode,verdict,confidence,committee_json,price_at_analysis,created_at, ret_1d,ret_3d,ret_5d,correct,reviewed_at)` ← 含**复盘字段**
- `alerts(id,symbol,type,detail,ts)`、`watchlist(symbol,market)`
- 接口：quotes/news/analysis/alerts/watchlist 的增查；`GET /analysis/review`（复盘统计）。

---

## 7. 多智能体投研委员会 (agent-service)

### 7.1 证据链委员（Evidence-based）
四位 LLM 委员（技术面/资金面/新闻情绪面/宏观面），**强制结构化输出**（JSON schema 校验）：
```json
{ "verdict":"偏多/偏空/中性", "confidence":0.62,
  "reasons":["..."],
  "evidence":[{"type":"indicator|news_fact|news_sentiment|news_inference|backtest|market",
               "source":"get_indicators","value":"RSI=72.4","interpretation":"短期偏超买"}],
  "counter_evidence":["RSI 接近超买，存在回调风险"],
  "risks":["..."], "abstain": false, "abstain_reason": null }
```
不允许只说"我认为偏多"——**必须列出依据的工具/指标/新闻/回测**，且每位委员需给出**反对自身结论的证据(counter_evidence)**。**新闻证据必须区分 `news_fact`(事实) / `news_sentiment`(情绪) / `news_inference`(推断)**，避免把情绪/传闻当事实。数据 `stale/error` 或证据不足 → `abstain=true` 并填 `abstain_reason`。

### 7.2 XGBoost 信号校准器（不是预测器）
`ml_signal.py`：回答"在相似技术形态/量价/波动环境下，历史 T+1 上涨概率是否高于基准"。
- 特征仅用截至 T 日数据（杜绝未来函数）；标签 T+1 涨跌。
- **walk-forward 滚动验证**；与**随机基准**、**买入持有**对比。
- **概率校准**（sklearn `CalibratedClassifierCV`，Platt/isotonic）。
- **弃权机制**：样本不足 / AUC≈0.5 / 特征异常 → 不输出方向（abstain）。
- **可解释**：输出 `feature_importance`（XGBoost 内置，必备）+ 可选 SHAP；说明"模型主要看了什么"。
- 作为委员会**一票**，明示"近随机、弱信号、易过拟合"。模型缺失时弃权。

### 7.3 主席汇总（结构化裁决，非简单投票）
主席 LLM 接收**经治理引擎(§7.5)校验后的委员意见**，输出：**多数意见 / 少数意见 / 分歧来源 / 最关键证据 / 反对证据(counter-evidence) / 结论失效条件（哪些条件会使结论反转）/ 异议委员 / 最大风险 / 最终研判 / 置信度（并解释为何不是 0.9~1.0）** + **免责声明**。委员弃权不计票并记录原因；置信度受治理引擎上限约束（§7.5）。

### 7.4 自审计机制 (Self-auditing Financial Agent)
不是"自动变准"，而是**系统持续记录自身判断并用真实市场结果反向审计**。研判落库时记 `price_at_analysis`；ingestion 到期回填 `ret_1d/3d/5d` 与 `correct`（方向是否兑现）。`GET /analysis/review` 统计：整体命中率、**各委员历史有效性**（谁常对/常错）、**主席是否过度自信**（高置信但常错 → 校准告警）、分市场表现。仪表盘"复盘模式"可视化——**委员会不仅分析，还被历史结果反向审计**。区别于只展示当下分析、不敢展示历史对错的普通 AI 金融系统。

---

### 7.5 证据治理引擎 (governance.py) — 核心创新
**确定性**规则层（非 LLM），在委员发言之后、主席汇总之前运行，对每条研判强制施加治理规则，并产出 `governance_report`（哪些规则触发、为何降级）供审计：
| 规则 | 触发 | 动作 |
|---|---|---|
| R1 无证据不出强结论 | 委员给 偏多/偏空 但 evidence 为空/过弱 | 降为 中性 或令其弃权 |
| R2 数据过期必降置信 | 输入 `data_status ∈ {stale,error}` | 置信度上限 ≤0.4 或弃权 |
| R3 证据冲突必暴露分歧 | 委员分歧超阈值 | 标记"高分歧"，封顶主席置信度 |
| R4 模型无效必弃权 | XGBoost AUC≈0.5 / 样本不足 | 该票剔除，不参与投票 |
| R5 回测不稳不支持高置信 | 参数敏感性不稳定 | 封顶置信度 |
| R6 新闻须分层 | 强结论仅依赖 news_sentiment/news_inference（无 fact/指标） | 降级或要求补证 |

**置信度天花板**：最终置信度 = min(主席提议, 治理上限)，治理上限由 数据质量 × 委员一致度 × 证据强度 推导，使"高置信"必须有据。治理引擎是确定性的、可单测的——这正是"证据治理框架"落到代码的体现。

## 8. 智能体任务模式 (agent-service 路由)

体现 MCP + Agent 平台差异化（非普通金融网站）：
1. **单股快速体检**：代码→行情+指标+新闻+风险（不跑全委员会，省成本）。
2. **深度研判**：完整证据链委员会 + 校准器 + 主席。
3. **组合观察**：对 watchlist 多只做简短扫描（并发）。
4. **异常提醒**：读取 alerts，汇总解读。
5. **复盘模式**：展示历史研判兑现情况与委员有效性。
6. **教学模式**：解释 MACD/RSI/回测/夏普等含义（面向学习）。

`POST /api/finance/analyze {symbol, mode}` 路由到对应模式。

---

## 9. 金融仪表盘 + 决策解释面板 (api-gateway/static/finance.html)

- 原生 HTML + ECharts(本地 vendored，离线)，延续 青瓷 暗色风。
- K线(蜡烛+量)+MA/BOLL 叠加 + MACD/RSI 副图；新闻流；置信度环；回测卡片(含基准/夏普/敏感性)。
- **反证驱动决策解释面板 (Counter-evidence-aware)**：主席结论 + **主要支持证据** / **主要反对证据(counter-evidence)** + **结论失效条件**（哪些条件会使判断反转）+ **异议委员** + **治理记录**（哪些治理规则触发、为何置信度被封顶）+ **最终判断（带 nuance，如"短线有动能但置信度不高，适合观察")** + 数据 `data_status` 徽标 + 免责声明横幅。不做"宣传式总结"，而像真实投研：先讲清反面与失效条件。
- 复盘模式视图：历史研判命中率、各委员有效性图。

---

## 10. 可观测性 (Observability)

- 各服务统一**结构化日志**（JSON：service/level/event/latency_ms）。
- 指标：采集失败次数、**各数据源成功率**、LLM 调用耗时、**委员会总耗时**、缓存命中率、每日采集条数、异常计数。
- `GET /api/finance/status`（错误/运行面板，网关聚合各服务 `/status`），仪表盘有"系统状态"页。答辩可展示运行监控。

---

## 11. 合规与诚实
全站显著免责声明；研判/回测固定横幅 "仅供学习研究，不构成投资建议"；禁"保证/必涨/稳赚"；委员会必含分歧/风险；ML/回测标注未来函数/过拟合/不可外推；尊重数据源 ToS 与限频。

---

## 12. 测试策略
- 单元（不联网）：指标在合成 OHLCV 确定性验证；可信回测各指标（夏普/回撤/连亏/手续费）合成验证；**data_quality 各状态判定**（fresh/stale/halted/limit/跨源价差）；适配器解析夹具；XGBoost 训练/校准/弃权管道在合成可分数据上验证；committee 用 fake LLM 验证证据链 schema 与主席结构；复盘收益回填计算。
- 集成：ingestion 写库 + 复盘回填；agent 深度研判经 MCP 取数产出证据链研判；冒烟 `scripts/smoke_finance.py`。
- 产物：仪表盘/决策解释/复盘/状态页截图、docker ps、阿里云镜像。

---

## 13. 技术新增
akshare、yfinance、pandas、numpy、APScheduler、xgboost、scikit-learn(校准)、(可选)shap、pytz/zoneinfo(时区)、requests/httpx(crypto)；前端 ECharts(本地)。新增 ingestion-service 镜像；compose 增该服务 + 健康检查 + restart。

---

## 14. 仓库结构（新增）
```
services/mcp-tool-service/  ➕ finance.py data_quality.py indicators.py backtest.py
services/agent-service/     ➕ committee.py governance.py ml_signal.py review.py modes.py finance_agent.py
services/ingestion-service/ ★ app.py scheduler.py reviewer.py alerts.py Dockerfile requirements.txt
services/api-gateway/       ➕ static/finance.html static/vendor/echarts.min.js
services/storage-service/   ➕ db.py(扩表+复盘+alerts+watchlist)
scripts/                    ➕ train_signal.py smoke_finance.py gen_finance_diagram.py
tests/                      ➕ test_indicators.py test_backtest.py test_data_quality.py
                             test_finance_adapter.py test_committee.py test_governance.py test_ml_signal.py test_review.py
models/                     XGBoost 模型 + 校准器产物
```

---

## 15. 风险与对策
- 预测不可靠（最大）→ 诚实定位"分析+弱信号校准器"，全程免责，回测/ML 标注偏差。
- 美股/crypto 在 CN 受限 → 多源+回退(CoinGecko)+超时+缓存+`data_status` 显式提示。
- 数据源不稳/限频/改接口 → 数据质量层 + 缓存 + 重试 + 回退 + 优雅降级。
- 数据脏活（复权/停牌/涨跌停/时区/口径）→ data_quality.py 集中处理（本设计重点）。
- 未来函数/过拟合 → 时间切分 + walk-forward + 样本外 + 参数敏感性 + 显式声明。
- LLM 成本（委员会多次调用）→ 快速体检模式省调用、研判缓存、并发降时延。
- 资源（多容器+ML）→ 训练离线、推理轻量、compose 健康检查。

---

## 16. 验收
- 三市场可取行情+K线+新闻（美股/crypto 允许降级提示），每条带 `data_status`。
- 金融 MCP 工具经 Inspector/客户端可调用。
- 深度研判产出**证据链**五方意见 + 主席结构化裁决 + 免责声明。
- **治理引擎可演示**：故意输入数据不足/无新闻/K线过短的标的，系统按 R1–R6 **降级置信度或弃权**，并在 `governance_report` 说明触发了哪条规则。
- **反证可见**：解释面板同时给出支持证据、反对证据与"结论失效条件"，置信度封顶有据可查。
- XGBoost 以校准概率出"一票"，AUC≈0.5/样本不足时**弃权**，有 feature_importance。
- 可信回测含基准/夏普/连亏/手续费/参数敏感性 + 不可外推标签。
- **自审计**：历史研判到期回填真实收益，可统计命中率、各委员有效性、主席过度自信。
- 仪表盘含反证驱动解释面板与系统状态页。
- 单元/集成/冒烟通过；全栈 docker compose healthy。
