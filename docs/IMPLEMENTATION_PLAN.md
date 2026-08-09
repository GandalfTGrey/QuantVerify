# QuantVerify 技术实施与项目计划

> 计划基线：2026-08-10
> 方法：Vertical Slice + milestone exit criteria
> 估算单位：1 engineer-day（专注开发日），用于排序和容量规划，不是日期承诺

## 1. 交付策略

每个里程碑都交付一条可验证的完整能力，并设置退出条件。新模块数量不是进度指标；可信、可复现的研究闭环才是。

建议先由 1 名 Python/quant engineer 完成 M0-M2。若多人并行，按 Data、Research Engine、Validation 三条 stream 分工，但核心领域模型和研究协议保持单一 owner。

## 2. 当前状态

| 工作项 | 状态 | 说明 |
|---|---|---|
| 仓库与开发分支 | Done | 已在 `agent/foundation-architecture` 开始 |
| 架构 v0.2 | Done | 补齐 causal/PIT/portfolio/identity/governance |
| 架构审查 | Done | 严重度、风险和处置已记录 |
| Python package baseline | Done | `pyproject.toml`、package、gitignore |
| Core domain contracts | Done | 时间、数据、成本、实验、运行、目标仓位 |
| Stable identity | Done | canonical SHA-256 experiment/run identity |
| Core unit tests | Done | 身份稳定性、时区、split、因果约束 |
| Versioned config loader | Done | YAML schema version、strict validation |
| CI baseline | Done | Python 3.11/3.12、Ruff、mypy、pytest、coverage |
| 研究守则整合 | Done | Data Integrity、Research Protocol、Strategy Universe |
| Reference loop、storage | Next | 属于 M0 后半与 M1 |

## 3. Milestone 0 — Foundation

目标：冻结首个可编码的研究契约，使后续 adapter 不会各自定义语义。

预计：4-6 engineer-days；当前已完成 M0-01 至 M0-06，M0-07/08 进入下一提交。

### 工作包

| ID | 工作项 | 产出 | 验收标准 | 估算 |
|---|---|---|---|---:|
| M0-01 | 项目元数据 | pyproject、README、gitignore、env sample | clean install；数据/secrets 不入 Git | 0.5 |
| M0-02 | 核心领域模型 | Pydantic immutable models | unknown fields fail；timezone/causal validation | 1.0 |
| M0-03 | 实验身份 | canonical hashing | key 顺序无关；科学输入变化产生新 ID | 0.5 |
| M0-04 | 端口协议 | Data/Strategy/Engine/Store ports | adapters 可在不改 core 下替换 | 0.5 |
| M0-05 | 配置加载 | YAML -> typed config | schema/version/error path 清晰 | 0.5 |
| M0-06 | 工程质量 | CI、Ruff、mypy、pytest、coverage | PR 自动检查；core 覆盖率 >=90% | 1.0 |
| M0-07 | ADR | 初始关键决策记录 | dependency/time/identity decisions 可追溯 | 0.5 |
| M0-08 | Golden fixture | 10-30 bars 人工可核对数据 | 预期仓位/收益/成本固化 | 0.5 |

### Exit criteria

- 新环境可通过一条命令安装并运行测试；
- 相同 config/data/code/environment 产生相同身份；
- 不合法时间、无时区、同 bar 生效、未知配置均 fail fast；
- CI 对每个 PR 执行 lint、type check、unit tests；
- 至少一个 golden fixture 经人工计算审核。

## 4. Milestone 1 — Minimum Trusted Research Loop

目标：跑通 `fixture/CSV -> SMA signal -> portfolio -> engine -> metrics -> artifacts -> manifest`，优先证明逐期正确性。

预计：8-12 engineer-days。

### 工作包

