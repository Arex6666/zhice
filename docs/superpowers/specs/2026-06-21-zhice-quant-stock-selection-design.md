# 智策 ZhiCe — A股中证800多因子选股系统设计规格说明书

> 版本 v1.1 · 编制日期 2026-06-21 · 首席量化架构师
> 定位：**研究型 · 诚实 · 弃权感知 · 不实盘**。对标专业机构方法学，但不承诺跑赢市场。
> 本文档已吸收逐层对抗核验（adversarial verdict）的全部高/中危修正，凡接口、依赖、PIT、泄漏、过拟合断言均以**已实测**为准（见 §16 接口实测附录）。
> v1.1 增量：吸收第二轮评审 14 项必修项——百度估值真实形态（单指标×period）、估值因子双路径 PIT 语义分离、ML 工件 Python/库版本契约、LSY 剔小市值过滤、A股风格因子基底、long-only 显著性判据统一、单因子设计网格 CPCV、真预告/快报日下界对齐、factor_eval schema 与"因子级→个股级"映射、BL 默认关闭与依赖件验收、MCP 工具 realtime/offline 切分、申万行业数据源、DSR 的 Var(SR_trials) 口径、M5–M7 两段式验收 + PIT 成熟度门。

---

## 0. 阅读指引与全局诚实约束（先读）

本规格的每一处技术承诺都受三条不可让渡的约束钳制，凡与之冲突者一律以约束为准：

1. **不冒充能力**：凡数据/接口/历史深度不可得，必须显式标注差距并降级为"弃权"或"forward-PIT-only"，**绝不**用今日快照回填历史并声称已消除偏差。
2. **弃权优先于给数**：样本不足、PIT 不可得、统计不显著 → 返回 `significant=None` / `abstain=True`，而非画一条看似可信的曲线。
3. **诚实标签随值同行**：`pit_status` / `caveat` / `survivorship_note` 是**结构化字段**，随每条因子值穿过 storage→mcp→committee→chair→仪表盘全链路，任一跳剥离即视为违规。

> 核验中暴露的最大反诚实失败模式：**把"数据缺失 / 模型加载失败 / PIT 不可得"包装成"统计弃权"**。本系统在 `abstain_reason` 中**强制区分** `data_missing` / `model_load_failed` / `insufficient_history` / `statistical_abstain` 四类，不得混淆。

> **第二轮核验补充的两条反诚实失败模式**（v1.1 新增，全文优先级等同上三条）：
> - **把横截面排名当个股 alpha 故事**：因子级 RankIC 显著 ≠ 某只个股有方向 alpha。任何"该股在该因子上分位高 → 看多"的直接推断都被 §10.3「因子级证据→个股级证据」映射规则拦截（必须 family 通过闸门 AND 极端分位 AND 控制风格后仍极端，三条同时成立才出 stat 证据）。
> - **里程碑可演示 ≠ 因子可信**：在 PIT 历史累积不足时，M5–M7 的"验收通过"只证明**管线正确性**（防泄漏/弃权逻辑/治理触发），**不构成 alpha 证据**。真实有效性须待 PIT 成熟度门（§14.2）触发后复核。

---

## 1. 概述与定位

### 1.1 系统目标

智策是一个面向 **A股中证800（沪深300 + 中证500）** 的横截面多因子选股**研究**平台。它在既有"单标的时序诚实引擎"之上，长出一条 **(date, instrument) 横截面面板 + Point-in-Time(PIT) 数据通道**，覆盖从因子构造、机构级因子评估、因子合成、组合构建到风控/治理/诚实披露的完整 7 层链路（L0–L7），并以多智能体委员会 + 确定性治理引擎 + MCP 工具边界把它们编排起来。

### 1.2 三性定位

| 性质 | 含义 | 落地机制 |
|---|---|---|
| **可信 (trustworthy)** | 结论可被证伪，不夸大 | purged-CV + 块自助显著性 + BH-FDR + Deflated Sharpe；强制并列买入持有基准 |
| **可解释 (explainable)** | 每个判断有证据与经济逻辑 | 因子公式字符串（DSL）+ SHAP/feature_importance + 一句经济故事 + 风险归因（行业/风格/特质） |
| **诚实 (honest)** | 主动披露局限与弃权 | 每因子标注 数据源/PIT状态/历史深度/幸存者偏差/覆盖率；无统计优势即弃权 |

### 1.3 对标专业机构的现实标尺（防自欺）

- Qlib 在 CSI300/CSI500 真实基准 **Rank-IC 仅 0.04–0.052**（XGBoost ~0.05）。任何 IC 显著高于此者应先怀疑泄漏，而非庆祝。
- 约 **83–87% 的 A 股异象复现失败**（Li-Liu-Liu-Wei 2024, MgmtSci）：默认假设是"这个因子无效"，举证责任在因子。
- LLM 交易 agent **常跑不赢买入持有**（StockBench 2510.02209 / Agent Market Arena 2510.11695）：本系统把"跑不赢买入持有"做成**产品默认诚实视图**，而非缺陷。

### 1.4 硬边界（不做项）

- ❌ 不做实盘撮合/下单（项目宪法级硬约束）。
- ❌ 不自建 Wind/聚宽级真 PIT 时点库（付费，列为已知差距）。
- ❌ 不引入 tick / 机构持仓明细 / HFT 路线（akshare 仅日频，强行复现引入未来函数）。
- ❌ 不引入 Qlib / baostock 重依赖到运行时（仅镜像其 DSL/PIT/分层**概念**）。

---

## 2. 业余 vs 专业量化的差异与本系统取舍

| 维度 | 业余做法（陷阱） | 专业机构做法 | 智策取舍 |
|---|---|---|---|
| **股票池** | 用今日成分回溯历史 | 时点历史成分（含退市/ST） | akshare 无历史成分 → **forward-PIT 累积 + 显式标 `survivorship_biased`**；启动前历史标注偏差未消除（诚实差距） |
| **小市值污染** | 全样本跑 IC | LSY：剔最小30%市值 + 剔次新/ST/壳 去壳价值污染 | **【核验修正】** universe(t) 与 L2 评估加 `lsy_filter` 档（可配置）；IC 须"剔小票后"与"全样本"双口径分别报告 |
| **财务对齐** | 用报告期末日 | 用公告日 announce_date | akshare 无公告日列 → **可见日 = min(法定截止日, 实测预告/快报披露日)**；默认管线即用真预告/快报日作下界锚点（见 §4 L0） |
| **因子评估** | 单一回测夏普 | IC/ICIR + 分层 + 换手 + 半衰期 + 分布 | 四项**联合**判定 + CPCV 多路径分布（Lalwani 非标准误差达 5×） |
| **多重检验** | t>2 挑最佳 | BH-FDR + Harvey t≥3.0 + DSR | 全家桶 Rank-IC 统一 BH，新因子 Harvey 门槛，DSR 扣试验次数 N（N 与 Var(SR_trials) 同源于设计网格，见 §7） |
| **CV** | 随机 k-fold | purged + embargoed CV / CPCV | 按 DATE 分折 + 标签[t,t+h]重叠 purge + embargo≥h；**单因子层也跑多路径稳定性，非单点** |
| **协方差** | 裸样本协方差求逆 | Ledoit-Wolf 收缩 | N(800)>>T → LW 收缩 + EWMA；HRP 大池默认（不求逆） |
| **MVO** | 裸 max-Sharpe | 收缩+约束+1/N 对照 | MVO 仅在 N≤100 收窄池且 T≥2N 启用；默认 HRP/ERC |
| **标准化** | 全期 mean/std | 逐截面 | 逐截面 z-score + 中性化，绝不跨期池化 |
| **ML** | 深网堆叠 | 浅层 GBDT（GKX：NN ~3层见顶） | XGBoost/LightGBM max_depth 3–6 + 强正则 + early stopping；**训练与推理同 Python/库版本同容器**（§4 架构契约） |
| **ML 启用** | in-sample 好就用 | OOS 优于线性基线才启用 | promote-then-prove：purged-CV OOS 优于「价量+估值+A股风格因子线性组合」基线 + 块自助显著，否则弃权 |
| **成本** | 忽略或低估 | 计 fee+印花税+滑点，net 口径 | A 股化成本：卖出加印花税0.05%，做空腿明示融券受限、降为纯诊断 |
| **结论** | 单点估计当真理 | 报告分布 + 弃权 | 设计选择网格分布 + DSR + 与 1/N 对照 |

**核心取舍立场**：智策宁可在头 12–24 个月对大量另类因子**全面弃权**（forward-PIT 累积不足），也不用今日快照制造虚假历史 alpha。这是"诚实但暂时无用"对"好看但虚假"的主动选择。

---

## 3. 总体架构图

### 3.1 七层 + 微服务 + MCP + 多智能体（ASCII）

```
┌──────────────────────────────────────────────────────────────────────────────────────┐
│  L7  前沿 LLM/智能体层 (离线 propose-then-prove 证伪机, 绝不进实时热路径)                │
│      scripts/mine_llm_factors.py: LLM→DSL公式候选→AlphaEval五维→原创性正则→            │
│                                   purged-CV→BH+Harvey+DSR→优于基线才落库, 否则弃权      │
└───────────────▲────────────────────────────────────────────────────────────────────────┘
                │ (离线产物: 通过闸门的因子 + 全套统计证据 + 元数据)
┌───────────────┴──────────────────────────────────────────────────────────────────────┐
│  L5/L6  风控/择时叠加 (vol_state + QVIX → 仓位乘子∈[floor,1]) · 治理/诚实 (R1–R13)      │
│         regime_overlay · qvix_timing · ic_audit · factor_gate · governance R10–R13      │
└───────────────▲────────────────────────────────────────────────────────────────────────┘
                │
┌───────────────┴──────────────────────────────────────────────────────────────────────┐
│  L4  组合构建与风险模型 (research-only, 重计算→离线批, 不进委员会 SSE)                   │
│      portfolio.py: shrink_cov(LW) · risk_parity(ERC) · hrp · mvo(cvxpy) · BL(P2 默认关) │
│      risk_model.py: Barra Σ=BFB'+D 风险归因 · capacity_check · 强制 vs 1/N 对照          │
└───────────────▲────────────────────────────────────────────────────────────────────────┘
                │ (expected-return 向量 = 通过闸门的因子合成打分; 仅多头)
┌───────────────┴──────────────────────────────────────────────────────────────────────┐
│  L3  因子合成 (横截面 alpha 组合, 训练&推理同 py3.12 同容器=agent-service)               │
│      factor_combine.py: 线性基线(等权/IC加权) ← 诚实默认 & ML 弃权回退                   │
│      xsec_model.py: GBDT 横截面排序 + 诚实闸门(ΔRank-IC CI下界>0 才接管)                 │
└───────────────▲────────────────────────────────────────────────────────────────────────┘
                │ (clean 因子矩阵 + 单因子诊断)
┌───────────────┴──────────────────────────────────────────────────────────────────────┐
│  L2  因子评估 (alphalens 对标的诚实闸门, 离线批, 重计算工具不进 SSE)                      │
│      factor_eval.py: Rank-IC/ICIR/HAC-t/块自助 · quantile分层单调 · long_only · 换手    │
│      panel_cv.py: 真 purged+embargo+CPCV+PBO  ·  multi_test.py: BH-FDR/Harvey/DSR       │
└───────────────▲────────────────────────────────────────────────────────────────────────┘
                │ (raw 因子矩阵 + 逐因子 metadata; 风格因子基底)
┌───────────────┴──────────────────────────────────────────────────────────────────────┐
│  L1  因子库 (横截面构造 + 预处理 + 元数据)                                               │
│      factor_dsl.py(~25算子) · factors/zoo.py(全家桶~20+公式+A股风格基底) · preprocess.py │
│      (去极值→z-score→申万一级行业+市值中性化) · altfactors.py(北向/EPS-rev/PEAD/户数/闸) │
└───────────────▲────────────────────────────────────────────────────────────────────────┘
                │ (时点可见面板: asof(可见日<=t) + universe(t) + lsy_filter)
┌───────────────┴──────────────────────────────────────────────────────────────────────┐
│  L0  数据层 (中证800 PIT 面板采集与存储)                                                 │
│      ingestion: akfetch.py(cross_section/per_symbol 双粒度) · pit_snapshot.py · calendar │
│      storage:   panel_daily · fundamentals_pit · index_membership · events · factor_meta│
│                 + factor_eval + portfolios; asof() · universe() · panel_asof_matrix()    │
└──────────────────────────────────────────────────────────────────────────────────────┘

═══════════════════════════════════ 微服务边界 ═══════════════════════════════════════════
 api-gateway        agent-service              mcp-tool-service          ingestion-service   storage-service
 (FastAPI+ECharts)  (py3.12; committee/        (py3.12; FastMCP          (scheduler 定时      (SQLite:
  /api/finance/*     governance/ml_signal/      stdio+SSE; 纯函数计算)    PIT快照+复盘+告警)   quotes/news/
  仪表盘             finance_agent/calibration/ factors/ portfolio.py     akfetch.py           analysis/alerts/
                     news_nlp/review/xsec_model)risk_model.py             pit_snapshot.py      watchlist + PIT 7表)
                        │                          ▲                         │                    ▲
                        │  mcp_client (SSE 单会话)  │ realtime 只读工具       │ httpx POST /pit/*  │
                        └──────────────────────────┘ (offline 重计算工具     └────────────────────┘
                                                      由 scheduler 直调, 不进 SSE)

═════════════════════════════════ 多智能体委员会 ═════════════════════════════════════════
 finance_agent.deep → run_committee(symbol):
   ┌─ 现有4 LLM 委员 (基本面/技术面/情绪面/风险面)
   ├─ ml_signal 风险票 (XGBoost 波动校准, 非方向, type=model, py3.12 同栈)
   ├─ 量化因子面分析师 (读 storage.factor_eval 落库 + §10.3 个股映射, type=stat) ← 新增, 只读离线产物
   ├─ 另类数据分析师 (北向/资金面, type=stat)                          ← 新增
   ├─ 盈利修正分析师 (EPS-revision/PEAD, type=stat)                    ← 新增
   └─ 证伪官 (反向证据翻转率 P3, 共线性检查)                            ← 新增
         │ _reverify_evidence_types → R9 交叉质询
         ▼
   governance.govern(members, data_status, ml, backtest_stable, vol_regime, factor_flags, regime_scale)
         │ R1–R8(确定性) + R10–R13(因子/组合) ; R9 在 committee 层
         ▼
   主席汇总 (confidence clamp 到 ceiling, 方向落 allowed_verdicts)
```

