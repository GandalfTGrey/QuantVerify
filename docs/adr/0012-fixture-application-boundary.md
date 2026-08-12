# ADR-0012：Fixture Application Command、Identity 与 Handler 边界

- Status: Proposed
- Date: 2026-08-12
- Owner / Reviewer: S-5.6 / Dev-Lead、QA-Lead
- Depends on: ADR-0003, ADR-0008, ADR-0011
- Tracking: Issues #17, #21, #27

## Context

`quantverify/core/ports.py` 的早期 `DataProvider`、`Strategy`、`ResearchEngine` 与 `ResultStore` 是尚无调用者的占位协议，签名和已实现的 strategy、`LongFlatReferenceEngine`、Metrics v1、`RunArtifactStore` 均不一致。CLI 若直接依赖这些占位协议，会把业务编排、身份和数据准入逻辑重新塞进 shell。

现有 `ExperimentConfig` 也没有绑定 reference engine 必需的 `initial_cash`，以及 Metrics v1 必需的 annualization、ddof、return basis 和 risk-free policy。composition root 使用匿名默认值会导致相同 experiment/run identity 产生不同科学结果。

此外，`ReferenceResult` 没有单独的 opening-equity observation date。首个 session 开盘交易后只有当日收盘 `PortfolioPoint`；在 CORE-06 冻结 opening anchor 与 first-return convention 前，不能无歧义构造完整 `MetricInput` 或宣称 artifact v2 可重放。

## Decision

### 1. FixtureRunSpec 补齐实验身份未覆盖的科学输入

新增 `FixtureRunSpec v1`，显式绑定：

- `mode=fixture` 与一个显式 `fixture_id`；
- 既有 `ExperimentConfig`；
- 精确 consumed session range 及 schedule id/content hash/count；
- reference execution `initial_cash`；
- Metrics v1 的 return basis、annualization、ddof 与 risk-free policy；
- 当前唯一支持的 typed `DailyTrendParameters(window)`。

`fixture_run_spec_id` 对完整、重验证后的 spec 计算；新 identity payload 将等价时刻统一为 UTC、将 Decimal 按数值规范化（例如 `10000` 与 `10000.00` 相同），但不修改既有全局 identity 或旧 experiment ID。`run_id` 对 `legacy experiment_id + fixture_run_spec_id + RuntimeContext` 计算：legacy ID 是兼容锚点，避免两个旧 experiment identity 即使新科学 payload 等价也共享一个 run ID。artifact root、输出路径和 observation clock 不进入科学或运行环境 identity。

既有 `ExperimentConfig.experiment_id` 保持不变；不得静默把新增字段塞入旧 identity。

### 2. v1 capability matrix 是封闭集合

CORE-05A 只允许：

- `DataSnapshot` fixture，且 `fixture_id == dataset_id`；snapshot 的自由文本 `source` 不是 admission authority，CORE-05B 必须与 SW-03 registry 返回的完整 bundle 精确匹配；
- 单资产日线 `daily_trend`，参数只有严格正整数 `window`；
- reference engine；
- BAR_CLOSE decision、NEXT_OPEN execution、lag=1、fractional=true；
- commission/slippage bps，且 slippage < 10000；minimum commission 与 stamp duty 必须为零。

策略 version/code hash 与 engine version 仍必须由后续静态 registry 精确匹配；未知或不支持能力 fail closed。现有 `ma_cross(short_window,long_window)` YAML 不满足该契约，不能临时映射为单窗口 SMA。

S1-S4 需要各自显式 adapter 与周期/schedule 输入；S5 还需要 DatasetBundleRef、allocator 与多资产 engine。本 ADR 不宣称支持它们。

### 3. Command 与 inbound handler

冻结 `PlanFixtureCommand`、`RunFixtureCommand`、`InspectRunCommand`，以及 `PlanResult`、artifact-v1-only `InspectResult`。`PlanResult.disposition=structurally_ready` 只表示 DTO、身份和静态 capability 结构通过；它不是 registry-backed fixture admission，也不授权执行。

CORE-05A 只公开：

- `PlanFixtureHandler.handle(command) -> PlanResult`；
- `InspectRunHandler.handle(command) -> InspectResult`。

`RunFixtureCommand` 仅保留版本化输入形状；在 CORE-06 冻结 opening-equity/first-return、完整 MetricInput lineage 与 artifact v2 前，**不提供 `RunFixtureHandler` 或 `RunReceipt`**。这使未满足的证据依赖成为编译/导入层面的缺失能力，而不是运行时可绕过的布尔开关。

旧 `core/ports.py` 暂时保留以避免未声明的 source break，但新 application 不得使用它；项目 0.2 可在确认无外部消费者后移除。

### 4. Fixture 与 real-data 模式隔离

fixture command 只接受 `DataSnapshot`。出现 `DatasetReleaseRef` 必须在 resolver/provider/engine/store 调用前拒绝。

真实数据未来只能消费 A4 controlled resolver 返回的受信 release/bundle；公开可构造的 `DatasetReleaseRef` 不是 authority。本 ADR 不创建 real-data composition root，也不注入 AkShare、Tushare、yfinance、CaptureStore 或任何网络 client。

`ConsumedSessionRange` 是 identity-bearing request，但不自行证明 schedule 权威性或完整 bars；SW-03/CORE-05B preflight 必须把它与显式注册 fixture 的 exact schedule/bars 对齐，不能从 `TimeRange.start/end.date()` 推断。

### 5. Inspect 与错误边界

`InspectRunCommand` 只接受显式、store-root-relative、canonical POSIX JSON path；absolute、`..`、backslash、控制字符和任何 `latest` path segment/filename 均拒绝。artifact v1 的 `InspectResult` trust scope 固定为 `artifact_v1_integrity_only`，不得称为 verified dataset/release 或 replayable fixture run。

稳定 CLI exit mapping：config=2，fixture/preflight/real-data unavailable=3，execution=4，artifact=5，internal=70。`ApplicationFailure` 只携带固定 error code，不接受原始 exception message，避免 credentials、环境变量、host path 或 traceback 越过 CLI 边界。`ApplicationFailure` 和派生身份的 `PlanResult` 在序列化前完整重验证，unsafe `model_copy()` 不能直接生成可信 JSON 输出。

## Deferred Hard Gates

CORE-06 必须先冻结：

1. opening-equity anchor 与 first-return convention；
2. 完整 `MetricInput` content identity 和 calculator/version；
3. artifact v2 对 FixtureRunSpec、execution、result、MetricInput 与 MetricSet 的完整 lineage；
4. v1 verified read 兼容与 v1/v2 schema dispatcher。

SW-03 必须提供显式 registry、immutable fixture bundle、ordered bars 和 exact schedule identity。两者完成后，CORE-05B 才能实现 preflight、SMA3 adapter 与 run handler。

## Non-goals

- 不实现 handler、CLI、composition root 或 project script；
- 不实现 FixtureBundle/registry；
- 不修改 artifact v1 bytes 或 store API；
- 不实现 metrics conversion、provider、A4、real-data mode 或多资产 execution；
- 不扫描目录、不接受 implicit latest、不做 dynamic import。

## Review Gate

ADR 在 contract PR 通过 S-5.6、Dev-Lead 与独立 QA 对抗 review 后才能改为 `Accepted`。
