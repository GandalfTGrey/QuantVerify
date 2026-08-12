# ADR-0011：DatasetReleaseRef 与真实数据实验边界

- Status: Accepted
- Date: 2026-08-12
- Owner / Reviewer: S-5.6 / Argus、Q-Lead、QA-Lead
- Depends on: ADR-0009, ADR-0010
- Tracking: Issues #21, #29

## Context

`DataSnapshot` 只描述早期 fixture/provider snapshot，缺少 normalizer、quality report/policy、eligible range、verified calendar 和 adjustment evidence。若真实数据实验继续只引用 `DataSnapshot`，相同 bars 在不同质量政策、日历或 adjustment 语义下仍可能共享实验 identity；下游也无法证明请求区间落在已验证范围内。

A3 已冻结 `QualitySuite.verify_report(...)`：孤立、自洽甚至完整重哈希的 `DataQualityReportV2` 不是生产 eligibility assertion。A4 必须携带完整输入闭包重放成功，才能发布 Gold release。

## Decision

### 1. 保留 fixture 兼容路径，新增真实数据 release 引用

`ExperimentConfig.dataset` 接受：

- 既有 `DataSnapshot`，仅供 fixture/legacy 路径；
- 新增不可变 `DatasetReleaseRef`，供未来真实数据 application preflight。

加入 release 后，完整 release 内容自然进入 `experiment_id`。`ExperimentConfig.experiment_id` 计算前重新验证完整 config；release frequency 必须与实验 frequency 一致。

本 ADR 不把 `DataSnapshot` 自动升级为真实数据，也不定义 application mode。CORE-05 必须显式区分 fixture 与 real-data execution，并在 real-data mode 拒绝 `DataSnapshot`。

### 2. Release identity 绑定科学输入与治理语义

`DatasetReleaseRef v1` 仅接受日线 normalized release，并绑定：

- asset、frequency、adjustment mode；
- normalized content hash、schema、normalizer id/version；
- selected raw evidence id、selected normalized input id，以及固定的 `single-active-source` resolution policy/version；A4 v1 只接受恰好一个 active source 的 report，并证明发布 bars 精确等于该 normalized observation；多 source report 一律 fail closed，直到独立、版本化的 source-resolution contract 被接受；
- accepted quality suite id/version；
- quality policy id/version/content hash；
- 完整 `CalendarArtifactRef` 与 pinned schedule id/content hash/requested bounds/session count；
- 一个或多个排序、不重叠的 eligible intervals；
- 每个 interval 的 inclusive session bounds、session count、exact expected-session-set hash、独立 quality report id/content hash 与排序唯一 warning finding ids；
- v1 固定 `RAW` adjustment semantics；adjusted/total-return 必须等待 CA-01 冻结 typed point-in-time transform ref 后发布新的 release-ref version。

`release_id` 对完整、重验证后的引用计算 `drel_*` identity。墙钟发布时间、路径或 mutable `latest` 不属于科学 identity，也不进入本契约。

### 3. Adjustment evidence fail closed

- `DatasetReleaseRef v1` 只允许 `RAW`；
- `SPLIT_ADJUSTED` / `TOTAL_RETURN` 不能用若干自由输入 hash 冒充完整 evidence；
- CA-01 必须先冻结 typed point-in-time transform ref，至少覆盖 RAW input/release、action-event manifest/vintage、as-of/cutoff、producer/schema/version、policy 与 output hash，再通过新的 release-ref version 扩展。

这只冻结 RAW 引用层规则，不代表 CA-01 已实现；A3 当前 `INCOMPLETE` 的 adjusted report 不得被 A4 晋升。

### 4. Eligible interval 是精确 session evidence，不是自然日授权

每个 interval 使用 inclusive `start_session..end_session`，并绑定 exact session count/hash 和一份对相同 requested range 完整重放成功的 A3 report。一个报告不能自行扩张、复制或合并为多个区间。多个 interval 可以表达历史缺口，但必须排序且不重叠。

