# 智策 ZhiCe — 可信·可解释·诚实 的多因子量化选股与多智能体研判平台

面向 **A 股（并扩展港股）** 的量化研究微服务系统：以 **MCP（Model Context Protocol）** 把行情/因子/组合/回测能力工具化，由 **DeepSeek** 多智能体「投研委员会」+ **证据治理引擎** + **机器学习信号** 给出带置信度、可解释、可复盘的研判，并以 **横截面多因子** 做持续调仓的纸面量化模拟。

> 核心不是"预测涨跌赚钱"，而是 **诚实**：绝不编造数据、绝不用今天快照回填历史、小样本绝不夸大显著、全程防未来函数。**仅供学习研究，不构成投资建议、不实盘。**

> 微服务架构实践大作业。课程报告见 `报告/`（含 `实验报告.docx` 与模型准确率可视化 `paper_trade_report.html`）；设计规格见 `docs/superpowers/specs/`；《MCP 实验指导书》原样基线保留于 `guide-baseline/`。

---

## ✨ 主要功能

- **盯盘墙**：A 股 46 + 港股 45 精选（港股按 科技/金融/消费/医药/能源蓝筹 5 子板块）+ 7 指数（含恒生指数），12s 自动刷新、行情延迟据真实时间戳如实标注。
- **GSAP 动效终端**：开机序列、全局行情跑马灯（悬停暂停/点击进研判/全视图常驻）、盯盘墙**原位更新**（数字滚动+变价辉光，12s 刷新零重建零闪烁）、涨跌分布动画条、视图转场、模拟回放 GSAP 时间轴驱动（即时变速/进度拖拽）；`prefers-reduced-motion` 全局降级（无障碍）。
- **个股研判**：技术/基本面/情绪/因子 4 位分析师 + ML 信号票 → **治理引擎** → 主席汇总；deep 模式支持 **agentic tool-use**（LLM 自主调用 MCP 工具，带白名单/超时/轮次护栏）。
- **行情图谱**：盘中 **分时图**（价/均价 VWAP/昨收基准/量能）与 **日/周/月 K 线** 可切换；多市场多源容错（港股 K 线腾讯、A 股分时东财等）。
- **因子体检**：zoo **16 个价量因子**，在 **全中证 300** 上以 Rank-IC / Newey-West HAC-t 评估显著性，多重检验（BH-FDR / Harvey t≥3 / Deflated Sharpe）校正，**据实测 IC 符号诚实解读**。
- **AI 量化模拟交易**：横截面反转多因子（超跌买入）top-K 等权、周频调仓的 **持续纸面回放**——净值曲线动画生长、交易流水滚动、持仓实时轮动、统计随进度更新；可调 持仓数/调仓频率/本金。
- **诚实弃权（4 类）**：`data_missing` / `model_load_failed` / `insufficient_history` / `statistical_abstain`，全链路透传。
- **防未来函数**：PIT（Point-In-Time）时点数据 + `asof` 防前视 + **无未来函数不变量测试**。

---

## 架构（6 个微服务）

```
浏览器（ECharts 仪表盘：盯盘墙 / 研判 / 分时·K线 / 因子体检 / AI模拟交易）
   │
   ▼
api-gateway(:8080) ──▶ agent-service(:8001, 委员会+治理+ML+agentic, MCP 客户端)
   │                        │  MCP-SSE
   │                        ▼
   │                 mcp-tool-service(:8002, FastMCP：41 个纯函数工具)
   ▼
storage-service(:8003, SQLite + PIT 时点表)   ingestion-service(:8004, APScheduler 采集/复盘/告警)
                                              offline-runner(离线批：因子评估 / 截面模型训练)
```

| 服务 | 技术 | 端口 | 职责 |
|---|---|---|---|
| api-gateway | FastAPI + ECharts + GSAP | 8080 | 唯一入口、前端仪表盘（动效引擎 GSAP）、反代、/metrics |
| agent-service | FastAPI + openai + mcp + xgboost | 8001 | 投研委员会、证据治理、ML 信号、agentic、MCP 客户端 |
| mcp-tool-service | FastMCP（stdio + SSE） | 8002 | **41 个** 金融/因子/组合/回测/模拟 MCP 工具（纯函数） |
| storage-service | FastAPI + SQLite | 8003 | 行情/新闻/研判/复盘/告警 + **PIT 时点表** 持久化 |
| ingestion-service | FastAPI + APScheduler | 8004 | 周期采集 + 研判复盘 + 异动告警 + PIT 快照 |
| offline-runner | APScheduler | — | 离线批：周频因子评估 / 月频截面模型训练 |

---

## 快速开始

```bash
# 1) 配置 DeepSeek 密钥
cd deploy
cp .env.example .env          # 编辑 .env 填入 LLM_API_KEY

# 2) 构建并启动
docker compose build
docker compose up -d
docker compose ps             # 5 个 healthy + offline-runner Up

# 3) 打开仪表盘
#    http://localhost:8080/finance
```

前端速览：盯盘墙点个股进研判；研判页顶部切 **分时 / 日 / 周 / 月 K**、切 **因子体检**；盯盘墙右上角 **🤖 AI 量化模拟交易** 看持续调仓回放。

### 从阿里云 ACR 直接拉取运行（免构建、免源码）

镜像已推送到**公开**镜像仓库，拉取无需登录，任何装了 Docker 的机器都能一键起全栈：