| ID | 工作项 | 依赖 | 验收标准 | 估算 |
|---|---|---|---|---:|
| M1-01 | CSV/fixture DataProvider | M0 | schema/quality/manifest/content hash | 1.0 |
| M1-02 | Feature registry + SMA | M0 | warm-up 明确；truncation causality test | 1.0 |
| M1-03 | SMA crossover Strategy | M1-02 | signal 与人工 fixture 一致 | 0.5 |
| M1-04 | Long/flat allocator | M1-03 | target/effective timestamps 正确 | 0.5 |
| M1-05 | Reference engine | M1-04 | 逐期现金、仓位、收益、成本可对账 | 2.0 |
| M1-06 | Metrics v1 | M1-05 | Total/CAGR/Vol/Sharpe/MaxDD 定义与测试 | 1.5 |
| M1-07 | Artifact writer | M1-05 | versioned Parquet + manifest + hashes | 1.0 |
| M1-08 | Experiment service/CLI | M1-01..07 | 单命令运行并输出 experiment/run ID | 1.0 |
| M1-09 | VectorBT adapter spike | M1-05 | golden fixture 与 reference engine 对账 | 1.5 |
| M1-10 | End-to-end tests | all | 无网络 fixture 可重复通过 | 1.0 |

### Exit criteria

- 一个实验可从配置完整执行且生成不可变 artifacts；
- reference engine 的每一期结果可人工核对；
- VectorBT adapter 与 reference fixture 在定义容差内一致；
- 毛/净收益、成本、仓位和指标口径在 artifact schema 中明确；
- 重跑不会覆盖旧运行。

## 5. Milestone 2 — Data、Strategy 与 Portfolio 抽象

目标：从单一 fixture 扩展到真实但受控的数据快照和多策略/多标的研究。

预计：12-18 engineer-days。

### 工作包

- Provider 选择与许可审查；
- Raw landing、normalizer、validator 和 dataset manifest；
- 市场日历、时区、公司行动与 adjustment policy；
- static universe 与历史 snapshot 契约；
- feature cache 和 registry；
- StrategySpec schema、Python implementation registry；
- portfolio constraints、cash/base currency；
- 3 个代表性策略：趋势、均值回归、横截面/轮动各一个；
- 数据和策略 contract tests。

### Exit criteria

- 至少一个真实数据源可产生不可变 snapshot；
- 不使用网络也可从 snapshot 重跑；
- 数据质量报告可查询，严重错误阻止实验；
- 3 类策略共享相同 engine/metrics contracts；
- dynamic universe 在实现前不会被伪装成 static universe。

## 6. Milestone 3 — Experiment Matrix 与 Research Store

目标：安全地执行批量参数、标的和时间窗口实验，并形成可查询谱系。

预计：10-15 engineer-days。

### 工作包

- grid expansion 和 config normalization；
- preflight 组合数、内存和运行预算；
- chunked local execution、retry、cancel/resume；
- DuckDB catalog 和 schema migration；
- experiments/runs/attempts/artifact manifests；
- CLI：plan、run、status、inspect、compare；
- 参数 surface read model；
- 性能基线和缓存统计。

### Exit criteria

- `10 strategies x 10 assets` 的代表性矩阵可在预算内执行；
- 任意指标可追溯到 config、snapshot、code、environment 和 artifact；
- 单个失败不会丢失其他运行；
- 同一矩阵的幂等重试行为明确；
- 并发写入不会损坏 catalog。

## 7. Milestone 4 — Robustness、Rating 与 Promotion

目标：用版本化研究协议代替“按 Sharpe 排名”。

预计：15-22 engineer-days。

### 工作包

- temporal train/validation/test；
- walk-forward + purge/embargo；
- parameter neighborhood score；
- cross-asset、regime、cost/delay sensitivity；
- benchmark alignment；
- evidence bundle；
- hard gates + weighted score policy；
- 人工 Promotion review 和审计；
- 后续 DSR/PBO/bootstrap 的研究 spike。

### Exit criteria

- UI/CLI 明确区分 IS、validation 和 locked test；
- 失败实验也进入 registry；
- 数据或 look-ahead gate 失败不能被高收益覆盖；
- rating 可由同一 evidence bundle 重算；
- Promotion 有 reviewer、policy version 和理由。

## 8. Milestone 5 — Research Console

目标：提供只读优先、完全可追溯的研究视图。

预计：8-12 engineer-days。

页面：Strategy Overview、Run Detail、Equity/Drawdown、Parameter Surface、Cross Asset、Robustness、Data Quality、Leaderboard、Promotion Review。

Exit criteria：所有数值显示 run ID 和口径；Dashboard 不直接执行 SQL 业务逻辑；不会默认隐藏失败运行；图表与导出报告结果一致。

