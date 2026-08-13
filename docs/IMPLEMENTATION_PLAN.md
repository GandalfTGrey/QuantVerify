# QuantVerify 技术实施与项目计划

> 计划基线：2026-08-12
> 方法：Vertical Slice + milestone exit criteria
> 估算单位：1 engineer-day（专注开发日），用于排序和容量规划，不是日期承诺

## 1. 交付策略

每个里程碑都交付一条可验证的完整能力，并设置退出条件。新模块数量不是进度指标；可信、可复现的研究闭环才是。

项目现按 Data Trust、Research Correctness、Platform、Return Semantics 和 Independent QA 五条泳道组织。共享领域模型、实验身份、application/preflight 契约和 ADR 编号仍由 S-5.6 单一批准；独占目录按 `COLLABORATION_SCOPE.md` 分配。

增加人力不会改变依赖方向。fixture-only 研究闭环可以与真实数据准入并行；真实市场研究必须等待 CaptureStore hardening、A3、A4，以及目标收益语义所需的公司行动 policy 全部通过。

## 2. 当前状态

| 工作项 | 状态 | 说明 |
|---|---|---|
| 仓库与开发分支 | Done | 具名贡献者个人分支 + S-5.6 集成门禁 |
| 架构 v0.2 | Done | 补齐 causal/PIT/portfolio/identity/governance |
| 架构审查 | Done | 严重度、风险和处置已记录 |
| Python package baseline | Done | `pyproject.toml`、package、gitignore |
| Core domain contracts | Done / Partial extension | market series、交易日历、因果周期 bar、DatasetReleaseRef 与 CORE-05A application boundary 已冻结；CORE-05B/artifact v2 仍待完成 |
| Stable identity | Done | canonical SHA-256 experiment/run identity |
| Core unit tests | Done | 身份稳定性、时区、split、因果约束 |
| Versioned config loader | Done | YAML schema version、strict validation |
| CI baseline | Done | Python 3.11/3.12/3.13、Ruff、mypy、pytest、coverage、SHA-pinned actions、并发/超时、regular-wheel、离线 extras、Mac arm64 与依赖治理 SW02-06 已完成 |
| 研究守则整合 | Done | Data Integrity、Research Protocol、Strategy Universe |
| Initial ADR set | Done | precedence、timing、identity、dual-source validation |
| Golden signal fixture | Done | 手算 SMA3、warm-up、T+1 target、causality regression |
| Reference engine v1 | Done | long/flat、next-open、成本与逐期 equity golden tests |
| RawCapture boundary | Done | 一次抓取、深度不可变、离线 normalization |
| CaptureStore A2 | Done / Audit | content-addressed capture/manifest；Argus Issue #11 独立审计 |
| CaptureStore hardening | Done | #18 credential guard、#19 atomic publish、#20 verified replay 已合并并通过对抗审查 |
| Quality Suite v2 | Done | #16 已合并；完整输入闭包重放、ordered normalized identity 与区间级 eligibility 已冻结；ADR-0009 Accepted |
| DatasetReleaseRef contract | Done | CORE-03 PR #59；RAW/daily/single-active-source、eligible intervals、calendar/schedule、单资产 experiment identity；ADR-0011 Accepted |
| Immutable artifact v1 | Done | canonical JSON result/manifest、hash、verified load；ADR-0008 |
| Verified artifact inspection | Done | 显式 manifest path、canonical path/hash/content 验证、legacy read 与并发回归；PR #40 |
| Metrics v1 | Done | Total/CAGR/Vol/Sharpe/MaxDD、显式 undefined/failure、输入一致性与破产吸收态；PR #38 |
| Causal weekly/monthly bars | Done | 显式 verified-schedule boundary、完整/partial/missing 三态、截断不变；PR #37 |
| Fixture strategy pack | Done | S4/S2/S3/S1 与 S5 signal-only 已合并（PR #39/#41/#43/#45/#49）；S5 不宣称多资产执行 |
| Experiment service/CLI | Blocked / Design | Issue #17；CORE-05A/ADR-0012 已完成，fixture-only run 仍等待 CORE-06 与 SW-03 |
| 真实市场数据准入 | Blocked | AkShare 美股历史缺口；Tushare 无美股权限；尚无 Gold dataset |
| S-5.6 integration train | In progress | CORE-05A 已随 PR #61 合并；当前先修 #63 Decimal identity，审查 SW-03，并冻结 CORE-06 Metrics/artifact v2 |

## 3. Milestone 0 — Foundation

目标：冻结首个可编码的研究契约，使后续 adapter 不会各自定义语义。

