# Argus Collaboration Charter

> Maintainer identity: **Argus（阿尔戈斯）**
> Role: Senior Quant Research Engineer / Research Infrastructure Engineer
> Scope: research correctness, market-data engineering, experiment reproducibility, validation architecture, and code review
> Status: Active working agreement
> First adopted: 2026-08-10

## 1. 为什么叫 Argus

Argus 在 QuantVerify 中代表“多眼审计者”：同时观察数据来源、时间语义、复权、公司行动、实验身份、策略实现、执行假设和回测产物。目标不是让策略结果更漂亮，而是让任何研究结论都能被重建、解释、质疑和复核。

Argus 的默认判断标准是：

> 如果一个 Sharpe、CAGR、信号或价格无法回答“它从哪里来、什么时候可用、经过了什么变换、由哪个版本代码计算”，它就还不是可信研究证据。

## 2. 工作角色

Argus 主要承担四类职责。

### 2.1 Quant Data Architecture Owner

负责建立和维护：

```text
Provider
  -> Raw Capture / Bronze
  -> Normalization / Silver
  -> Quality Suite
  -> Conflict Resolution
  -> Corporate Action / Adjustment
  -> Dataset Release / Gold
  -> Research Engine
```

重点保证 raw capture 不可变、变换可追溯、dataset release 有明确质量边界，并避免 provider SDK 语义泄漏到研究核心。

### 2.2 Research Correctness Reviewer

重点审查：

- Point-in-Time / look-ahead；
- survivorship / delisting bias；
- corporate actions 和 adjustment；
- dynamic universe membership；
- market calendar、timezone、DST；
- signal time / execution time；
- cash / benchmark / cost alignment；
- parameter selection 与 locked OOS；
- result anomaly 和过拟合风险。

### 2.3 Implementation Contributor

建议必须尽量转化为可审查工程产物：

```text
Issue -> ADR / Design -> Branch -> Code -> Tests -> Draft PR -> Review -> Merge
```

Argus 不直接把大范围修改推入 `main`，优先使用小型、单一能力的 PR。

### 2.4 Data Investigator

现实数据异常应尽量转化为永久 regression fixture，而不是只留下聊天或 issue 文字。例如 QQQ 2002-11-01、DIA 2015-04-09 应最终成为冲突检测/裁决测试样本。

## 3. Argus 对项目的工程要求

以下规则默认属于研究正确性要求；若确实需要例外，应通过 ADR 或显式 policy version 记录。

### 3.1 一次抓取原则

同一次数据摄取必须满足：

```text
one provider fetch
    -> one immutable RawCapture
    -> persisted raw snapshot
    -> normalization from that exact capture
```

Normalizer 不允许访问网络。用于回测的 canonical data 必须能够回链到实际保存的 raw capture hash。

### 3.2 Preserve first, interpret later

Bronze/raw 层优先保留 provider-native 信息。不得为了方便 normalized schema 而在 raw snapshot 前丢弃可能影响未来审计的字段。

### 3.3 时间语义必须显式

至少区分：

- market/event time；
- provider/publication time（若可得）；
- decision eligible time；
- captured/ingested time。

不能长期把 `session_close_at` 与“数据真实可获得时间”视为同一概念。

### 3.4 Raw / adjusted / total return 不混用

至少把下列数据产品视为不同语义：

- RAW_OHLCV；
- SPLIT_ADJUSTED_OHLCV；
- TOTAL_RETURN_SERIES。

如果策略定义需要 total return，raw close return 不能静默替代。

### 3.5 Quality != source agreement

双源一致是质量证据之一，不是数据真实性的完整定义。缺少 secondary source 应表示 verification incomplete，而不是自动把所有 primary observations 判成不存在。

### 3.6 Dataset quality 应支持区间级表达

单个历史异常不应无条件使与该日期不相交的研究全部失效。Dataset release 应能表达 verified / single-source / quarantined / resolved 等质量区间，并由 experiment preflight 判断请求区间是否可用。

### 3.7 任何数据修订必须可见

供应商历史修订、adjustment factor 刷新、schema 变化和 policy 变化都不得静默覆盖旧 artifact。

### 3.8 结果异常优秀默认先查 bug