### 3.2 关键架构决策一：不新增 factor-service 微服务

经源码核验，因子/组合计算落入 **mcp-tool-service 的 `factors/` 子包 + `portfolio.py`**，理由：(1) mcp-tool-service 已是"纯函数计算 + FastMCP 工具"聚合点（backtest/volatility/anomaly/crossasset/seasonality 同档）；(2) 委员会经 mcp_client SSE 单会话调用，多一个微服务 = 多一条 SSE 链路 + 部署面，收益为负；(3) TDD 脱网单测范式可直接复用。

但本论断**有前置条件**（见下两条架构契约），不再是无条件的"零改动可拆出"。

### 3.3 关键架构决策二：模型工件 Python/库版本契约（【核验修正】）

**问题**：实测 agent-service 镜像锁 **Python 3.12**（注释明言"匹配 xgboost 3.3.0 的 pickle 跨端可加载"），mcp-tool-service 镜像是 **Python 3.11**。现有 `ml_signal`/`SignalCalibrator` pickle 在 py3.12 训练。若 mcp-tool（3.11）load/predict 任何共享 pickle，将重蹈"模型 pickle 跨端不可加载"的坑；sklearn/xgboost pickle 协议在跨 minor Python/库版本下不保证兼容。

**决策（二选一，本规格采用方案 A）**：

- **方案 A（采用）——训练与推理同栈同容器**：横截面 GBDT（`xsec_model.py`）的**训练（离线 `scripts/`）与推理均放 agent-service（py3.12，与 `ml_signal` 同栈）**。mcp-tool-service **只暴露纯统计/组合函数**（IC/分层/协方差/HRP/ERC/DSR/CPCV 等无 pickle 依赖的纯数值计算），**绝不 load/predict 任何 ML pickle 工件**。L3 合成时，委员会经 agent-service 内部直接调用 `xsec_model.predict`（同进程，无跨容器 pickle）。
  - 表现层：`factor_combine`（线性合成，纯函数、无 pickle）可留在 mcp-tool；`xsec_rank`（树模型推理）迁至 agent-service，mcp-tool 的 `xsec_rank` 工具改为"转发到 agent-service 推理端点或仅返回线性基线"。
- **方案 B（备选，不采用）**：把 mcp-tool 镜像升到 3.12，并在 CI 实测 pickle round-trip。仅当未来必须把树推理放 mcp-tool 时才启用。

**强制落地——"模型工件契约"条款（写入 §12 测试 + CI）**：

1. 所有 ML pickle 工件随包写入 sidecar `artifact_meta.json`：`{python_version, sklearn_version, xgboost_version, numpy_version, trained_at, model_class, feature_names_hash}`。
2. 加载侧（agent-service）启动时校验运行环境与 sidecar 一致；**不一致 → `abstain_reason='model_load_failed'`**，绝不静默降级为"统计弃权"。
3. **跨容器 pickle round-trip 回归测试**：CI 在 agent-service 容器内 dump、在拟接收容器内 load+predict，断言预测逐位一致；任一不一致即红灯。此测试是 §3.2"子包可零改动拆出"论断成立的**必要条件**——契约不绿，则不得把任何 pickle 依赖工具拆到异版本容器。

### 3.4 关键架构决策三：MCP 工具面 realtime/offline 切分（【核验修正】）

**问题**：多数 L2/L4 工具（`factor_report`/`evaluate_factor_cv`/`build_portfolio`/`efficient_frontier`/`panel_cv`/CPCV/`mine_llm_factors`）是 CPU 密集的**离线批语义**，但若全部注册成同一 FastMCP **实时**工具面、经委员会 SSE 单会话调用，一次 `efficient_frontier`/CPCV 调用会**阻塞 FastMCP 事件循环**（现有工具均为轻量 async I/O）。

**决策——两类工具面物理切分**：

- **(a) realtime 只读工具**（进 FastMCP 热路径、委员会 SSE 可直调）：`get_universe` / `asof_value` / `get_panel` / `factor_metadata` / `list_factor_meta` / `data_coverage_report` / `pit_data_health` / 以及**读取 L2/L4 落库结果**的工具（`read_factor_eval` / `read_portfolio`）。均为轻量 SQLite 查询，毫秒级返回。
- **(b) offline 重计算工具**（**仅由 scheduler 离线 job 直接调用、结果落库，绝不进委员会 SSE 会话**）：`panel_cv` / CPCV / `build_portfolio` / `efficient_frontier` / `evaluate_factor_cv` / `factor_report`（全量重算路径）/ `mine_llm_factors` / `train_xsec`。

§10.2 工具目录中**每个工具标注 `realtime|offline`**。对 offline 工具，即便它们因复用而被注册到 FastMCP，也必须用 **`anyio.to_thread.run_sync` 卸载到线程**或交由**独立进程**执行，避免阻塞事件循环；并在工具 docstring 与返回体标 `execution_mode='offline'`，委员会侧的调用白名单**硬拒** offline 工具（调用即返回 `error='offline_tool_not_callable_in_committee'`）。

---

## 4. L0–L7 逐层详细设计

> 每层格式：组件 → 算法/公式 → 库 → 数据源+PIT状态 → 数据流。已吸收 verdict 修正项以 **【核验修正】** 标注。

### L0 — 数据层（中证800 PIT 面板采集与存储）

**职责**：交付唯一可信的数据地基——带 `visible_date`/`announce_date` 戳的时点面板 + `universe(date)` + `asof()` 查询。不出研判、不算因子。

#### 组件

| 模块 | 服务 | 职责 |
|---|---|---|
| `akfetch.py` | ingestion | akshare 采集适配层（**新建，非复用现有 Sina/EM 价量链**）。`anyio.to_thread` 卸载同步 akshare（沿用 finance.py `get_news` 范式）；防御式字段解析；obs.TTLCache 限流 + obs.Metrics 按源计量 |
| `pit_snapshot.py` | ingestion | PIT 快照编排：5 个 scheduler job（见下），逐源 try/except 失败隔离 |
| `calendar.py` | ingestion | 交易日历（`tool_trade_date_hist_sina`），**启动时拉一次落地缓存（长 TTL）**，回退仅作末端兜底并告警 |
| db.py PIT 扩展 | storage | 7 张新表 + `asof()`/`universe()`/`panel_asof_matrix()` 查询 |
| app.py PIT REST | storage | `POST/GET /pit/*` 端点 |
| `pit_panel.py` | mcp-tool | FastMCP **realtime** 工具暴露：`get_universe`/`get_panel`/`asof_value`/`data_coverage_report`/`list_factor_meta`/`read_factor_eval`/`read_portfolio` |

#### 【核验修正】调用粒度双类适配器（非统一 symbol 抽象）

实测多个接口是**全市场截面**而非 per-symbol。强制按调用粒度分类：

```python
# (a) cross_section 源: 一次拿全市场, 再用 universe(t) 过滤入库, 每日/每期 1 次调用
CROSS_SECTION_APIS = {
  "index_stock_cons_csindex": "symbol=指数代码, 无 date 参数 → 仅今日成分快照",  # 【实测确认无 date 参】
  "stock_zh_a_spot_em":       "全市场快照(动态PE/PB/总市值/换手/量比)",
  "stock_yjyg_em":            "date=报告期 → 全市场业绩预告, 携真预告披露日",
  "stock_yjkb_em":            "date=报告期 → 全市场业绩快报, 携真快报披露日",
  "stock_gpzy_pledge_ratio_em": "date → 全市场质押",
  "stock_hsgt_hold_stock_em": "market+indicator 枚举 → 全市场北向排名快照",
  "stock_board_industry_name_em": "全市场申万/东财一级行业列表(行业→代码)",  # 【新增: 行业映射源】
}
# (b) per_symbol 源: 才走逐标的循环
PER_SYMBOL_APIS = {
  "stock_financial_analysis_indicator": "symbol → 多年财务(按报告期末索引, 无公告日列)",  # 【实测】
  "stock_zh_valuation_baidu":  "symbol+indicator+period → 单指标单列 value 时序",  # 【替代失效的 stock_a_indicator_lg; 真实形态见下】
  "stock_individual_info_em":  "symbol → 个股所属行业(申万/东财一级)",  # 【新增: 个股→行业归属】
  "stock_hsgt_individual_detail_em": "symbol+start+end → per-symbol 北向持股明细",  # 【实测存在】
  "stock_zh_a_gdhs_detail_em": "symbol → per-symbol 股东户数明细",  # 【实测存在】
  "stock_individual_fund_flow": "symbol → 资金流",
  "stock_restricted_release_queue_em": "symbol → 解禁",
}
```

`factor_meta` 新增 `fetch_granularity ∈ {cross_section, per_symbol}` 字段。

#### 【核验修正】百度估值接口的真实形态（§16 附录同步修订）

实测 `stock_zh_valuation_baidu(symbol, indicator, period)` 的真实形态为：

- **单指标单列**：每次调用仅返回**一个**指标（`indicator ∈ {市盈率(动)/市盈率(静)/市净率/市销率/总市值}`），DataFrame 仅 `date` + `value` 两列；**不**一次返回 PE/PB/PS/总市值多列。
- **period 决定历史窗，默认仅近一年**：`period ∈ {近一年/近三年/近五年/近十年/全部}`，`period='近一年'` 实测仅 ~366 行；**长历史必须显式传更长 period**——"多年"**不是自动的**。
- **由此推论**：每个估值因子 = `symbol × indicator × period` 的**笛卡尔调用**。覆盖 EP/BP/SP/DY 四个估值因子至少需 **4+ 次/标的**调用（每指标一次，外加确定 period）。M0 PoC 必须按此预算调用次数与限流，否则直接撞墙。

**`factor_meta` 增字段**（落地百度接口维度）：`baidu_indicator TEXT`（如 `市盈率(动)`）、`baidu_period TEXT`（实际拉取的 period，如 `近五年`）。`history_depth_days` **按实际拉取的 period 落地**（如 period='近一年'→~252、'近五年'→~1260），**不得标"多年"**。

#### 【核验修正】EP 口径二选一（避免两路口径漂移）

EP 的取数路径**显式二选一并写明**，全系统统一：

- **路径 A（默认采用）——百度估值快照路径**：`EP = 1 / 市盈率(动)`（直接由 `stock_zh_valuation_baidu(symbol, '市盈率(动)', period)` 取 PE 后取倒数）。BP=`1/PB`、SP=`1/PS`、DY 由股息率指标或 `1/PS·派息率` 不可得时弃权。**此路径 PIT 语义 = `forward_pit_only`（无修订链/无 vintage），见 §5.3**。
- **路径 B（备选，不与 A 混用）——财报字段 + K 线自算路径**：`EP = 净利润TTM / 总市值`，分子取自 `stock_financial_analysis_indicator` 财报字段、按法定截止日/真披露日对齐，分母取 K 线收盘价×股本。**此路径 PIT 语义 = `lagged_legal_deadline`，见 §5.3**。

**同一因子在同一管线内只挂一条路径、一种 PIT 标**，禁止 A/B 混用导致口径漂移。默认全系统走路径 A（数据可立即获得、历史深度由 period 决定），路径 B 作为 PIT 严谨度更高的可选升级（待 §14 PIT 成熟度门后评估切换）。

#### 数据库 schema（storage db.py，沿用单文件 SQLite + `with _conn` 短事务）