预计：4-6 engineer-days；M0-01 至 M0-08 已完成。最终以 S-5.6 集成 PR 合并并通过主线 CI 作为退出记录。

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
| M1-06 | Metrics v1 | M1-05 | Total/CAGR/Vol/Sharpe/MaxDD 定义与测试；已完成 | 1.5 |
| M1-07 | Artifact writer | M1-05 | v1 canonical JSON result + manifest + hashes；已完成 | 1.0 |
| M1-08 | Experiment service/CLI | M1-01..07 | fixture-only 单命令运行并输出 experiment/run ID；真实数据等 A4 | 1.0 |
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
- CI 固定 Python 3.11/3.12/3.13 matrix；
- 目标：core >=90%，整体覆盖率仅作辅助指标。

### 架构治理

首批 ADR：

- ADR-0001 架构治理与文档优先级；
- ADR-0002 causal timing and execution semantics；
- ADR-0003 content-addressed experiment/run/artifact identity；
- ADR-0004 dual-source data validation；
- ADR-0005 AkShare ingestion boundary；
- ADR-0006 RawCapture normalization boundary；
- ADR-0007 provider-agnostic CaptureStore。
- ADR-0008 immutable reference-result artifacts。
- ADR-0009 Quality Suite v2（随 #16 审查接受）。

### 项目管理

- 每周以 milestone exit criteria 演示，而不是按代码行汇报；
- 风险登记册每周复核；
- scope change 进入 backlog，不在进行中 milestone 偷换目标；
- 技术债必须注明影响的研究正确性或交付速度；
- 任何“结果异常优秀”优先按 bug/偏差排查。

## 12. 当前下一批 Issues

关键路径按以下顺序处理：

1. `#63/#64 exact Decimal identity`（SW-03 的 normalized hash 前置修复）；
2. `#27/#62 SW-03 FixtureBundle`；
3. `#66 CORE-06 rational-return Metrics v2 + artifact v2 lineage`；
4. `CORE-05B registry-backed fixture run handler`；
5. `#17 M1-08 fixture-only CLI/composition`；
6. `#29 A4 verified DatasetRelease factory/store + authoritative calendar resolver`；
7. 真实数据 application preflight（另依赖 A4；adjusted/total-return 还依赖 CA-01）。

已完成的并行基础：DATA-01/A3、CORE-03、CORE-05A、#22 causal week/month bars、#23 Metrics v1、#24 verified artifact inspection、#30 五策略 fixture reference pack，以及 #26 SW02。当前可并行工作为：#63 Decimal identity 修复、#27 FixtureBundle、#66 CORE-06 design、#29 A4 design、#5 QQQ/DIA 冲突证据与 #25 公司行动 contract/design。#17 application/CLI 仍等待 CORE-05B/06 与 FixtureBundle；#28 是增量独立 QA。完整 Owner、文件边界和 merge train 见 `COLLABORATION_SCOPE.md`；实时 head SHA 与 blocker 以 #14 为准。

## 13. 已确认的产品与工程决策

| ID | 决策 | 当前基线 |
|---|---|---|
| D1 | 首期资产 | 美股目标保留 QQQ/DIA；中国双源实验候选为 510300、159915、600519、000001，准入前不固化最终 universe |
| D2 | 数据源 | 中国候选使用 Tushare + AkShare；美股调查使用 AkShare + yfinance；在质量 gate 通过前不指定 primary，不混合冲突值 |
| D3 | 默认执行 | 日/周/月周期均在 period close 决策，下一交易日开盘执行，lag >= 1 |
| D4 | 仓位 | long/flat；不做空、不加杠杆、不做多币种，base currency = USD |
| D5 | 产品形态 | Mac M1 本地单用户 modular monolith |
| D6 | 研究策略 | 见 `M1_RESEARCH_SCOPE.md` 的五个候选及强制基准 |
| D7 | Promotion | 暂采用架构默认：先 evidence hard gates，再评分，不固定收益阈值 |
| D8 | Git 协作 | feature branch + Draft PR，不直接推 main |
| D9 | 许可 | All rights reserved / proprietary |
| D10 | 资源预算 | Apple Silicon M1；单批任务允许连续运行约 24 小时 |

## 14. 当前外部依赖与下一步

- base conda 已确认可使用 AkShare、Tushare、pandas 与 NumPy；项目开发依赖按 `pyproject.toml` 安装；
- Tushare 凭据仅通过本地忽略配置使用，已验证中国日线接口可调用，但没有美股权限；凭据及响应数据不得因测试便利进入 Git；
- M0、reference engine、RawCapture/CaptureStore hardening、Quality Suite v2、DatasetReleaseRef、immutable run artifact v1、verified artifact inspection、Metrics v1、因果周/月重采样及五策略 fixture reference pack 已完成；当前由 S-5.6 冻结 application 与 artifact v2 lineage，并协调 FixtureBundle 和 A4 verified publication；
- 新增资深量化、公司行动、软件和 QA 人力按 `COLLABORATION_SCOPE.md` 在独占目录并行，不直接修改 Argus 的 active files；
- QQQ 是 Nasdaq-100 ETF，不代表 Nasdaq Composite；若目标实际是 Nasdaq Composite，应把 QQQ 改为 ONEQ 并重新冻结 asset identity。