```bash
cd deploy
# 可选：填入 DeepSeek 密钥（不填则委员会 LLM 研判降级弃权，盯盘墙/因子/K线/AI模拟等照常可用）
export LLM_API_KEY=sk-xxxx

docker compose -f docker-compose.acr.yml pull
docker compose -f docker-compose.acr.yml up -d
# 打开 http://localhost:8080/finance
```

镜像地址（单仓库、按 tag 区分服务）：
`crpi-zjwfywe3f3bt7ie4.cn-hangzhou.personal.cr.aliyuncs.com/arex_666/zhice_agent:<服务名>`
（服务名 ∈ api-gateway / agent-service / mcp-tool-service / storage-service / ingestion-service / offline-runner）

---

## MCP 服务（41 个工具）

FastMCP 双传输：`stdio`（供 Inspector / Cline）与 `sse`（供 agent-service 跨容器调用）。工具按域分：

- **行情/图谱**：`get_quote` `get_quotes_batch` `get_kline` `get_intraday` `get_indicators` `get_stock_news` `market_overview` `get_market_context`
- **信号/波动/异动**：`compute_signals` `get_volatility` `detect_anomalies` `get_seasonality` `get_qvix_timing` `get_regime_overlay`
- **多因子引擎**：`list_factor_universe` `compute_factor_series` `compute_factors_last` `preprocess_cross_section` `combine_factors` `evaluate_factor` `factor_report` `ic_self_audit` `factor_family_gate` `deflated_sharpe` `altfactor` `industry_dummies`
- **组合/风险**：`build_portfolio` `risk_attribution` `efficient_frontier` `shrink_cov_report` `backtest` **`simulate_trading`**（AI 量化模拟）
- **PIT 时点数据**：`get_universe` `asof_value` `get_panel` `read_factor_eval` `read_portfolio` `data_coverage_report` `pit_data_health` `list_factor_meta` `data_source_metrics`

```bash
# MCP Inspector（stdio）；Inspector 需允许浏览器来源
cd services/mcp-tool-service
ALLOWED_ORIGINS=http://127.0.0.1:6274 mcp dev mcp_server.py
# 容器内 SSE 端点：http://localhost:8002/sse
```

---

## 因子引擎与诚实评估

- **因子库 zoo（16 个 history-native 价量因子）**：动量（Mom_12_1/Mom_6_1）、反转（Rev_1/Rev_5/Rev_21）、低波（TotalVol/Vol_60/DownVol/HiLoRange）、彩票（MaxRet）、趋势（Hi52/MA_Trend/RangePos）、流动性（Amihud）、量价（VolRatio/PVCorr）。
- **评估**：Rank-IC / ICIR / Newey-West HAC-t，purged + embargo 交叉验证防泄漏，BH-FDR / Harvey t≥3 / Deflated Sharpe 多重检验校正。
- **实测结论（全 CSI 300）**：Rev_5 Rank-IC **+0.063（t=3.81）** 显著、动量族弃权 —— 独立复现"**A 股是反转市**"的学术共识。
- **模型准确率（诚实）**：单股日线方向 ≈ **49.5%（随机）**；ML 模型**刻意预测"大波动日"而非涨跌方向**（波动具聚集性、可学习），样本不足时**弃权**而非硬编。详见 `报告/实验报告.docx` 与 `报告/paper_trade_report.html`。

---

## 测试

```bash
# 单元测试（无需联网/密钥）—— 358 个，含"无未来函数不变量"等诚实性测试
python -m pytest tests/ -q

# 端到端金融冒烟（需先 up；含 MCP 工具与委员会研判）
export $(grep -v '^#' deploy/.env | grep LLM_ | xargs)
python scripts/smoke_finance.py
```

---

## 推送阿里云 ACR（指导书第七步）

```bash
# 先在真终端登录（交互输密码）
docker login --username=<阿里云账号全名> <registry域名>

# 单仓库、按 tag 区分 6 个服务（个人版只建了一个仓库时用这个）
bash scripts/push_acr.sh [ACR仓库全路径]

# 或：一服务一仓库
bash scripts/push_aliyun.sh <registry> <namespace> [tag]
```

---

## 项目结构

```
services/
  api-gateway/       (:8080) 前端仪表盘 static/{finance.html, css/, js/} + 反代
  agent-service/     (:8001) 委员会/治理/ML/agentic/xsec_model
  mcp-tool-service/  (:8002) FastMCP：finance / zoo / factor_eval / portfolio / paper_engine …
  storage-service/   (:8003) SQLite + PIT 时点表
  ingestion-service/ (:8004) APScheduler 采集/复盘/告警/PIT 快照
  offline-runner/           离线批：因子评估 / 截面模型训练
tests/              # 358 个单元测试（TDD）
scripts/            # 因子评估批 / 训练 / 冒烟 / 推送
docs/superpowers/   # 设计规格说明书 + 计划
guide-baseline/     # 《MCP 实验指导书》原样基线（备查）
deploy/             # docker-compose.yml（6 服务）, .env.example
报告/               # 实验报告.docx / .md、模型准确率可视化、截图
```

---

## 诚实边界与免责

本平台的设计哲学是 **可信·可解释·诚实**：宁可诚实报告"不确定/弃权/跑输"，也不制造漂亮但虚假的指标。所有结果均为研究性质，**不构成投资建议、不用于实盘交易**；市场有风险，决策需谨慎。
