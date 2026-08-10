# QuantVerify v0.1 架构审查报告

> 审查日期：2026-08-10
> 审查范围：原 `PROJECT_ARCHITECTURE.md` v0.1
> 结论：方向正确，需补齐研究正确性契约后再扩大实现

## 1. 总体评价

原方案最有价值的决定是把项目定义为策略研究实验室，明确区分 Signal Research 和 Execution Research，并把 Experiment、Robustness、Promotion Gate 设为一等概念。这避免了常见的两种失败：先堆回测脚本，或过早围绕某个交易框架设计全部领域对象。

但 v0.1 更接近“能力地图”，尚未达到可指导多人实现的架构基线。最大风险不是组件缺少，而是若干研究语义没有成为正式契约：什么时候知道数据、什么时候产生信号、什么时候可成交、如何从信号得到组合、实验如何唯一标识、样本外数据如何隔离。若直接按原模块树并行开发，系统可能很快运行，却无法证明结果可信。

审查后的建议是：保留产品方向与分阶段策略，调整依赖方向，新增 Portfolio Construction、Point-in-Time Data、Causal Timing、Identity/Lineage、Research Protocol 和 Evidence Quality 六条主线，并以小型 reference fixtures 先验证语义，再接入 VectorBT 扩展性能。

## 2. 关键发现与处置

| ID | 严重度 | 原方案问题 | 风险 | v0.2 处置 |
|---|---|---|---|---|
| AR-01 | Critical | 未正式定义 signal time、decision time、execution time | 同 bar 成交、look-ahead、收益错位 | `TargetPosition` 增加 `decision_at/effective_at`，默认至少一 bar 延迟 |
| AR-02 | Critical | 数据只有单一 timestamp | 财务修订、指数成分和公告数据泄漏未来 | 引入 `event_time/available_time/ingested_at` |
| AR-03 | Critical | `Signal` 直接变成 `TargetPosition` | 信号、仓位和风险约束耦合，多资产逻辑失真 | 新增 Portfolio Construction/Risk Policy |
| AR-04 | Critical | Experiment ID 未覆盖代码、环境、随机性 | 相同 ID 可能对应不同结果，无法复现 | 分离 `experiment_id`、`run_id`、`artifact_id` |
| AR-05 | High | 依赖图表现为 core 指向 data/engine | 容易让领域层依赖框架与存储 | 改为 domain-owned ports + adapters |
| AR-06 | High | VectorBT 作为核心主路径而非纯 adapter 语义 | 第三方升级改变结果且难发现 | 统一 artifact schemas，并与 reference fixtures 对账 |
| AR-07 | High | Robustness 列出方法但缺少研究治理 | 多次试验、测试集反复使用导致选择偏差 | 记录全部尝试，测试集解封规则和 protocol version |
| AR-08 | High | 动态 universe 只作为“未来注意事项” | MVP 若含个股研究会立即出现幸存者偏差 | snapshot + effective dates 成为数据 gate |
| AR-09 | High | Adjustment、现金分红和 corporate actions 语义不足 | 总回报重复计算或漏算 | snapshot manifest 固化 adjustment mode |
| AR-10 | High | Benchmark 只是比较模块 | 不同口径、成本和日历造成伪 alpha | Benchmark 也作为可追溯运行，统一对齐 |
| AR-11 | High | Result Store 只有实体名，无不可变/并发策略 | 重跑覆盖、并发写损坏、查询与事实混合 | append-only metadata + immutable Parquet artifacts |
| AR-12 | High | Rating 只有建议权重 | 高收益可能掩盖数据质量或前视偏差 | hard gates + versioned policy + reviewer audit |
| AR-13 | Medium | Market Regime 未定义识别时间 | 用完整样本事后分类造成泄漏 | regime 算法也需 PIT/版本/输入时点约束 |
| AR-14 | Medium | 缺少多币种、现金和 FX 语义 | 跨市场组合收益错误 | Portfolio 层加入 base currency、cash、FX policy |
| AR-15 | Medium | 缺少 schema 演进策略 | 历史 artifacts 随代码升级不可读取 | 所有核心模型和 artifact 带 schema version |
| AR-16 | Medium | 测试只写了 Pytest，没有测试不变量 | 很难防止“结果看起来合理”的错误 | unit/property/contract/golden/regression 分层 |
| AR-17 | Medium | Agent 边界不足 | 自动调参、选择性报告和执行任意代码 | 审批、资源预算、审计、禁止自动 Promotion |
| AR-18 | Medium | 缺少 secrets、许可和数据治理 | 凭证泄漏、数据非法再分发 | `.env`、manifest license、Git ignore、安全扫描 |
| AR-19 | Medium | MVP 数量目标多、质量门少 | 为完成“10+ 策略”复制不可信实现 | milestone exit criteria 优先于策略数量 |
| AR-20 | Low | 原文架构与实施细节混在同一长文档 | 难以判断当前状态和下一步 | 拆成 Architecture、Review、Implementation Plan |