`structurally_supports_consumed_schedule(schedule)` 只做结构 gate：完整、非空的已验证 consumed schedule 必须与 release calendar 完全一致、落在 pinned parent schedule bounds 内，并且其首尾 session 完整落在同一个 eligible interval。跨 gap、越界或 unsafe schedule fail closed。该方法不证明传入 schedule 的交易所权威性，也不替代 verified calendar loader；application 必须先从 release 所绑定的权威 schedule 解析请求的完整实际 sessions（包括 warmup/lookback、估值和下一 open execution session），逐 session 比对 pinned parent schedule 的 exact slice，再调用 containment gate。只检查 performance range 不构成生产准入。

### 5. 单资产 release 不得冒充多资产 universe

`DatasetReleaseRef v1` 只描述一个 asset。其唯一合法 experiment universe id 由 release 派生为 `single:<venue>:<symbol>`；`ExperimentConfig` 在构造和 identity 边界执行该约束。QQQ release 因此不能与 `QQQ+DIA`、`us_index_etfs_v1` 等多资产 universe 组合。

S5 双动量或其他多资产实验必须等待独立的 `DatasetBundleRef`/session-range contract；该 contract 必须逐资产绑定每个 release 和共同可消费的 verified schedule range。单资产 release id 不可替代 bundle identity。

### 6. Ref 自洽不等于 release authenticity

和质量报告一样，公开 Pydantic DTO/哈希不能证明生产者身份。调用方手工构造一个自洽 `DatasetReleaseRef` 不等于 Gold 发布。

A4 实现必须提供受控 factory/store，至少：

1. 对完整 A3 输入执行 `verify_report`；
2. v1 只接受恰好一个 active source；选定该 report 中唯一的 evidence/normalized input pair，重算实际输出 bars 的有序 normalized identity并逐字段一致；多 source report 一律拒绝，禁止 latest、平均、拼接或按策略表现选源；
3. 验证 calendar artifact/schedule authority 与 interval session hashes；
4. v1 factory 一律拒绝 adjusted promotion；CA-01 接受并发布新契约后才允许扩展；
5. immutable publish，并返回由受信 store/manifest anchor 的 ref。

CORE-05 real-data preflight 必须解析该受信 release，而不是仅接受任意 DTO 或 implicit latest。

## Compatibility

- 既有 `DataSnapshot` configs、artifact v1 和 fixture tests 保持可读；
- `ExperimentConfig` 的 dataset union 对旧 config 无 identity 变化；
- release config 是新增形态，尚不代表 CLI/application 已支持真实数据运行；
- release-backed config 仅支持派生的单资产 universe；S5/多资产 config 等待 bundle contract；
- `SeriesDescriptor.source_kind=dataset_release` 可以引用 `release_id` 与 normalized content hash，但不会自行证明 Gold authenticity。

## Consequences

- 质量 policy/report、normalizer、calendar/schedule、eligible interval、adjustment/action 变化都会改变 release 与 experiment identity；
- 多个不连续 eligible intervals 可被准确表达，但一次实验请求不得跨越 gap；
- fixture 与 real-data 的信任边界可以在 CORE-05 显式执行；
- A4 需要保存并重放比单个 DTO 更完整的证据闭包。

## Non-goals

- 不实现 A4 factory/store 或 Gold publication；
- 不实现 verified calendar loader；
- 不实现 CA-01 corporate-action transform；
- 不修改 strategy、engine、provider、CLI 或 artifact v2；
- 不允许 performance-based source selection、silent averaging 或 mutable latest。

## Review Gate

本 ADR 已通过 S-5.6 与独立 QA 对抗 review。A4 implementation 可以据此准备实现，但在 verified factory/store、权威 calendar resolver 与 application preflight 完成前，不得宣称真实数据 release 可用。