```sql
-- 本期启用 WAL 降锁竞争（一行配置, 非迁移）:
PRAGMA journal_mode=WAL; PRAGMA busy_timeout=5000;

CREATE TABLE IF NOT EXISTS panel_daily(
  symbol TEXT, date TEXT, field TEXT, value REAL,
  source TEXT, visible_date TEXT,   -- 统一时点轴: =as_of(快照时点); 永不用 ingest_ts 查询
  ingest_ts TEXT,                   -- 仅审计, 不入时点查询
  PRIMARY KEY(symbol,date,field,source));
CREATE INDEX idx_panel_dfs ON panel_daily(date,field,symbol);
CREATE INDEX idx_panel_sfv ON panel_daily(symbol,field,visible_date);

CREATE TABLE IF NOT EXISTS fundamentals_pit(
  symbol TEXT, period TEXT,
  announce_date TEXT,        -- 可见日 = min(法定截止日, 真预告/快报日); 见下对齐逻辑
  legal_deadline TEXT,       -- 法定截止日(回退锚点)
  disclosed_date TEXT,       -- 实测预告/快报披露日(下界锚点, 可空)
  field TEXT, value REAL, source TEXT, pit_status TEXT, ingest_ts TEXT,
  PRIMARY KEY(symbol,period,field,source));
CREATE INDEX idx_fund_sad ON fundamentals_pit(symbol,announce_date);

CREATE TABLE IF NOT EXISTS index_membership(   -- forward-only 累积
  date TEXT, symbol TEXT, weight REAL, index_code TEXT,
  universe_pit_status TEXT,  -- 'forward_snapshot' | 'today_snapshot_only'(启动前)
  PRIMARY KEY(date,symbol,index_code));

CREATE TABLE IF NOT EXISTS events(
  symbol TEXT, event_type TEXT, announce_date TEXT, payload_json TEXT,
  source TEXT, ingest_ts TEXT);
CREATE INDEX idx_evt_sad ON events(symbol,announce_date);

CREATE TABLE IF NOT EXISTS factor_meta(
  factor_name TEXT PRIMARY KEY, source TEXT, akshare_api TEXT,
  fetch_granularity TEXT, pit_status TEXT,    -- {history_native, forward_pit_only, lagged_legal_deadline, lagged_fixed, risk_gate}
  baidu_indicator TEXT, baidu_period TEXT,    -- 【核验修正】百度估值维度落地
  compute_path TEXT,                          -- 'baidu_snapshot' | 'report_kline' (EP 等口径路径)
  history_depth_days INTEGER, backtestable_from TEXT,  -- 硬约束下游回测起点
  survivorship_note TEXT, coverage REAL, direction TEXT,  -- direction ∈ {+,-,risk_gate}
  sw_industry_source TEXT,    -- 行业映射来源(中性化依赖)
  regime_breaks TEXT,  -- JSON list, 如北向 2024-08 口径变更点
  caveat TEXT);

-- 【核验修正】L2 离线批落库表(委员会只读); schema 与 §10.3 个股映射对齐
CREATE TABLE IF NOT EXISTS factor_eval(
  factor_name TEXT, family TEXT, as_of TEXT,     -- 评估批次时点
  horizon INTEGER, n_quantiles INTEGER, neutralize_variant TEXT, rebalance INTEGER,  -- 设计选择网格坐标
  universe_filter TEXT,                           -- 'all' | 'lsy'(剔小票) 双口径都落
  mean_rank_ic REAL, icir REAL, ic_t_hac REAL, ic_block_boot_p REAL,
  monotonic_spearman REAL, long_only_excess REAL, long_only_block_boot_p REAL,
  ls_research_only_sharpe REAL,                   -- 仅诊断展示, 不作通过判据
  turnover REAL, ic_half_life REAL,
  bh_passed INTEGER, harvey_passed INTEGER,
  dsr_optimistic REAL, dsr_conservative REAL, n_trials INTEGER, var_sr_trials REAL,
  family_verdict TEXT,                            -- {有效稳定,衰减中,不稳定,失效,样本不足}
  residual_incremental_ic REAL,                   -- 控制风格基底后的增量 IC
  significant INTEGER,                            -- 1/0/NULL(弃权)
  abstain_reason TEXT,                            -- data_missing/insufficient_history/statistical_abstain
  computed_at TEXT,                               -- 落库时间, 供 staleness 判定
  PRIMARY KEY(factor_name, as_of, horizon, n_quantiles, neutralize_variant, rebalance, universe_filter));
CREATE INDEX idx_feval_fam ON factor_eval(family, as_of);

CREATE TABLE IF NOT EXISTS portfolios(
  portfolio_id TEXT, as_of TEXT, method TEXT, weights_json TEXT,
  beats_1overN INTEGER, excess_block_boot_p REAL, cov_method TEXT, cov_delta REAL,
  capacity_flag TEXT, fallback_reason TEXT, computed_at TEXT,
  PRIMARY KEY(portfolio_id, as_of));
```

#### 核心算法/公式