## 3. 保留的关键决定

以下决定无需推翻：

- Research First，而不是 execution first；
- Signal Research 与 Execution Research 分离；
- Experiment 是一级对象；
- VectorBT 适用于 Stage 1 的大规模候选筛选；
- Parquet + DuckDB 适合本地优先的初期形态；
- Streamlit + Plotly 适合作为首期研究控制台；
- Promotion Gate 阻止普通策略进入昂贵的执行研究；
- Kafka、Redis、Celery、Kubernetes 和微服务暂缓；
- 采用 vertical slice 而不是先完成所有模块。

## 4. 需要纠正的设计细节

### 4.1 领域层应拥有接口

原依赖图用箭头表达 `core -> data/engine`，容易理解为核心依赖实现。正确规则是核心/application 定义所需端口，VectorBT、DuckDB 和供应商 adapter 依赖这些端口。运行时通过 dependency injection 组装。

### 4.2 StrategySpec 不是唯一策略实现形式

简单条件可由 YAML 表达；复杂横截面排序、状态机或组合优化不适合无限扩张 DSL。建议 YAML 负责声明和引用，受版本控制的 Python 实现负责复杂逻辑。禁止用 `eval` 把 YAML 变成任意代码执行入口。

### 4.3 数据版本不能只使用时间戳

同一供应商、同一日期范围可能因修订得到不同数据。版本必须是 manifest + 分区内容的哈希，并记录 schema、调整方式和质量报告。数据源名称不等于数据版本。

### 4.4 回测结果不是一个巨型对象

净值、逐期收益、持仓和成交可能很大。领域层用 `ArtifactRef` 指向版本化 Parquet artifacts；数据库保存索引和小型汇总。这样既支持本地分析，也避免数据库成为大数组存储。

### 4.5 评级不能只做加权平均

Data Quality、Look-ahead、Reproducibility 和 OOS evidence 属于硬门槛。通过硬门槛后，才对收益质量、风险、稳定性和复杂度做加权排序。

## 5. 风险登记册

| 风险 | 概率 | 影响 | 早期信号 | 缓解措施 | Owner |
|---|---|---|---|---|---|
| 前视偏差未被发现 | 高 | 致命 | 异常高且平滑的结果 | 时间契约、causality/golden tests | Research/Architecture |
| 幸存者偏差 | 高 | 致命 | 个股历史结果显著优于指数 | historical universe snapshots | Data |
| 参数/策略多重试验 | 高 | 高 | 只保留最佳实验 | 全量 registry、DSR/PBO、holdout policy | Research |
| 数据许可不支持缓存/分发 | 中 | 高 | provider 条款不清 | manifest license 和访问控制 | Product/Data |
| VectorBT 与参考语义不一致 | 中 | 高 | adapter 升级后指标跳变 | fixture 对账和版本锁 | Engine |
| DuckDB 并发写冲突 | 中 | 中 | 多 worker 写失败 | 单 writer/append files，后续 PostgreSQL | Storage |
| 参数矩阵造成资源爆炸 | 高 | 中 | 内存溢出、运行时间失控 | preflight budget、chunking、取消 | Experiment |
| 测试集被反复使用 | 高 | 高 | OOS 结果逐版变好 | 解封审计、滚动保留最终窗口 | Research |
| Agent 选择性报告 | 中 | 高 | 报告缺少失败实验 | workflow policy、audit、人工 gate | Agent/Product |
| 过早产品化 | 中 | 中 | UI/API 工作超过研究核心 | milestone exit criteria | PM |

## 6. 架构质量属性评估

| 属性 | v0.1 | v0.2 目标 | 验证方式 |
|---|---|---|---|
| Correctness | 有理念，缺契约 | 时间、数据和成本不变量明确 | golden/property tests |
| Reproducibility | 有字段清单 | 内容寻址的三层身份 | ID tests + rerun comparison |
| Modularity | 模块较全 | domain-owned ports | import rules/contract tests |
| Scalability | VectorBT 导向 | 单机批量优先、可测后演进 | benchmark + resource telemetry |
| Auditability | 实验谱系概念 | append-only runs/audit events | lineage query tests |
| Security | 未覆盖 | secrets、许可、受控 Agent | CI scans + policy review |
| Operability | 未覆盖 | 结构化日志、错误分类、可恢复 | failure injection tests |

## 7. 审查结论

项目应继续，并且可以立即实现 M0。当前不建议直接批量实现 20 个策略或 Dashboard；那会把尚未稳定的时间、数据和结果语义复制到整个系统。正确的首个工程目标是用一个很小但可逐期人工核对的 fixture，证明：输入快照、信号、延迟仓位、成本、收益、指标、身份和 artifact 谱系完全一致。

本次已经启动 M0：项目元数据、核心领域模型、端口协议、确定性身份和关键校验测试已建立。剩余决策见实施计划中的“需要产品负责人确认”。