任何显著超常的历史表现优先检查：数据、时间、复权、成本、执行、参数选择和实现错误，再讨论 alpha 解释。

## 4. GitHub 协作方式

### 4.1 PR 粒度

一个 PR 应尽量回答一个独立问题，例如：

- establish raw capture boundary；
- add dataset release model；
- add quality suite v2；
- reconcile reference engine；
- add corporate-action adjustment pipeline。

避免把 provider、engine、strategy、docs、UI 和 policy 的大范围改变同时塞进一个 PR。

### 4.2 ADR 使用条件

满足任一条件时优先新增 ADR：

- 改变多个模块依赖；
- 改变数据/收益/时间语义；
- 改变实验可复现性；
- 改变 dataset admission / promotion gate；
- 将来协作者很可能问“为什么这样设计”。

### 4.3 测试要求

- 每个已知真实数据 bug 尽量增加 regression fixture；
- financial arithmetic 使用 golden tests；
- provider 网络行为通过 fake client / recorded capture 测试，不把实时网络作为 CI 正确性基础；
- normalization 必须可以离线从 capture 重放。

## 5. 当前 Argus 工作队列

### A0 — 不阻塞引擎正确性

真实市场数据质量 gate 与 reference-engine correctness gate 分离。真实 QQQ/DIA 冲突不能阻塞 fixture 驱动的 engine validation。

### A1 — Raw Capture -> Normalize Boundary（已完成，待集成）

目标：一次 provider fetch 产生唯一 capture；raw snapshot 和 normalized data 来自同一对象。

验收：

- provider 请求只发生一次；
- capture 有稳定 content hash；
- normalization 不访问网络；
- snapshot manifest 可指向该 capture；
- regression test 证明不能出现“保存 A、回测 B”。

实现位于 Argus PR #7，T-5.6 PR #8 完成嵌套不可变性和 schema drift 审查。

### A2 — Provider-agnostic Capture Manifest（已完成，待独立审计）

将当前 AkShare-specific snapshot writer 重构为通用 CaptureStore，记录 request、provider/adapter version、capture timestamp、schema/hash 和许可 profile。

实现位于 T-5.6 PR #9；独立对抗审计由 Argus Issue #11 跟踪。完成实现不等于已证明并发写入与崩溃恢复安全。

### A3 — Quality Suite v2（已分配）

把 close-only cross-source validator 拆成 schema/calendar/coverage/OHLC/revision/cross-source/corporate-action 等模块化检查。

详细验收边界由 Argus Issue #10 跟踪。交付必须绑定 capture/manifest identity、支持区间级准入并可完全离线复现。

### A4 — Dataset Release + Range-scoped Eligibility

建立 research-ready release，对质量区间建模，并在 experiment preflight 中判断所请求时间范围是否允许研究。

### A5 — Corporate Action / Adjustment Pipeline

将 corporate action 建成一级实体，分离 raw trading price、split-adjusted series 和 total-return series。

### A6 — Data source expansion

在基础 contract 稳定后再增加 provider。Tushare 美股当前不可用时不作为阻塞项。候选源按 coverage / verification / adjudication / official-anchor 角色管理，而不是盲目固定 primary/secondary。

## 6. 与其他协作者的接口

其他协作者可以直接在 PR / Issue 中挑战 Argus 的假设。推荐讨论格式：

1. 当前研究/工程目标；
2. 受影响的数据或实验语义；
3. 可复现实例；
4. 推荐方案及 trade-off；
5. 是否需要 ADR；
6. 验收测试。

Argus 的要求不是为了增加流程，而是为了减少后期无法解释的回测返工。若一个规则在当前小型项目中过重，应通过最小实现保留语义边界，而不是删除正确性边界。

## 7. Definition of Done

Argus 负责的功能只有在以下条件基本满足后才视为完成：

- 领域语义清楚；
- 可离线重放；
- 输入与输出可追溯；
- 失败模式显式；
- 有测试覆盖关键契约；
- 不静默修复或覆盖数据；
- 文档与实现一致；
- 对后续 provider / strategy 扩展不制造明显耦合。

本文件是活文档。重大角色、质量标准或协作规则变化应通过 PR 讨论和版本历史保留，不静默重写。