- **PIT as-of 查询（防前视核心）**：`value_visible(s,f,t) = SELECT value FROM fundamentals_pit WHERE symbol=s AND field=f AND announce_date<=t ORDER BY announce_date DESC LIMIT 1`。日频 panel 用 `visible_date<=t`。**akshare 无修订链(vintage)** → 只能取最新修订值 → `pit_status='forward_pit_only'`，**绝不标 `true_pit`**。
- **幸存者偏差**：`universe(t)` = index_membership 中 `date<=t` 最近的成分快照。**【核验修正】** index_stock_cons_csindex 实测无 date 参数、仅返今日成分 → 启动前历史**无法重建** → `universe_pit_status='today_snapshot_only'` + 仪表盘强制提示偏差未消除。
- **【核验修正】LSY 剔小市值过滤档**：`universe(t)` 支持 `lsy_filter ∈ {off, on}`。`lsy_filter=on` 时按 Liu-Stambaugh-Yuan(2019) 剔除：(1) 截面**最小 30% 市值**股；(2) **次新股**（上市<6 个月）；(3) **ST/*ST**（名称含 ST）；(4) 可识别**壳股**代理（极小市值 + 长期停牌/无主业，启发式标 caveat）。该过滤在 universe 构造与 L2 评估**两处**落地。**默认评估管线对每个因子在 `universe_filter='all'` 与 `'lsy'` 双口径分别跑 IC/分层并落 factor_eval**（见 §6）。**未启用 lsy_filter 的口径，文中不得引 LSY 作方法学背书**。
- **【核验修正】财报可见日对齐（升为默认管线）**：
  ```
  可见日 announce_date = min( 法定截止日 legal_deadline ,  实测预告/快报披露日 disclosed_date )
  其中 disclosed_date 取自 stock_yjyg_em(业绩预告) / stock_yjkb_em(业绩快报) 的真披露日
  仅当无任何披露日证据 → 回退 announce_date = legal_deadline
  legal_deadline: 年报次年4/30, 半年报8/31, 三季报10/31, 一季报4/30
  ```
  pit_status：当 `disclosed_date` 命中并早于法定日 → `pit_status='lagged_disclosed'`（已用真披露日）；回退法定日 → `pit_status='lagged_legal_deadline'`。
  **理由**：A 股大量公司远早于法定日披露（1 月底业绩快报、3 月披露年报）。一律推到 4/30 会人为延迟 3–4 个月信息释放、系统性削弱质量/价值因子真实 IC、制造"因子无效"的假阴性。回归测试必须覆盖：(a) 晚于披露日的数据不泄漏；(b) 有 disclosed_date 时可见日确实提前到 disclosed_date。

#### 库与数据源
numpy/pandas/httpx/anyio/apscheduler/fastapi+pydantic/sqlite3/mcp（均已装）。akshare 接口见 §16 实测附录。

#### MCP 工具（均 **realtime**）
`get_universe(date, lsy_filter)` · `get_panel(date, fields)` · `asof_value(symbol, field, date, indicator, period)` · `data_coverage_report(date)`（含 `backtestable_from`）· `list_factor_meta()` · `read_factor_eval(...)` · `read_portfolio(...)` · `pit_data_health()`。

---

### L1 — 因子库（横截面构造 + 预处理 + 元数据）

**职责**：把全家桶因子做成可审计公式，施加机构标配三件套预处理，逐因子产出 clean 值 + 元数据。**L1 只产 clean 因子，不做因子选择、不判显著性**（防 L1 层引入选择偏差，BH/DSR 全在 L2）。

#### 组件

| 模块 | 职责 |
|---|---|
| `factor_dsl.py` | Qlib 式 ~25 算子（仅单标的时序 + 算术/比较/If）+ AST 解析 + 算子白名单（拒 eval，防注入与隐含未来函数算子）。**横截面算子(Rank/Quantile/zscore)交给 preprocess 逐截面执行以防泄漏** |
| `factors/zoo.py` | 全家桶 ~20+ 因子公式字符串 + 每因子 metadata + **A股风格因子基底**（§5.7） |
| `preprocess.py` | 逐截面：MAD去极值 → z-score → **申万一级行业 + ln市值**中性化（numpy.linalg.lstsq 残差） |
| `altfactors.py` | 6 类另类/风险因子纯函数 |
| `industry_map.py` | **【核验修正】申万一级行业映射**（数据源 + PIT/覆盖率，见下） |

#### 算子集（DSL）
`ts_mean / ts_std / delay / delta / corr / cov / ts_max / ts_min / idxmax / ema / wma / slope / rsquare / resid / scale + Add/Sub/Mul/Div/Gt/Lt/If`。复用 indicators.py 的 rolling 与 volatility.py 的 ewma 数学（**仅抄数学常数，不调函数**——核验指出复用度此前被夸大）。

#### 【核验修正】申万一级行业映射数据源（中性化的前置依赖）

预处理第 3 步中性化需"申万一级行业哑变量"。实测数据源补齐：

| 用途 | akshare 接口 | 粒度 | 覆盖率 | PIT 状态 |
|---|---|---|---|---|
| 行业清单（行业→代码） | `stock_board_industry_name_em` | cross_section | 全市场一级行业 | forward 累积 |
| 个股→行业归属 | `stock_individual_info_em`（"行业"字段） | per_symbol | 中证800 基本全覆盖 | **行业归属随时间变更 → caveat** |

**PIT 注意**：行业分类本身有 PIT 问题（成分/归属会调整）。akshare 无历史行业归属 → **行业映射按 forward 累积**（同 universe），启动前历史段标 `industry_pit_status='today_snapshot_only'`，中性化结果带 caveat。`factor_meta.sw_industry_source` 记录来源。中性化与 §8.2 行业中性约束、Barra 行业暴露均以此映射为基底；映射缺失/覆盖率<阈值的截面 → 该截面中性化弃权（`data_quality=degraded`）。

#### 预处理流水线（固定顺序，逐截面日 t，Fama-MacBeth 风格）

**【核验修正：MAD 常数口径统一】** 区分两个用途，互为倒数：
```
σ_robust = 1.4826 · MAD        # 估稳健标准差 (= MAD / 0.6745)
z_mad    = 0.6745·(x−median)/MAD = (x−median)/σ_robust   # anomaly.mad_zscore 的 z 分数

步骤1 去极值:  x' = clip(x, median ± k·σ_robust),  k=3~5  (或 1%/99% winsorize), 记录 winsor_pct
步骤2 标准化:  z_i = (x_i − mean_cs)/std_cs            (仅当日横截面统计量)
步骤3 中性化:  clean_i = resid from OLS  z_i ~ α + Σβ_k·Industry_k(申万一级哑变量) + γ·ln(MktCap_i)
              用 numpy.linalg.lstsq; 行业哑变量去一列防共线; n_valid 阈值/条件数/R²异常 → 该截面弃权
```

#### 全家桶因子目录（摘要，完整表见 §5）
- **价量**：动量 `Mom_{12-1}=Ref(C,21)/Ref(C,252)-1`、短反转、低波 `IdioVol`、Amihud 非流动性、规模 `ln(MktCap)`
- **估值**：EP/BP/SP/DY —— **【核验修正】** 数据源由不存在的 `stock_a_indicator_lg` 改为 `stock_zh_valuation_baidu`（**单指标×period 笛卡尔调用**，见 §5.3 + L0 真实形态），口径走默认路径 A（百度快照，`forward_pit_only`）或可选路径 B（财报+K线，`lagged_*`）
- **A股风格因子基底**：MKT / SMB(规模) / VMG(价值−成长, LSY) ——**控制已知因子的可计算基底**（§5.7）
- **质量**：ROE / GrossProfitability / Accruals（按可见日对齐，min(法定截止日, 真披露日)）
- **另类**：北向 `NorthboundFlow` / `EPS-revision`（**未缩放或滞后均值缩放，绝不除当期EPS/股价** — Jung 2019）/ `PEAD-SUE`（预告日 t0）/ 股东户数 `Chip=-Δln(户数)`
- **资金流**：`main_fund_flow` —— **默认弃权**（方法学存疑，东财口径黑箱）
- **风险闸**：股权质押 / 限售解禁 —— `direction='risk_gate'`，只降权不产 alpha

#### 【核验修正】冷启动硬规则
`factor_meta` 增 `history_depth_days`（**按实际 period/累积落地，不标"多年"**）。L1/L2 对 `history_depth_days < 252` 的因子**强制 `significant=None`**（`abstain_reason='insufficient_history'`），可视化显示"样本积累中 N/必要N 天"而非画线。价量因子用真实长历史（K 线）立刻有深度 → `history_native`；估值因子深度 = 百度 period 实拉深度；财务/另类因子 `forward_pit_only` 初期不可评估。

#### MCP 工具（均 **realtime**，纯函数）
`build_factor_panel` · `compute_factor` · `preprocess_cross_section` · `factor_metadata` · `list_factor_universe` · `altfactor`。

---

### L2 — 因子评估（alphalens 对标的诚实闸门）

**职责**：对每个候选因子做机构级单因子诊断，对因子家族做多重检验，给"通过/降级/弃权"硬判定。**离线批处理任务**（scheduler 定时跑，§3.4 offline 工具面），落库 `factor_eval` 表；委员会只读落库结果，二者解耦。

#### 离线批运行频率与 staleness（【核验修正：委员可实现性前置】）
- **运行频率**：`factor_eval` 离线批由 scheduler 默认 **每个调仓周（周频）+ 每月全量**重算一次（设计网格全跑），低频因子（户数季频/解禁）随其数据更新触发。
- **staleness 阈值**：委员会读取时若 `now − computed_at > N 日`（默认 N=10 交易日）→ 该 stat 委员 **abstain**（`abstain_reason='insufficient_history'` 区别于 data_missing）。当日/当批无记录 → 同样 abstain。

#### 组件

| 模块 | 职责 |
|---|---|
| `factor_eval.py` | Rank-IC/ICIR/HAC-t/块自助 · quantile分层单调 · **long_only 超额** · turnover · rank_autocorr · ic_decay 半衰期；双口径(all/lsy) |
| `panel_cv.py` | **新写**的真 purged+embargo（按 DATE 分折，非复用 walk_forward_auc）+ **单因子设计网格多路径 + CPCV** |
| `multi_test.py` | seasonality 抽出的 BH + Bonferroni + Harvey + deflated_sharpe/psr |

#### 核心算法/公式

- **Rank-IC（主指标）**：`IC_t = Spearman(factor_t, fwd_return_{t+h})`；`ICIR = mean(IC)/std(IC)`；`年化ICIR = ICIR·√(年化调仓期数)`。标尺：|mean RankIC|≈0.03 可用 / 0.05 良好 / >0.10 罕见。**双口径**：每因子在 `all` 与 `lsy`（剔小票）两个 universe 上分别报告（防小市值污染高估反转/另类 IC）。
- **IC 显著性（抗自相关，两路）**：(A) Newey-West HAC：`t=mean(IC)/SE_HAC`，`SE_HAC=√[(γ0+2Σ(1-l/(L+1))γ_l)/T]`，`L=⌊4(T/100)^{2/9}⌋`；(B) 复用 `backtest.bootstrap_significance` 块自助（块长 `max(√T, h)` 覆盖标签重叠）。**【核验修正】** IC 序列 `n<20` 一律 `significant=None`；HAC 与块自助冲突时取更保守者（都显著才算）。
- **分层 + 多头超额（【核验修正：判据全面 long-only 化】）**：每截面分 N=5/10 层，`Spearman(层序号, μ_q)≈±1` 检验单调；**通过判据用 long-only top 分位组合超额，不用 LS 净额**：
  ```
  long_only_excess_t = μ_top(扣成本) − benchmark_t,   benchmark ∈ {买入持有, 1/N}
  → 块自助检验 long_only_excess 序列是否显著为正
  LS_t = μ_top − μ_bottom  仅作 _research_only 诊断展示(空头腿 A股不可实现), 绝不作通过条件
  ```
  dashboard 强制水印"空头腿 A股不可实现"+并列 long-only 与买入持有；**因子委员方向证据只用 long-only 分层与 IC**。全文凡"多空(long-only)"自相矛盾措辞统一改为"long-only top 分位超额"。
- **purged + embargoed CV / CPCV（【核验修正：单因子也跑多路径】）**：purge 剔除标签窗口 [t,t+h] 与测试日重叠的训练样本；embargo `e≥h`；CPCV 从 N 个日期块组合选 k 作测试 → C(N,k) 路径 → OOS 分布；`PBO = P(样本内最优在样本外排名落后中位数)`。
  - **单因子层**：不要求逐路径 PBO，但**必须对"设计选择网格"（horizon / 分层N / 中性化变体 / 调仓频率 / universe_filter）做最小 CPCV 或至少 multiple-path 稳定性**，报告网格 OOS 分布，并把保守 DSR 计入网格自由度。规格立场：**单因子 PBO 可省，但设计网格的 OOS 分布与保守 DSR 不可省**（与 §13 "设计选择构成多重试验" 自陈一致）。
  - **ML 合成因子层**：CPCV + 完整 PBO 必跑。
- **BH step-up**：升序 `p_(i)`，`q_(i)=min over j≥i of p_(j)·m/j`，`passed if q<α`。
- **Deflated Sharpe**（Bailey-López de Prado 2014，纯 scipy.stats.norm）：
  ```
  SR0 = √Var(SR_trials)·[(1−γ)·Φ⁻¹(1−1/N) + γ·Φ⁻¹(1−1/(N·e))]   (γ=欧拉常数, N=试验次数)
  DSR = Φ( (SR_obs−SR0)·√(T−1) / √(1 − γ3·SR_obs + (γ4−1)/4·SR_obs²) )
  ```
  **【核验修正：Var(SR_trials) 与 n_trials 同源】** 见 §7 专节定义。要点：N 与 Var(SR_trials) **同源于同一组设计选择网格**——该网格既给出试验数 N（=因子数×网格点数），又给出一组试验夏普 {SR_i} 用以估 `Var(SR_trials)`；当网格退化为单点（无分布）时，用解析近似 `Var(SR_trials)≈1/T` 并在返回体标 `var_source='analytic_1overT'`，**禁止用单点却伪造分布方差**。`test_multi_test` 的 López de Prado 对拍用例固定这一口径。

#### 中性化数值稳健化
丢弃/合并截面内成员 <5 的行业桶并标 `data_quality=degraded`；lstsq 加 rcond 或微岭正则；schema 强约束 `factor_value.visible_date ≤ date < fwd_return 窗口起点`，单测注入"用未来值构因子"反例断言被拒。

#### MCP 工具（均 **offline**，仅 scheduler 直调、落库）
`factor_report` · `factor_family_gate` · `build_factor_panel`（全量重算路径）· `evaluate_factor_cv` · `deflated_sharpe`。委员会侧只用 realtime 的 `read_factor_eval` 读结果。

---

### L3 — 因子合成（横截面 alpha 组合）

**职责**：把通过 L2 闸门的单因子合成为每调仓日的横截面单一打分，供 L4 作 expected-return 向量。**默认线性基线**；ML 仅在 purged-CV OOS 显著优于线性基线时接管/混入，否则弃权回退。**训练与推理同处 agent-service / py3.12（§3.3 契约）**。

#### 组件

| 模块 | 服务 | 职责 |
|---|---|---|
| `factor_combine.py` | mcp-tool（纯函数无 pickle） | (a) 等权合成（按方向）；(b) IC 加权 `score_i = Σ_j w_j·clean_{i,j}`，`w_j ∝ 滚动 mean RankIC_j`（仅历史，无前视） |
| `xsec_model.py` | **agent-service（py3.12）** | 浅层 GBDT（max_depth 3–5, 强正则, early stopping）训练**与推理**+ 诚实闸门；pickle 工件带 `artifact_meta.json` |

#### 诚实闸门（promote-then-prove，GKX 树>线性）
```
enable_ML  iff  (OOS_RankIC_ML − OOS_RankIC_baseline) 块自助 CI 下界 > 0
           AND  long-only top 分位超额(扣 fee+slippage+印花税) 块自助显著
           AND  通过 BH 因子闸
           AND  控制 A股风格基底(MKT/SMB/VMG)后增量 IC > 0   # 残差化后才采纳, 防换皮
否则 abstain → 回退线性基线
```
**【核验修正】**
- OOS 增益**基线**明确为 **「已入库价量+估值因子 + A股风格因子基底（§5.7 的 MKT/SMB/VMG）的 Elastic Net 线性组合」**——风格基底已在 §5.7 给出公式/数据源/PIT，**消除"控制 FF"的空指针**。残差化"控制已知因子"以此基底为可计算底座。
- **判据已全面 long-only 化**：通过条件用 long-only top 分位超额块自助显著，**移除任何含空头腿的 LS 净额作为通过条件**（LS 仅 _research_only 诊断展示）。
- ML 默认用已装 xgboost（lightgbm 列可选）；`abstain_reason` **区分** `model_load_failed`（含 §3.3 工件契约校验不过）/ `data_missing` / `insufficient_history` / `statistical_abstain`，杜绝缺陷伪装成诚实弃权。

#### A 股化成本口径
卖出加印花税 0.05%（单边）；做空腿明示融券受限 → **多空降为纯诊断，不进 expected-return**；组合层只用多头打分。成本一致性回归断言 L3/L4 同口径。

#### MCP 工具
`combine_factors`（**realtime**，纯线性，mcp-tool 内）· `xsec_rank`（**转发 agent-service 推理或返回线性基线**，§3.3）· `evaluate_factor_family`（**offline**）。

---

### L4 — 组合构建与风险模型（research-only）

**职责**：把 L3 打分（或 None）在可投域上转为研究型权重。**MVO 是误差最大化器** → 默认 HRP/ERC，MVO/BL 仅在收窄池启用，强制与 1/N 对照。**全部为重计算 offline 工具面（§3.4），由 scheduler 直调落库，委员会只读 read_portfolio。**

#### 组件
`portfolio.py`（纯函数核）+ `risk_model.py`（Barra 风险归因）。

#### 核心算法/公式

- **Ledoit-Wolf 收缩**：`Σ̂ = (1−δ)·S + δ·F`，`δ` 由 `sklearn.covariance.LedoitWolf` 解析求解；配 EWMA λ≈0.94。报 `δ` 与条件数（供 R11）。
- **MVO（cvxpy QP，DCP）**：
  ```
  maximize  μᵀw − γ·wᵀΣ̂w − κ·‖w−w_prev‖₁
  s.t.  Σw=1, 0≤w≤w_max(单股≤4%), |B_sec'(w−w_b)|≤ε(行业中性), ‖w−w_prev‖₁≤T_max(换手)
  κ = fee_bps + slippage_bps + 卖出印花税  (与 backtest 同源 bps, A股化)
  ```
- **风险平价 ERC**：`RC_i = w_i·(Σ̂w)_i/√(wᵀΣ̂w)` 对所有 i 相等；凸形式 `min 0.5·wᵀΣ̂w − (1/N)·Σln(w_i)` 坐标下降。
- **HRP**（三步，不求逆）：`d_ij=√(0.5·(1−ρ_ij))` → `scipy.cluster.hierarchy.linkage` → 准对角化 → 递归二分逆方差 `α=1−V₁/(V₁+V₂)`。
- **Black-Litterman（P2，【核验修正：默认关闭 + 依赖件】）**：`Π=λΣ̂w_mkt`；后验 `E[R]=[(τΣ̂)⁻¹+PᵀΩ⁻¹P]⁻¹·[(τΣ̂)⁻¹Π+PᵀΩ⁻¹Q]`，τ≈0.025–0.05。
  - **默认关闭**（`enable_bl=False`）。理由（§14 风险表同步登记）：BL 把 LLM 主观视图灌进 expected return，与"研究型/LLM 永不持最终决策权/证伪机"定位张力大。
  - **Ω 来源是依赖件，未交付前不得引用**：视图置信度→Ω 的映射，依赖 `calibration.py` 提供 **per-view 校准接口**。实测 `calibration.py` 当前只有 `assess()`（可靠性图诊断），**尚无产出 per-view 置信度的接口**。
  - **验收条件（写成 contract）**：BL 仅当 `calibration.per_view_confidence(view)` 落地且其按委员/按因子滚动校准在 §12 测试全绿后，方可置 `enable_bl=True`。在此之前 Ω 引用任何"calibration 校准后可信度"均视为引用未来件，CI 静态检查拦截。τ/Ω 敏感性扫描结果（启用时）强制上 UI。
- **Barra 风险归因**：`Σ=B·F·B'+D`；`wᵀΣw = wᵀBFBᵀw(行业+风格) + wᵀDw(特质)`（行业/风格暴露依赖 §L1 行业映射 + §5.7 风格基底）。
- **容量（平方根律）**：`impact_i ∝ σ_i·√(Q_i/ADV_i)`，仅事后诊断 + 披露 tick 级无数据。

#### 【核验修正】数值稳定性与依赖
- **HRP 为大池默认**（不求逆，最稳）；MVO/BL 仅在可投域收窄到 N≤100 且 T≥2N 时启用，否则不提供 MVO 档并标注原因；BL 还需 `enable_bl=True`（默认否）。
- 回退链补全：首期无 prev_weights → 等权；"放松约束"给确定性序列（行业 ε → 换手上限 → 单股上限），每步写 `fallback_reason`；solver 非 optimal → 拒绝返回权重、回退等权并置 caveat。
- **依赖如实**：`scipy + scikit-learn + cvxpy` 加入 mcp-tool-service/requirements.txt（**非"唯一新依赖 cvxpy"**——scipy/sklearn 实测未装于该容器）；cvxpy 惰性导入，缺失时降级 ERC。**注意**：mcp-tool 的 sklearn 仅用于**无 pickle 的纯数值计算**（LedoitWolf 解析解、HRP 聚类），**不 load/predict 任何跨容器 ML pickle**（§3.3）。

#### 组合层显著性（强制 vs 1/N）
构造组合与 1/N **同日对齐、net-of-cost** 配对日收益 → 差分超额序列 → 块自助（块长 √n）。仅当超额块自助显著为正才标 `beats_1overN=True`，否则 None/False → R13 降级。**forward-PIT 累积达 ≥N 个调仓期前，`beats_1overN` 恒 None**，UI 标注"PIT 历史不足，样本外评估未启动"。

#### MCP 工具（均 **offline**，scheduler 直调落库 portfolios 表）
`build_portfolio` · `risk_parity_weights` · `hrp_weights` · `risk_attribution` · `capacity_check` · `efficient_frontier` · `shrink_cov_report`。委员会只读 realtime 的 `read_portfolio`。

---

### L5/L6 — 风控/择时叠加 与 治理/诚实

#### L5 风控/择时叠加

| 模块 | 职责 |
|---|---|
| `regime_overlay.py` | 融合 vol_state（已实现波动）+ qvix_timing（隐含波动）→ 目标仓位乘子 `scale∈[floor,1]` |
| `qvix_timing.py` | QVIX（`index_option_300etf_qvix`）分位 → 择时区间 level |

**算法**：
```
realized_factor = {low:1.0, normal:1.0, elevated:0.75, extreme:0.5}[vol_state.regime]
implied_factor  = {low:1.0, normal:1.0, elevated:0.75, extreme:0.5}[qvix_level]
target_scale = max(floor, min(realized_factor, implied_factor))   # 取 min=保守优先, 永不>1(只减不加)
```
**【核验修正】**
- **删除期限结构/backwardation 分量**：实测 `index_option_300etf_qvix` 仅返单一 QVIX OHLC 序列、**无近/远月双序列** → `term_structure=None` 固定，绝不用 high/low 伪造。可选改造为跨品种 QVIX 横截面（50/300/500/1000 相对水平）。
- QVIX=**沪深300大盘恐慌代理**，不可当个股/中小盘波动，caveat 明示。
- `scale` **只缩 net-exposure（仓位展示），不参与方向 ceiling 计算**，二者解耦，避免多刹车连乘"诚实到无用"。
- 缩放档位/floor/区间边界做敏感性扫描报告分布（复用 `param_sensitivity`），严禁单点；缩放后并列买入持有 + 块自助显著性。

#### L6 治理/诚实

| 模块 | 职责 |
|---|---|
| `ic_audit.py` | IC 时序自审（ICIR/年化/半衰期/子区间一致性/衰减漂移）→ verdict，纯诊断**不动天花板** |
| `factor_gate.py` | 因子家族 Rank-IC + 块自助 + BH-FDR + Harvey + DSR → status |

**算法**：`half_life`=IC 降到峰值一半的 h；`subperiod_consistency`=前后半段 IC 同号比例；`recent_drift`=mean(近窗) − mean(全窗)。verdict ∈ {有效稳定, 衰减中, 不稳定, 失效, 样本不足}。低频因子（户数季频/解禁）IC 序列设硬样本阈值，不足即 `样本不足`，不输出半衰期数字。

---

### L7 — 前沿 LLM/智能体层（离线 propose-then-prove 证伪机）

**职责**：LLM 只产**公式型(DSL)候选因子**与可审计信息解释；**系统是证伪机**。所有 LLM 路径**离线（scripts/）**，绝不进实时热路径，LLM 永不持最终决策权（对齐 Alpha Illusion 六阶段）。

#### 组件
`scripts/mine_llm_factors.py`（AlphaAgent/MCTS-lite 编排）· `alpha_eval.py`（五维无回测初筛）· `agents.py`（四角色：因子研究员/组合经理/风控官/证伪官）。`mine_llm_factors` 是 **offline** 工具，绝不进委员会 SSE。

#### 闯关流水线（任一关失败即弃权）
```
LLM 在受限 DSL 生成公式候选 (操作数=价量+4另类; 算子=ts/rank/corr/std/delay)
  → 闸门1 alpha_eval 五维 (PPS/RRE/PFS/DH/财务逻辑) 无回测初筛
  → 闸门2 原创性正则 (ast_distance + |corr|>0.7 + 共享高频子树 FSA 拒)
  → 闸门3 panel_cv 真·purged+embargo(+CPCV/PBO) 且优于「价量+估值+A股风格基底」线性基线
  → 闸门4 factor_eval Rank-IC/ICIR + IC 块自助显著 + 分层单调 + long-only top 超额 net (计成本+买入持有对照)
  → 闸门5 multi_test BH-FDR + Harvey t≥3.0 + DSR(N 与 Var(SR_trials) 同源)
  → 全过 → 落库 (公式+全套统计证据+元数据); 否则写弃权理由
严格 cutoff 后样本外: cutoff = max(LLM供应商训练截止保守估计, 项目固定保守日)
```
（闸门3 基线已去 "FF" 字样，改用本系统已交付的 §5.7 A股风格基底，消除空指针。）

#### AlphaEval 五维公式
- `PPS = 0.5·IC + 0.5·RankIC`
- `PFS = min{ Spearman(rank(f), rank(f+ε_gauss)), Spearman(rank(f), rank(f+ε_t(ν=3))) }`，ε_gauss σ=日均波动
- `DH = −Σpᵢlogpᵢ/log m`，`pᵢ=λᵢ/Σλ`（因子库协方差特征值归一化熵）
- `RRE` 相对秩熵（稳定性/反换手）；financial_logic（LLM 50–100，**仅展示不抬升治理**）

#### DSL 安全
算子白名单 + AST 校验，严禁 eval/任意代码与隐含未来函数算子（居中/全样本统计）。

---

## 5. 完整因子目录表

> PIT 状态：`history_native`=自带多年历史立即可回测 · `forward_pit_only`=启动累积/无修订链 · `lagged_legal_deadline`=回退法定截止日滞后 · `lagged_disclosed`=用真预告/快报披露日 · `risk_gate`=风险闸非alpha。所有 forward_pit_only/lagged 因子初期 `history_depth_days<252` 时强制弃权。
> **历史深度不再泛标"多年"**：估值因子按百度 `period` 实拉深度落地；财务/另类按累积。

### 5.1 价量因子（history_native，立即可回测）

| 因子 | 公式 | 方向 | 数据源 | PIT | 历史深度 |
|---|---|---|---|---|---|
| 动量 Mom_{12-1} | `Ref(C,21)/Ref(C,252)−1` | + | get_kline | history_native | K线全历史 |
| 短期反转 Rev_5 | `−(C/Ref(C,5)−1)` | + | get_kline | history_native | K线全历史 |
| 特异波动 IdioVol | `Std(resid of r_i~α+β·r_mkt, 60)` | − | get_kline + 指数 | history_native | K线全历史 |
| 总波动 TotalVol | `Std(Δln C, 20)` | − | get_kline | history_native | K线全历史 |
| Amihud 非流动性 | `mean(|ret_d|/成交额_d, 21)` | + | get_kline | history_native | K线全历史 |
| 规模 Size | `ln(总市值)` | − | spot_em / 百度估值(总市值) | forward_pit_only(快照) | 见 §5.3 period |
| 换手 Turnover | `mean(换手率, 21)` | − | spot_em | forward_pit_only | 累积 |

### 5.2 估值因子接口真实形态说明（【核验修正】先读）

`stock_zh_valuation_baidu(symbol, indicator, period)` **每次仅返回单一指标（PE 或 PB 或 PS 或总市值）、仅 `date`+`value` 单列**；`period='近一年'` 实测仅 ~366 行，**长历史须显式传 `period∈{近三年/近五年/近十年/全部}`，"多年"不是默认**。因此：

- **每估值因子 = `symbol × indicator × period` 笛卡尔调用**；覆盖 EP/BP/SP/DY 需 **4+ 次/标的**调用。M0 PoC 须据此预算限流。
- `factor_meta` 落 `baidu_indicator`（如 `市盈率(动)`）、`baidu_period`（实际 period）、`history_depth_days`（=该 period 实拉行数，**非"多年"**）、`compute_path`（`baidu_snapshot` 或 `report_kline`）。

### 5.3 估值因子（双路径 + 分离 PIT 语义）

> **【核验修正：同一因子只挂一条路径、一种 PIT 标，禁止 A/B 混用】**
> - **路径 A（默认）= 百度估值快照**：`forward_pit_only`（无 vintage/无修订链，是 forward 快照，**不是**按法定截止日对齐 → **绝不标 lagged_legal_deadline**）。分子（净利润/净资产/营收）隐含当时市场已知最新财报，分母（总市值）为当日价，整体是 forward 快照。
> - **路径 B（可选升级）= 财报字段 + K 线自算**：分子按可见日（min(法定截止日, 真披露日)）对齐 → 才用 `lagged_disclosed`/`lagged_legal_deadline`。

| 因子 | 路径A 公式(默认) | 路径B 公式(可选) | 方向 | 数据源 | 路径A PIT | 路径B PIT | 历史深度 |
|---|---|---|---|---|---|---|---|
| EP（盈利市值比） | `1 / 市盈率(动)` | `净利润TTM/总市值` | + | A: baidu(市盈率(动),period) · B: 财报+K线 | **forward_pit_only** | lagged_disclosed | =baidu period 实拉 |
| BP | `1 / 市净率` | `净资产/总市值` | + | A: baidu(市净率,period) · B: 财报+K线 | **forward_pit_only** | lagged_disclosed | =baidu period 实拉 |
| SP | `1 / 市销率` | `营收/总市值` | + | A: baidu(市销率,period) · B: 财报+K线 | **forward_pit_only** | lagged_disclosed | =baidu period 实拉 |
| DY 股息率 | `股息率指标`(若无→弃权) | `每股股息/股价` | + | A: baidu(若提供) · B: 财报派息+K线 | forward_pit_only | lagged_disclosed | 视来源 |

> **【核验修正】** 决策书指定的 `stock_a_indicator_lg` 在 akshare 1.18.64 **实测不存在**；估值因子改用 `stock_zh_valuation_baidu`（单指标×period 笛卡尔，路径A）+ 可选财报自算（路径B）。**默认全系统走路径 A，PIT 一律 `forward_pit_only`**；路径 B 为待 PIT 成熟度门后评估的严谨升级。

### 5.4 质量因子（可见日 = min(法定截止日, 真披露日)）

| 因子 | 公式 | 方向 | 数据源 | PIT |
|---|---|---|---|---|
| ROE | `净利润/净资产` | + | stock_financial_analysis_indicator (+yjyg/yjkb 披露日) | lagged_disclosed / 回退 lagged_legal_deadline |
| 毛利率 GrossProfitability | `(营收−营业成本)/总资产`（Novy-Marx） | + | stock_financial_analysis_indicator | lagged_disclosed / 回退 lagged_legal_deadline |
| 应计 Accruals | `(ΔNWC−折旧)/总资产` | − | stock_financial_analysis_indicator | lagged_disclosed / 回退 lagged_legal_deadline |

### 5.5 另类 alpha 因子（forward_pit_only，初期弃权）

| 因子 | 公式 | 方向 | 数据源 | PIT | caveat |
|---|---|---|---|---|---|
| 北向 NorthboundFlow | `hold_ratio_t − Ref(hold_ratio,20)` | + | **stock_hsgt_individual_detail_em**(symbol,start,end) | forward_pit_only | 2024-08 口径变更点 regime_break，跨期差分弃权；周/双周衰减快 |
| EPS-revision | `(EPS_t−Ref(EPS,1m))/|Ref(EPS,3m均值)|` **未缩放** | + | stock_profit_forecast_em | forward_pit_only | 除当期EPS/股价会失效(Jung 2019)；尾部覆盖稀疏→弃权 |
| PEAD-SUE | `(预告净利中值−一致预期)/历史净利std`，t0=真预告日 | + | stock_yjyg_em / stock_yjkb_em | forward_pit_only(事件) | 事件稀疏，样本不足→弃权 |
| 股东户数 Chip | `−Δln(户数)` | + | **stock_zh_a_gdhs_detail_em**(symbol) | forward_pit_only(季) | 低频，块自助样本少→弃权 |

### 5.6 资金流 / 风险闸

| 因子 | 方向 | 数据源 | 处置 |
|---|---|---|---|
| 主力资金流 main_fund_flow | + | stock_individual_fund_flow | **默认 abstain**：东财订单分类黑箱、不可复算、学术预测力弱 |
| 股权质押（risk_gate） | risk_gate | stock_gpzy_pledge_ratio_em | governance R10 降置信度天花板/弃权（>50%高危） |
| 限售解禁（risk_gate） | risk_gate | stock_restricted_release_queue_em | governance R10/L4 可投性约束降权 |

### 5.7 A股风格因子基底（【核验修正：交付"控制已知因子"的可计算基底】）

> 用于 L3/L7 闸门"控制已知风格后仍有增量 IC"的**残差化底座**，以及 Barra 风格暴露。优先 Liu-Stambaugh-Yuan(2019) 三因子（MKT/SMB/VMG），均在 `lsy_filter=on`（剔最小30%）样本上构造（LSY 原意）。**有了本表，闸门基线不再出现"FF"空指针。**

| 风格基底 | 构造（每调仓期截面，剔最小30%市值后） | 数据源 | PIT | 构造周期 |
|---|---|---|---|---|
| MKT（市场） | universe 市值加权超额收益 `R_mkt − R_f`（R_f 取固定短端近似，标 caveat） | get_kline + universe | history_native（价量） | 调仓频 |
| SMB（规模） | 小市值组 − 大市值组（按 ln 市值中位分组，2×3 或中位二分） | 百度估值(总市值)/spot + get_kline | forward_pit_only（市值快照） | 调仓频 |
| VMG（价值−成长, LSY） | 高 EP 组 − 低 EP 组（EP 用 §5.3 默认路径A `1/PE`，剔小票） | baidu(市盈率) + get_kline | forward_pit_only（随 EP 路径A） | 调仓频 |

构造说明：采用 LSY 的 2×3（size × value）独立分组、组内市值加权、做多高、做空低的腿差作为风格收益序列；**风格收益序列本身仅用于残差化与风险归因**，其做空腿是统计构造、不进可实现组合。残差化：候选因子对 [MKT, SMB, VMG] 时序回归取残差，残差 IC 仍显著为正才算"控制已知因子后有增量"。**SMB/VMG 因依赖市值快照与 EP 路径A → `forward_pit_only`，冷启动期 history_depth<252 时风格基底本身弃权 → 该期"增量 IC"判据无法计算 → 候选因子相应 abstain（不放行）**，诚实优先。

---

## 6. 因子评估方法学

四项**联合**判定，任一失败即降级/弃权：

1. **预测力**：Rank-IC（主指标，抗厚尾/涨跌停）+ ICIR + IC>0 占比 + HAC-t / 块自助 p 值。**双口径报告**：`universe_filter='all'`（全样本）与 `'lsy'`（剔最小30%市值+次新/ST/壳）**分别**报 IC/分层，防小市值污染高估反转/另类因子 IC（LSY 2019）。**未在 lsy 口径报告的因子，不得引 LSY 作背书。**
2. **单调性**：分层 Q1–Q5/Q10 各层下期收益单调（`Spearman(层序号, μ_q)≈±1`）；非单调暴露"只在尾部有效"的假因子。
3. **可持有性**：换手率 + factor_rank_autocorr（越高越省成本）+ IC 半衰期（指导调仓频率）。高换手 × 短半衰期 → 成本吞噬 → 降级。
4. **稳健性**：purged-CV OOS + **设计选择网格多路径分布（单因子层也跑，非单点）** + ML 层 CPCV/PBO；网格 = 窗口/加权/微盘过滤(lsy)/horizon/分层N/中性化变体/调仓频率/成本。

**多重检验纪律**：全家桶 ~20+ 因子 Rank-IC p 值统一 **BH-FDR**；新另类因子 **Harvey t≥3.0**；"最佳"用 **Deflated Sharpe** 扣试验次数 N（保守 N 计入设计自由度；**N 与 Var(SR_trials) 同源于设计网格**，见 §7）。

**verdict 链（【核验修正：全面 long-only，去 LS 净额作通过条件】）**：
```
IC 显著(HAC∧块自助) ∧ 分层单调
  ∧ long-only top 分位组合(扣成本) 相对 买入持有/1N 的超额块自助显著
  ∧ 换手不吞噬 ∧ 过 BH-FDR
  ∧ OOS 优于「价量+估值+A股风格基底」线性基线
  ∧ (剔小票 lsy 口径与全样本口径结论不冲突, 否则降级并标 small_cap_driven)
  →  通过
LS 净额(含空头腿) 仅作 _research_only 诊断展示, 绝不作通过条件
任一失败 / 样本不足 / forward_pit_only 深度<252 / 风格基底未成熟  →  降级 / 弃权(significant=None)
```

---

## 7. 因子合成与诚实闸门 + DSR 口径定义

### 7.1 合成闸门（默认线性基线）

**默认线性基线**（等权 / IC 加权），ML 只在 promote-then-prove 通过时接管：

```
gate = (ΔRankIC 块自助 CI 下界 > 0)            # OOS 严格优于「价量+估值+A股风格基底」线性基线
     ∧ (long-only top 分位超额 net 块自助显著)  # 去 LS 净额
     ∧ (通过 BH 因子闸)
     ∧ (控制 A股风格基底 MKT/SMB/VMG 后增量 IC > 0)   # 残差化后才采纳, 防换皮; 基底见 §5.7
enable_ML if gate else abstain → 回退线性基线
```

ML 配置：浅层 GBDT（max_depth 3–6，强正则，early stopping）；输出 SHAP/feature_importance + 每因子一句经济逻辑（Bagnara：预测精度≠风险溢价故事）；当分类 head 时用 `CalibratedClassifierCV(method='sigmoid')` + Brier/ECE 评估，**不在测试集校准**。`abstain_reason` 区分 4 类（data_missing / model_load_failed / insufficient_history / statistical_abstain）。**训练与推理同 py3.12 / agent-service（§3.3 契约）；工件带 artifact_meta，加载校验不过即 model_load_failed**。

### 7.2 【核验修正】DSR 的 Var(SR_trials) 与 n_trials 口径（消除"单点套需分布的公式"矛盾）

DSR 公式中 `SR0` 需要"试验夏普的方差" `Var(SR_trials)`，而多数因子默认只跑单路径——若无分布则无法估方差。本系统**强制 N 与 Var(SR_trials) 同源**：

- **唯一权威来源 = 设计选择网格**：对每个因子，§4/§6 定义的设计网格（horizon × 分层N × 中性化变体 × 调仓频率 × universe_filter）天然产生**一组**试验夏普 `{SR_1,…,SR_M}`。
  - `N = 因子数 × 网格点数 M`（与"全家桶规模 × 自由度"一致）。
  - `Var(SR_trials) = sample_var({SR_1,…,SR_M})`（**与 N 同源于同一组网格**，不另起炉灶）。
- **网格退化为单点时的解析回退**：若某因子确无网格（M=1），用解析近似 `Var(SR_trials) ≈ 1/T`（López de Prado 单试验近似），返回体标 `var_source='analytic_1overT'`，并把该因子的 `n_trials` 同步取保守家族级 N（不允许 N 大而 Var 取单点 0）。
- **自洽性约束（CI 断言）**：`var_source ∈ {grid_distribution, analytic_1overT}`；当 `var_source='grid_distribution'` 时必须满足 `n_trials ≥ M` 且 `M = len(grid_SR)`；当 `M=1` 时 `var_source` 必为 `analytic_1overT`。`test_multi_test` 用 López de Prado 公开参考数值对拍并固定此口径（CI gate）。
- 输出乐观（仅价量自由度）与保守（计入全网格自由度）两个 DSR，**以保守者为治理判据**；N=1 退化为 PSR 单独断言。

---

## 8. 组合构建与风险模型

### 8.1 默认管线
```
L3 打分 μ (或 None)
  → select_universe: 时点可投域清洗 (剔停牌/ST/一字板/PIT外/解禁高峰; 可选 lsy_filter; 判定见下)
  → top 分位/N 候选 (仅多头)
  → shrink_cov: LedoitWolf(EWMA λ=0.94) → Σ̂ + δ + 条件数
  → 权重引擎: μ 有效 ∧ N≤100 ∧ T≥2N → MVO/(BL 仅 enable_bl=True); 否则 → HRP/ERC (默认稳健档)
  → cvxpy 约束: 单股≤4% / 行业中性±ε / 换手≤T_max / 做多 / 成本 κ; infeasible → 确定性回退链
  → 复盘: 组合 net 日收益 vs 1/N 配对差分 → 块自助 → beats_1overN
  → 容量诊断 + Barra 风险归因 → 落 portfolios 表 (委员会只读 read_portfolio)
```

### 8.2 可投性过滤数据源（核验补全）
停牌：spot 接口成交额=0/换手=0；ST：名称含 ST；涨跌停：当日 |涨跌幅| 触及 ±10%/±20%/±5%（主板/创业科创/ST）。无法判定 → 标 `unknown` 并保守剔除。LSY 档（可选）再叠剔最小30%市值+次新+壳。

### 8.3 公式（见 §4 L4，此处不赘）
LW 收缩 / MVO QP / ERC 对数障碍 / HRP 三步 / BL 后验（默认关）/ Barra Σ=BFB'+D / 平方根冲击。

---

## 9. 治理与诚实披露

### 9.1 现有 R1–R8（confirmed：govern() 内）+ R9（committee 层质询）

`govern(members, data_status, ml, backtest_stable, vol_regime)`：R1 无证据 / R2 数据状态 / R3 连续分歧 / R4 ML弃权 / R5 回测 / R6 仅情绪 / R7 ML高波动 / R8 已实现波动。R9 交叉质询在 committee.py 以 note 形式追加。

### 9.2 新增因子/组合治理规则（核验对齐：扩展签名，非"延 R9"）

`govern(..., factor_flags=None, regime_scale=None, capacity_flag=None)`，新增分支作用于**因子证据**（非方向票）：

| 规则 | 触发 | 动作 | 相位 |
|---|---|---|---|
| **R10** | 因子 pit_status ∈ {forward_pit_only, lagged_fixed, lagged_legal_deadline} 或 history_depth<252 或 risk_gate 触发 | 封顶该证据贡献/置信度；风险闸只降权 | 证据级，**算 ceiling 之前** |
| **R11** | 因子 IC 衰减(ic_audit verdict ∈ {衰减中,失效}) 或协方差条件数过大/δ 过高/optimizer infeasible | 标注估计不可靠、封顶；回退风险平价 | 证据级 + 组合级 |
| **R12** | 因子未过 BH-FDR / ICIR<阈值 / 与已选因子 \|corr\|>0.7 / 控制风格基底后增量IC≤0 / LLM 证据缺元数据(来源/cutoff/样本外IC/PIT) / factor_eval staleness 超阈 | 排除/降级；缺元数据视同无效 | 证据级，**算 ceiling 之前** |
| **R13** | 组合样本外未跑赢 1/N（含 beats_1overN=None） / 容量不可投 | 降级为"仅展示 ERC 风险均衡、不主张 alpha"；标研究型不可实盘 | 组合级独立审计行 |

**执行 DAG（防自相矛盾治理态）**：`R12(剔无效证据) → R11(封顶非PIT/不可靠) → R1/R6(无据/仅情绪降级) → R10(因子降权) → 算冲突/disagreement/ceiling/allowed_verdicts → R13(组合级)`。

### 9.3 诚实披露面板
每因子卡：数据源 / PIT状态 / 历史深度（实拉 period/累积，非"多年"）/ 覆盖率 / 幸存者偏差 / IC衰减曲线 / DSR(乐观+保守) / backtestable_from / 双口径(all vs lsy) IC。每组合：协方差方法+δ / 是否跑赢1/N / 容量是否受限 / BL 默认关闭说明（启用时 τ/Ω 假设）/ "研究型不实盘"。**因子证据永不抬升置信度天花板**（对齐 seasonality）。

### 9.4 R10–R13 校准（防"诚实到无用"）
各规则只在专属维度收紧，避免对同一不确定性重复罚分（R8 已封波动，R12 regime_scale 只缩 net-exposure 不再二次压 ceiling）。review 回流监控弃权率/平均 net-exposure，设弃权率告警阈值。

---

## 10. 智能体角色与编排 + 完整 MCP 工具目录

### 10.1 委员会角色（confirmed：committee.LENSES + _member + _ml_member 脚手架）

| 角色 | 类型 | 读取 | 证据 type | 约束 |
|---|---|---|---|---|
| 基本面/技术面/情绪面/风险面（现有4） | LLM | data_blob | fact/opinion/inference | R1/R6/R9 |
| ML 波动票（现有） | model | ml_signal（py3.12 同栈） | model（非方向） | R4/R7 |
| **量化因子面分析师**（新增） | stat | **storage.factor_eval 落库 + §10.3 个股映射** | stat | R1/R10/R12；无记录或 staleness 超阈则 abstain |
| **另类数据分析师**（新增） | stat | 北向/资金面 read_factor_eval | stat | R10；只降权 |
| **盈利修正分析师**（新增） | stat | EPS-revision/PEAD read_factor_eval | stat | R10/R12 |
| **证伪官**（新增） | stat | reverse_evidence_test（P3 翻转率）+ 共线性 | stat | 找反例，不升 ceiling |

**编排时序**：`finance_agent.deep → run_committee → _member(并行) + _ml_member + 新角色(读离线产物) → _reverify_evidence_types → _cross_examine(R9) → govern(R1–R8 + R10–R13) → 主席 clamp confidence 到 ceiling, 方向落 allowed_verdicts → storage.analysis → calibration 回流`。

**【核验修正】** 因子委员 lens 命名含可识别标记（或 db._by_member 改按 evidence type 判方向票），避免恒中性/stat 票污染 `_by_member` 方向命中统计（confirmed：db.py:54 用 `'风险信号' in lens` 排除）。

### 10.2 完整 MCP 工具目录（签名 + realtime|offline 标注）

> **【核验修正】** 每个工具标 `realtime`（轻量只读，委员会 SSE 可直调）或 `offline`（重计算，仅 scheduler 直调落库，**委员会调用即拒**）。offline 工具即便注册到 FastMCP，也用 `anyio.to_thread.run_sync` 卸载或独立进程，避免阻塞事件循环。

**L0 数据 — 全 realtime**
```python
get_universe(date: str, lsy_filter: str='off') -> dict                       # realtime
get_panel(date: str, fields: list[str]) -> dict                             # realtime
asof_value(symbol: str, field: str, date: str,
           indicator: str=None, period: str=None) -> dict                   # realtime; 补 indicator/period 维(百度估值)
data_coverage_report(date: str = None) -> dict                              # realtime; 含 backtestable_from
list_factor_meta() -> list                                                  # realtime
read_factor_eval(factor_name: str, as_of: str=None,
                 universe_filter: str='lsy') -> dict                        # realtime; 读 L2 落库
read_portfolio(portfolio_id: str, as_of: str=None) -> dict                 # realtime; 读 L4 落库
pit_data_health() -> dict                                                   # realtime
```
**L1 因子 — 全 realtime（纯函数）**
```python
build_factor_panel(universe, as_of, factors) -> dict                        # realtime(增量) / offline(全量)
compute_factor(symbol, factor_name, as_of=None) -> dict                     # realtime
preprocess_cross_section(values, industries, ln_mktcap, method='mad') -> dict  # realtime
factor_metadata(factor_name=None) -> dict                                   # realtime
altfactor(symbol, kind, as_of=None) -> dict   # kind=main_fund_flow→永远 abstain  # realtime
```
**L2 评估 — 全 offline（scheduler 直调落 factor_eval；委员会只用 read_factor_eval）**
```python
factor_report(factor_name, universe, as_of, horizon=20, n_quantiles=5,
              universe_filter='all') -> dict                                # offline
factor_family_gate(factor_names, as_of=None) -> dict   # BH-FDR+Harvey+DSR  # offline
evaluate_factor_cv(factor_name, model=None, embargo=5, n_paths=10) -> dict  # offline
deflated_sharpe(sr, n_trials, var_sr_trials=None, var_source='auto',
                skew=0, kurt=3, n_obs=252) -> dict                          # offline(批) ; 口径见 §7.2
evaluate_factor(factor_values, forward_returns, factor_library=None) -> dict  # offline; AlphaEval 五维
```
**L3 合成**
```python
combine_factors(panel, method='ic_weighted', rolling_ic=None) -> dict       # realtime(纯线性, mcp-tool)
xsec_rank(panel, labels, date_groups, baseline_scores) -> dict              # 推理转发 agent-service(py3.12) 或返回线性基线; §3.3
```
**L4 组合 — 全 offline（scheduler 直调落 portfolios；委员会只用 read_portfolio）**
```python
build_portfolio(symbols, signal_scores, method='hrp', constraints=None,
                prev_weights=None, capital=None, enable_bl=False) -> dict   # offline; BL 默认关
risk_parity_weights(symbols, returns_panel=None) -> dict                    # offline
hrp_weights(symbols, returns_panel=None) -> dict                            # offline
risk_attribution(weights, exposures) -> dict                               # offline
capacity_check(weights, capital, adv) -> dict                              # offline
efficient_frontier(symbols, signal_scores, n_points=20) -> dict            # offline(CPU 密集)
shrink_cov_report(symbols, returns_panel=None, method='lw') -> dict        # offline
```
**L5/L6 风控治理**
```python
get_qvix_timing(window=250) -> dict                                        # realtime
get_regime_overlay(symbol, floor=0.5) -> dict                              # realtime
factor_health_report(factors, alpha=0.05) -> dict                         # offline
ic_self_audit(ic_series, horizons=5, annualize_periods=12) -> dict        # realtime(传入序列即算)
```
**L7 LLM 证伪（含离线/委员辅助）**
```python
propose_factor(formula, panel_ref) -> dict                                # offline
check_factor_originality(formula, library) -> dict                        # realtime(轻量 AST)
purged_cv_panel(X, y, dates, horizon, embargo=5, cpcv_groups=0) -> dict   # offline(CPU 密集)
risk_gate(symbol) -> dict                                                  # realtime
reverse_evidence_test(member_conclusion, counter_evidence) -> dict        # realtime(委员辅助)
mine_llm_factors(...) -> dict                                             # offline; 绝不进委员会 SSE
```

> 工具约定：async、出错抛出 → FastMCP 置 `isError=True`；返回带 `data_quality`/`pit_status`/`caveat`/`disclaimer`/`execution_mode` 结构化字段；复用 obs.TTLCache 缓存（键按 as_of 隔离）+ METRICS 计量。**委员会侧硬拒 `execution_mode='offline'` 工具**（返回 `error='offline_tool_not_callable_in_committee'`）。

### 10.3 【核验修正】因子级证据 → 个股级证据映射规则（消除语义鸿沟，防"横截面排名当 alpha 故事"）

L2 产出是**因子级** IC/family verdict，委员会是 **per-symbol** 研判。量化因子面分析师**不得**直接把"该股在该因子上的横截面分位"当方向票。映射规则（**三条同时成立才产 stat 证据，否则 abstain**）：

```
对个股 s 在因子 f 上产 stat 方向证据  iff
  (1) 因子 family 通过 L2 闸门 (read_factor_eval.family_verdict='有效稳定' AND significant=1)
  AND (2) 个股 s 处于因子 f 的横截面极端分位 (top/bottom 分位, 阈值可配)
  AND (3) 控制 A股风格基底(MKT/SMB/VMG)后, s 在残差因子上仍处极端分位 (剔除"只是小盘/价值暴露"的伪证据)
方向 = 因子 direction × (s 在 top→看多 / bottom→看空, 但空头仅 _research_only 不进可实现方向)
证据强度上限受 R10 封顶 (forward_pit_only/深度不足 → 封顶或 abstain)
任一条不成立 / family 弃权 / staleness 超阈 / 当批无记录  →  abstain (区分 reason)
```

- **离线批频率**：见 §L2（周频 + 月度全量；低频因子随数据更新触发）。
- **staleness 阈值**：`now − factor_eval.computed_at > 10 交易日` → abstain（`insufficient_history`）。
- **schema**：见 §L0 `factor_eval` 表（含 family/family_verdict/significant/universe_filter/网格坐标/residual_incremental_ic/computed_at），委员经 realtime `read_factor_eval` 读取，按上式三条判定。
- **诚实约束**：该映射**永不抬升置信度天花板**，只作 stat 证据进入冲突/共识统计；证伪官对其做反例检查。

---

## 11. 微服务改动清单

### storage-service
- **新增**（db.py）：7 张 PIT 相关表（panel_daily / fundamentals_pit / index_membership / events / factor_meta / **factor_eval** / **portfolios**）；`asof()` / `universe(date, lsy_filter)` / `panel_asof_matrix()` 查询；启用 WAL + busy_timeout。
- **新增**（app.py）：`POST/GET /pit/*` 端点 + `GET /pit/factor_eval` + `GET /pit/portfolio`（委员会 realtime 只读）。
- **修改**：`_by_member` 增 non_directional 显式排除（避免 stat 票污染方向命中）。

### ingestion-service
- **新增**：`akfetch.py`（cross_section/per_symbol 双粒度采集；百度估值按 indicator×period 笛卡尔调用 + 限流预算）、`pit_snapshot.py`（5 job：snapshot_panel/snapshot_events/snapshot_quarterly/snapshot_disclosure(yjyg/yjkb 真披露日)/universe_rebuild，错峰或串行避免并发写）、`calendar.py`（交易日历落地缓存）、行业映射采集（stock_board_industry_name_em + stock_individual_info_em）。
- **修改**（scheduler.py）：注册 PIT 快照 job + **L2/L4 offline 重计算 job**（factor_eval 周频/月度全量、portfolios 周频），复用 per-symbol try/except 失败隔离 + 计数器；**offline 重计算 job 直调 mcp-tool offline 工具或本地纯函数，结果落库，不经委员会 SSE**。

### mcp-tool-service
- **新增**：`factors/`（dsl.py / zoo.py / preprocess.py / eval.py / altfactors.py / panel_cv.py / **industry_map.py** / **style_base.py**(MKT/SMB/VMG)）、`portfolio.py`、`risk_model.py`、`multi_test.py`、`regime_overlay.py`、`qvix_timing.py`、`ic_audit.py`、`factor_gate.py`、`alpha_eval.py`、`pit_panel.py`。
- **修改**（mcp_server.py）：注册上述 MCP 工具，**每工具标 `execution_mode` 元数据**；offline 工具用 `anyio.to_thread.run_sync` 卸载；委员会调用白名单硬拒 offline。
- **修改**（requirements.txt）：**新增 scipy + scikit-learn==1.7.2 + cvxpy(惰性)**（实测当前仅 numpy/pandas/akshare/yfinance）；CI 容器内实测 import 通过。**约束：mcp-tool 的 sklearn 仅用于无 pickle 纯数值计算（LedoitWolf/聚类），不 load/predict 任何跨容器 ML pickle（§3.3）。**
- **复用/重构**：seasonality.py BH 内联 → import `multi_test.bh`（先写逐位相等回归测试）。

### agent-service（py3.12，ML 训练+推理同栈）
- **新增**：`ml_signal.panel_walk_forward` + `train_xsec`（横截面 ranking，**旧 SignalCalibrator 波动校准器完全不动**）；**`xsec_model.py` 推理端点**（L3 树模型推理留本容器，§3.3 方案A）；committee 新增 4 个角色（依赖注入可脱网单测）；`agents.py`（L7 四角色）；`scripts/mine_llm_factors.py` + `scripts/train_xsec_factors.py`（离线）。
- **修改**（governance.py）：扩 `govern()` 签名 + R10–R13；calibration.py 升级为按委员/按因子滚动校准，并**新增 `per_view_confidence()` 接口**（BL Ω 的依赖件，验收前 BL 保持默认关）。
- **新增工件契约**：所有 ML pickle 随 `artifact_meta.json`；加载侧校验环境一致，不一致 → `model_load_failed`。

### api-gateway
- **新增**：`/api/finance/portfolio` 转发（读 portfolios 落库）；finance.html ECharts「因子体检报告（双口径 all/lsy）」+「组合视图」+「仓位刹车/QVIX 择时」+「委员/因子校准」面板；强制并列买入持有 + 块自助显著性 + PIT/幸存者/容量 caveat 卡 + BL 默认关闭说明。

---

## 12. 测试策略（TDD，守住现有全绿基线）

> 沿用 `importlib.util.spec_from_file_location` 脱网加载范式；合成数据、可重复、tmp_path 临时库。**先写测试再写实现**。

### 单元测试（纯函数脱网）
- `test_preprocess`：中性化残差与[**申万一级行业哑变量**,ln市值]正交（corr≈0）；对"纯由行业+ln市值线性构造的假因子"中性化后残差≈0；**逐截面 vs 跨期池化给出不同结果**（防泄漏回归）；winsor_pct 正确；行业映射缺失截面→degraded 弃权。
- `test_factor_dsl`：算子对已知序列出已知值（与 indicators/volatility 交叉校验）；非法公式抛错；AST 白名单拒 eval；cs_rank 只在当日截面内排名。
- `test_style_base`：MKT/SMB/VMG 在合成截面上构造正确（小市值组−大市值组符号正确、剔最小30%生效）；风格基底 history_depth<252 时返回弃权 → 依赖它的增量 IC 判据 abstain。
- `test_factor_eval`：注入 `factor=fwd_return+噪声` → RankIC 显著>0；纯噪声 → IC≈0 且 BH 后 not passed；分层单调；常数序列 → significant=None；**双口径 all/lsy 都产出且小市值驱动因子在 lsy 口径 IC 显著回落 → 标 small_cap_driven**；**long-only top 超额作通过判据、LS 字段仅 _research_only**。
- `test_panel_cv`：构造标签 [t,t+h] 重叠样本 → 断言被 purge（**purge 版 OOS IC 显著低于不 purge 版** = 泄漏被堵）；无信息数据 OOS IC≈0 触发弃权；**单因子设计网格 multiple-path 分布产出（非单点）**；CPCV 路径数=C(N,k)；PBO 在过拟合策略≈1、稳健≈0。
- `test_multi_test`：bh 与 seasonality 原内联 BH **逐位相等**（回归守护）；DSR 随 n_trials↑ 单调下降；**DSR 的 Var(SR_trials) 与 n_trials 同源自洽断言（var_source∈{grid_distribution,analytic_1overT}；grid 时 n_trials≥M=len(grid_SR)；M=1 时强制 analytic_1overT）**；DSR/PSR 对拍 López de Prado 论文数值（CI gate）；N=1 退化 PSR；Harvey t=2.9 拒/3.1 过。
- `test_portfolio`：合成正定 Σ → ERC 风险贡献相等(误差<1e-3)；LW 收缩后正定且 0<δ<1；HRP 权重和=1 非负；约束 MVO 满足全部约束；infeasible 优雅回退且 fallback_reason 非空；beats_1overN 在噪声 μ 上为 None/False；**BL 默认 enable_bl=False 时不调用 calibration.per_view_confidence**。
- `test_regime_overlay`：scale∈[floor,1] 永不>1；两刹车取 min；QVIX unknown 优雅降级；term_structure 固定 None。
- `test_pit_db`：asof 时点可见性（注入 announce_date t-30/t-5 两版 → as_of=t-10 返 t-30 版，t-5 不可见）；**可见日 = min(法定截止日, 真披露日)：注入早于法定日的 yjkb 披露日 → 可见日提前到披露日；无披露日 → 回退法定日**；INSERT OR REPLACE 幂等；ingest_ts 永不入查询；index_membership 含退市名。
- `test_baidu_valuation`（network-marked skip）：`stock_zh_valuation_baidu` 单指标单列形态断言；period='近一年' 行数≈252±、'近五年'更长；EP=1/PE 路径A 落 forward_pit_only；factor_meta 落 baidu_indicator/baidu_period/compute_path。

### 契约 / 跨容器 / 治理 / 集成测试
- **`test_artifact_contract`（【核验修正】§3.3 契约）**：ML pickle 带 artifact_meta；加载侧环境不一致 → model_load_failed（非 statistical_abstain）；**跨容器 pickle round-trip：在 agent-service 容器 dump、在拟接收容器 load+predict，断言预测逐位一致**（不绿则禁止把 pickle 依赖工具拆到异版本容器）。
- **`test_mcp_execution_mode`（【核验修正】§3.4）**：每工具 execution_mode 标注存在；委员会调用 offline 工具被硬拒；offline 工具 docstring/返回标 offline。
- `test_governance` 扩展：R10/R11/R12（含控制风格后增量IC≤0 排除、factor_eval staleness 超阈 abstain、缺元数据视同无效）/R13，**多规则同时触发组合用例**防自相矛盾；**既有 R1–R8 断言保持全绿**（新参数默认 None 向后兼容）。
- `test_committee` 扩展：新角色依赖注入 fake llm/gather_fn 脱网，产 type=stat 证据；**§10.3 个股映射：family 未通过/非极端分位/控制风格后不极端 → abstain；三条齐备才出证据；staleness 超阈 abstain**；stat 票不计入 _by_member 方向命中。
- 接口契约测试 `test_akshare_smoke`（network-marked，默认 skip）：对每个声明接口跑 `getattr + inspect.signature`，stock_a_indicator_lg 缺失即红灯；stock_zh_valuation_baidu 形参含 indicator/period；行业映射接口存在。
- 诚实回归：纯噪声因子全家桶 BH 后 passed 数≈期望假阳性率内；横截面模型在随机标签上 panel-purged-CV 的 OOS IC 不显著（仿 scripts/audit_signal.py + permutation_null）。

---

## 13. 风险与局限（诚实）

| 类别 | 风险 | 缓解/披露 |
|---|---|---|
| **PIT** | akshare 无 vintage/修订链，只能 forward_pit_only；财务无公告日列；北向 2024-08 口径变更 | 可见日=min(法定截止日,真披露日) + regime_breaks 标注；百度估值=forward 快照（绝不标 true_pit/lagged）；防前视回归测试 |
| **估值接口形态** | 百度估值单指标单列、period 决定历史（默认仅一年）、需 4+次/标的笛卡尔调用 | factor_meta 落 baidu_indicator/period；history_depth 按实拉 period；M0 按此预算限流；EP 口径二选一(默认 1/PE) 防漂移 |
| **幸存者** | index_stock_cons_csindex 无 date 参数、仅今日成分；启动前历史不可重建 | universe_pit_status='today_snapshot_only' + 仪表盘前置 caveat；评估 baostock 历史成分回填（P1）；**不声称已消除** |
| **小市值污染** | today_snapshot 段 + 未剔小票 → 系统性高估反转/另类 IC（比幸存者偏差更隐蔽） | LSY lsy_filter（剔最小30%+次新/ST/壳）；IC 双口径(all/lsy)报告；未在 lsy 口径不得引 LSY 背书 |
| **冷启动** | forward_pit_only 因子 history_depth≈0，1-2 年内另类/估值(路径A) 家桶实质不可用 | history_depth_days<252 强制 significant=None + 进度条而非曲线；价量立即可回测；**PIT 成熟度门(§14.2)作客观触发** |
| **里程碑验收幻觉** | PIT 不足时 M5–M7"通过"只在合成/today_snapshot 污染数据上做，非真 OOS | **两段式验收（§14.1）**：管线正确性在合成数据全绿（≠alpha 证据）+ 真实有效性待 PIT 成熟度门复核 |
| **过拟合** | 因子搜索/超参/设计选择构成多重试验，Lalwani 非标准误差达 5×；单因子也有 horizon/窗口挑选 | BH-FDR + Harvey + 保守 DSR(N 与 Var(SR_trials) 同源于网格) + **单因子层设计网格多路径** + ML 层 CPCV/PBO + 报告分布非单点 |
| **ML 工件跨端** | agent(3.12) vs mcp-tool(3.11) pickle 不保证兼容（曾踩坑） | **训练+推理同 py3.12/agent-service（§3.3 方案A）**；artifact_meta 契约 + 跨容器 round-trip CI；mcp-tool 不碰 ML pickle |
| **BL 主观视图张力** | BL 把 LLM 主观视图灌进 expected return，与"证伪机/不主张 alpha"定位张力大；Ω 依赖未落地的 per-view 校准 | **BL 默认关闭(enable_bl=False)**；Ω 来源为依赖件，calibration.per_view_confidence 落地+测试全绿前不得引用 |
| **行业分类 PIT** | 申万行业归属随时间变更，akshare 无历史归属 | 行业映射 forward 累积 + today_snapshot_only caveat；中性化/Barra 行业暴露以此为前置，覆盖率不足截面弃权 |
| **容量** | 给小盘大权重实盘买不进；tick 级冲击无数据 | 平方根律事后诊断 + capacity_check 标不可投 + "研究型不可实盘" |
| **数据可靠性** | 另类/QVIX 多为单源爬虫，限流/改名/字段漂移（stock_a_indicator_lg 已失效即先例） | 适配器隔离 + TTL + 失败隔离 + Metrics 熔断雏形 + 防御解析；coverage 归零→弃权 |
| **A股摩擦** | 融券受限/涨跌停/停牌/T+1 | **多空降为纯诊断、判据全面 long-only top 超额**；可投性过滤；卖出印花税入成本；明示未完全建模 |
| **架构错配** | per-symbol 时序栈 vs 横截面面板；重计算阻塞 SSE | 横截面诊断离线批，委员只读落库；**MCP realtime/offline 切分（§3.4）**；先建 L0 PIT 面板再接委员会 |
| **数据缺口** | 无 Wind/聚宽 PIT 库、无 tick、无机构持仓明细 | 列为已知差距，随每因子免责披露 |

**总诚实立场**：本系统不承诺跑赢市场。多数因子可能弃权或跑不赢 1/N——这被做成显式诚实视图（引 StockBench/Agent Arena 佐证），是 trustworthy 差异化卖点而非缺陷。

---

## 14. 实现路线图（有序里程碑）

> 每里程碑独立 TDD 全绿、可演示、可回退。先窄后宽。

### 14.1 里程碑表（【核验修正：M5–M7 两段式验收】）

| 里程碑 | 内容 | 验收 |
|---|---|---|
| **M0 接口实测固化** | `scripts/akshare_smoke.py` 跑通全部接口签名（含百度估值 indicator×period 笛卡尔预算）；修正纸面接口；5–10 只标的端到端采集 PoC | smoke 全绿；接口签名/历史深度/baidu_indicator/period 入 factor_meta；EP 口径二选一确认 |
| **M1 L0 PIT 数据层** | storage 7 表 + asof/universe(lsy) + WAL；ingestion akfetch 双粒度 + 5 快照 job(含真披露日) + 交易日历缓存 + 行业映射；pit_panel realtime MCP | 防前视回归测试通过；可见日=min(法定,披露日)选对版本；含退市名；行业映射覆盖率达标 |
| **M2 L1+L2 核心（纯算法）** | factor_dsl + preprocess(申万中性化) + style_base(MKT/SMB/VMG) + 5–6 个 GKX 强因子；multi_test 抽取(回归守护)；factor_eval 双口径 + panel_cv 单因子多路径 | 中性化正交；逐截面无泄漏；BH 逐位相等；DSR Var/N 同源自洽对拍；双口径 IC 落库 |
| **M3 L4 稳健档** | portfolio.py 仅 HRP/ERC + LW + 与 1/N 对照；依赖补齐(scipy/sklearn/cvxpy)；offline 落 portfolios | ERC 风险贡献相等；beats_1overN 噪声→None；execution_mode=offline 不进 SSE |
| **M4 L3 横截面 ML** | ml_signal.panel_walk_forward + train_xsec(promote-then-prove, py3.12 同栈)；artifact 契约 + 跨容器 round-trip；scripts 离线训练 | purge 版 OOS IC<不purge 版；不优于风格基底基线→abstain；工件契约绿；round-trip 逐位一致 |
| **M5 另类 + MVO + L5/L6（BL 默认关）** | altfactors(forward-PIT 起采)+ MVO 收窄池 + regime_overlay/qvix + factor_gate + governance R10–R13 | **管线段**：治理多规则组合测试全绿、冷启动弃权、R1–R8 不回归（合成数据，**不构成 alpha 证据**）。**有效性段**：标 PENDING，待 PIT 成熟度门 |
| **M6 委员会 + 仪表盘** | 4 个新委员(read_factor_eval + §10.3 个股映射)+ 证伪官；ECharts 因子体检(双口径)/组合视图/校准面板 | **管线段**：脱网单测全绿、§10.3 三条映射逻辑、staleness/abstain 正确、强制并列买入持有。**有效性段**：PENDING（PIT 门） |
| **M7 L7 LLM 证伪（可选）** | mine_llm_factors 离线闯关流水线(基线=风格基底, 无FF)+ 原创性正则 + cutoff 纪律 | **管线段**：噪声因子全链弃权、cutoff 后样本外断言、offline 不进 SSE。**有效性段**：PENDING（PIT 门） |

> **两段式验收定义**：每个 M5–M7 里程碑拆为
> - **管线正确性段（可立即验收）**：防泄漏/弃权逻辑/治理触发/映射规则在**合成数据**上全绿。**明确标注：此段通过不构成任何 alpha 证据。**
> - **真实数据有效性段（延期验收）**：标 `PENDING(PIT-maturity)`，只有 PIT 成熟度门（§14.2）触发后，用真实累积的 OOS 数据复核才可声称有效。

### 14.2 【核验修正】PIT 成熟度门（另类/forward_pit_only 因子从弃权转可评估的客观触发条件）

```
PIT 成熟度门 OPEN(因子族 F)  iff
  (1) forward 累积的 visible 历史深度 ≥ N_min 个调仓期 (默认 N_min=24 个月频期/或 ≥504 交易日)
  AND (2) 该族每因子 factor_eval.history_depth_days ≥ 252
  AND (3) 依赖的风格基底(§5.7)同样 ≥252 (否则增量 IC 不可计算)
  AND (4) universe 在该窗内非全程 today_snapshot_only (有真 forward 累积成分)
门 CLOSED 期间: 该族因子 significant=None (insufficient_history), 委员 abstain, UI 显示进度条
门 OPEN 后: 触发对该族的真实 OOS 复核; 仅此时其 IC/DSR/beats 结论才进入"alpha 证据"语义
```

成熟度门状态随每次离线批写入 `factor_meta`/`factor_eval`，仪表盘显式展示各因子族"距门开启还差 N 期"。**这是把"里程碑可演示≠因子可信"做成客观闸门、而非口头免责的落地机制。**

---

## 15. 参考文献

**经典/方法论**
- Gu, Kelly & Xiu (2020). *Empirical Asset Pricing via Machine Learning.* RFS.
- Harvey, Liu & Zhu (2016). *…and the Cross-Section of Expected Returns.* RFS.（因子动物园 + 多重检验 t≥3.0）
- López de Prado (2018). *Advances in Financial Machine Learning.*（purged/embargoed CV, CPCV, 元标签）
- Bailey & López de Prado (2014). *The Deflated Sharpe Ratio.*（SR0 / Var(SR_trials) / N 口径）
- Bagnara (2024). *Asset Pricing and ML: a critical review.* JoES 12532.
- Lalwani, Meshram & Jindal (2025). *Research Design Choices in ML Portfolios.* EuFM 70033.（非标准误差 5×）
- DeMiguel, Garlappi & Uppal (2009). *Optimal Versus Naive Diversification.*（1/N 常胜出）
- Michaud (1989). *The Markowitz Optimization Enigma.*（误差最大化器）
- Ledoit & Wolf (2004/2020). *Honey, I Shrunk the Sample Covariance Matrix / Nonlinear Shrinkage.*
- López de Prado (2016). *Building Diversified Portfolios that Outperform Out-of-Sample (HRP).*
- Black & Litterman (1992).（BL 后验；本系统默认关闭）
- Fama & French (1992/2015)；Jegadeesh & Titman (1993)（动量）。

**A股专门**
- Li, Liu, Liu & Wei (2024). *Replicating and Digesting Anomalies in the Chinese A-Share Market.* MgmtSci.（~85% 复现失败）
- Liu, Stambaugh & Yuan (2019). *Size and Value in China.* JFE.（**剔最小30%市值 + EP 替代 BM + MKT/SMB/VMG(PMO)** — §5.7/§6 双口径的方法学依据）
- Jung, Keeley & Ronen (2019).（EPS-revision 缩放陷阱）

**LLM 挖因子 / 多智能体 / 诚实基准**
- AlphaAgent (2502.16789)；CogAlpha (2511.18850)；Navigating the Alpha Jungle LLM+MCTS (2505.11122)；AlphaEval (2508.13174)。
- ContestTrade (2508.00554)；TradingGroup (2508.17565)；QuantAgent (2509.09995)。
- StockBench (2510.02209)；Agent Market Arena (2510.11695)；The Alpha Illusion (2605.16895)；CN-Buzz2Portfolio (2603.22305)。

**框架**：Microsoft Qlib（Alpha158/360, PIT, DSL）；alphalens；cvxpy；statsmodels；sklearn Ledoit-Wolf。

---

## 16. 接口实测附录（2026-06-21, akshare 1.18.64）

> 凡设计依赖的接口均经 `getattr + inspect` 实测，把"已核实存在"从纸面声明变为事实。

| 接口 | 状态 | 关键发现 |
|---|---|---|
| `stock_a_indicator_lg` | ❌ **不存在(MISSING)** | 已移除/改名 → 估值因子改用 `stock_zh_valuation_baidu` + `stock_zh_a_spot_em` |
| `stock_zh_valuation_baidu` | ✅ 存在 | **形参 (symbol, indicator, period)；每次仅返单一指标(PE 或 PB 或 PS 或总市值)、单列 value；period 决定历史窗，默认 '近一年'≈366 行；长历史须显式传 近三年/五年/十年/全部** → 每估值因子=symbol×indicator×period 笛卡尔，覆盖 EP/BP/SP/DY 需 4+次/标的；factor_meta 落 baidu_indicator/baidu_period/compute_path；history_depth 按实拉 period |
| `index_stock_cons_csindex` | ✅ 存在 | **仅 symbol 参数，无 date** → 只返今日成分 → 幸存者偏差不可历史消除（叠加未剔小票会进一步高估另类/反转 IC）|
| `stock_yjyg_em` / `stock_yjkb_em` | ✅ 存在 | 全市场业绩预告/快报，**携真披露日** → 升为默认对齐：可见日=min(法定截止日, 真披露日) |
| `stock_hsgt_individual_detail_em` | ✅ 存在 | per-symbol 北向明细（替代市场级 hold_stock_em） |
| `stock_zh_a_gdhs_detail_em` | ✅ 存在 | per-symbol 股东户数明细 |
| `index_option_300etf_qvix` | ✅ 存在 | **单一 QVIX OHLC 序列，无近/远月双序列** → 删期限结构分量 |
| `stock_zh_a_spot_em` / `stock_value_em` | ✅ 存在 | 全市场截面快照 |
| `stock_financial_analysis_indicator` | ✅ 存在 | **首列为报告期末日期，无公告日列** → 配合 yjyg/yjkb 真披露日对齐，回退法定截止日 |
| `stock_board_industry_name_em` | ✅ 存在 | **一级行业清单（中性化/Barra 行业基底来源）** |
| `stock_individual_info_em` | ✅ 存在 | **个股→所属行业归属（行业 PIT：随时间变更→forward 累积+caveat）** |

**依赖实测**：mcp-tool-service/requirements.txt 仅 numpy/pandas/akshare/yfinance；scipy/scikit-learn/cvxpy/lightgbm **均未装于该容器** → 必须显式新增（scipy + sklearn==1.7.2 与 agent-service 一致 + cvxpy 惰性）。mcp-tool 的 sklearn 仅用于无 pickle 纯数值计算。

**容器/工件实测**：agent-service 镜像 **Python 3.12**（注释"匹配 xgboost 3.3.0 pickle 跨端可加载"）；mcp-tool-service 镜像 **Python 3.11**。现有 ml_signal/SignalCalibrator pickle 在 py3.12 训练 → **ML 横截面模型训练+推理统一 py3.12/agent-service（§3.3 方案A）**；跨容器 pickle round-trip 列入 CI。

**现有代码实测**：`govern()` 签名止于 R8（R9 在 committee 层 note）；`calibration.py` 当前仅 `assess()`（可靠性图诊断），**无 per-view 置信度接口** → BL Ω 为依赖件、默认关闭；`bootstrap_significance` n<20 返回 significant=None；`walk_forward_auc` 是组内时间留出（**非真 purge**，横截面必须新写 panel_walk_forward）；seasonality BH 内联于 day_of_week_effect；anomaly `_K=0.6745`（乘子，与 winsorize 用的 1.4826 互为倒数）；storage 现有 5 表（quotes/news/analysis/alerts/watchlist）；db._by_member 用 `'风险信号' in lens` 排除非方向票。