## 9. Milestone 6 — Research Agent

目标：自动化策略发现、形式化、实验草案和报告，不自动决定是否上线。

预计：10-16 engineer-days。

工作包：来源引用、StrategySpec 草案、schema validation、审批 checkpoint、experiment budget、全实验报告、prompt/model version、audit trail、防任意代码执行。

Exit criteria：Agent 无法绕过 locked test、hard gate 或人工 Promotion；每个事实可回链到 evidence；失败实验不被省略。

## 10. Milestone 7 — Execution Research

只有当 Stage 1 promotion policy 稳定且已有获批策略后启动。先建立 TargetPosition contract consumer 和 implementation shortfall 对账，再评估 VeighNa/RQAlpha/LEAN。Paper/live trading 需要独立安全、风控、账户和运维设计，不属于当前承诺。

## 11. 横向工程工作

### 测试与 CI

- 每个 bug 先增加回归 fixture；
- 核心财务计算使用 golden tests；
- 依赖升级单独 PR，并附结果差异；
- CI 固定 Python 3.11/3.12 matrix；
- 目标：core >=90%，整体覆盖率仅作辅助指标。

### 架构治理

首批 ADR：

- ADR-0001 Modular monolith + hexagonal ports；
- ADR-0002 causal timing and execution semantics；
- ADR-0003 content-addressed experiment/run/artifact identity；
- ADR-0004 Parquet artifacts + DuckDB catalog；
- ADR-0005 reference engine and VectorBT adapter validation。

### 项目管理

- 每周以 milestone exit criteria 演示，而不是按代码行汇报；
- 风险登记册每周复核；
- scope change 进入 backlog，不在进行中 milestone 偷换目标；
- 技术债必须注明影响的研究正确性或交付速度；
- 任何“结果异常优秀”优先按 bug/偏差排查。

## 12. 建议的第一批 Issues

1. `foundation: add CI for lint, typing and tests`
2. `config: load and validate versioned experiment YAML`
3. `data: define Bar v1 schema and golden fixture`
4. `features: implement causal SMA with warm-up policy`
5. `strategy: implement SMA crossover signals`
6. `portfolio: map signals to lagged long/flat targets`
7. `engine: build transparent reference engine`
8. `metrics: define and implement metrics v1`
9. `artifacts: write immutable Parquet run outputs`
10. `application: execute one experiment end to end`
11. `engine: reconcile VectorBT adapter against golden results`
12. `docs: add initial ADR set and research protocol`

## 13. 已确认的产品与工程决策

| ID | 决策 | 当前基线 |
|---|---|---|
| D1 | 首期资产 | QQQ（Nasdaq-100 ETF）与 DIA（DJIA ETF） |
| D2 | 数据源 | Tushare Pro 为主、AkShare 为交叉验证；冲突不静默择一 |
| D3 | 默认执行 | 日/周/月周期均在 period close 决策，下一交易日开盘执行，lag >= 1 |
| D4 | 仓位 | long/flat；不做空、不加杠杆、不做多币种，base currency = USD |
| D5 | 产品形态 | Mac M1 本地单用户 modular monolith |
| D6 | 研究策略 | 见 `M1_RESEARCH_SCOPE.md` 的五个候选及强制基准 |
| D7 | Promotion | 暂采用架构默认：先 evidence hard gates，再评分，不固定收益阈值 |
| D8 | Git 协作 | feature branch + Draft PR，不直接推 main |
| D9 | 许可 | All rights reserved / proprietary |
| D10 | 资源预算 | Apple Silicon M1；单批任务允许连续运行约 24 小时 |

## 14. 当前外部依赖与下一步

- base conda 已确认存在 AkShare 1.18.83、Tushare 1.4.29、pandas 2.2.3、NumPy 2.2.3；
- 当前环境尚未发现 Tushare token；接入真实 Tushare 数据前需通过 `TUSHARE_TOKEN` 配置，禁止写入 Git；
- M0 下一步是 ADR 与 golden fixture；随后进入数据双源 adapter 和可信研究闭环；
- QQQ 是 Nasdaq-100 ETF，不代表 Nasdaq Composite；若目标实际是 Nasdaq Composite，应把 QQQ 改为 ONEQ 并重新冻结 asset identity。
