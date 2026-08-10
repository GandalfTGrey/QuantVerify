# ADR-0006：Raw Capture 与 Normalization 的单次抓取边界

- Status: Accepted
- Date: 2026-08-10
- Owner: Argus

## Context

当前 AkShare / yfinance adapter 同时承担网络抓取和 normalization。调用方若先使用 `fetch_daily_records()` 保存 raw snapshot，再调用 `load_daily()` 生成 `NormalizedBar`，provider 会再次访问网络。

供应商可能在两次请求之间发生历史修订、schema 变化或上游响应差异。因此系统可能保存 snapshot A，却实际用 response B 生成研究数据。此时即使 manifest 和 content hash 都存在，也无法证明 backtest dataset 真正来自被保存的 raw artifact。

此外，normalizer 能访问网络会让离线重放、deterministic tests 和数据谱系变得不可靠。

## Decision

建立显式数据边界：

```text
DataRequest
    -> Provider.fetch(...)
    -> RawCapture
    -> persist immutable capture
    -> Normalizer.normalize(RawCapture)
    -> NormalizedBar[]
```

规则：

1. 同一次 ingestion workflow 对某 provider request 只允许一次网络抓取；
2. `RawCapture` 是网络响应进入 QuantVerify 后的不可变边界对象；
3. normalization 必须从已经存在的 capture/records 执行，不得内部再次访问网络；
4. `load_daily()` 可暂时作为兼容 convenience API，但内部必须执行 `capture -> normalize(capture)`，不能分别 fetch 两次；
5. snapshot / manifest 后续必须引用对应 capture 的 content hash；
6. provider-native raw 信息应优先保留，canonical field pruning 只能发生在 normalization 层或明确的 adapter-canonical capture schema 中；
7. provider request 参数属于 capture identity/provenance 的组成部分，credential 除外。

## Initial Implementation Scope

第一阶段为兼容现有代码，允许 provider 暴露：

```python
capture_daily(...)
normalize_daily(capture, ...)
load_daily(...)
```

其中：

```python
load_daily(...):
    capture = capture_daily(...)
    return normalize_daily(capture, ...)
```

后续可进一步统一到 provider-independent `DataRequest` / `RawCapture` / `CaptureStore`。

## Consequences

### Positive

- snapshot 和研究数据可以来自同一实际响应；
- normalization 可离线重放；
- provider 网络行为与数据变换逻辑分离；
- 更容易增加 recorded fixtures、revision detection 和 provider-agnostic CaptureStore；
- 后续接入 Alpaca/Massive 等 source 时不必复制混合 fetch/normalize 模式。

### Cost

- provider API 增加一个显式 capture 对象；
- 现有 snapshot writer 需要后续适配通用 capture manifest；
- 部分测试需要新增“只抓取一次”和“normalize 不访问网络”的契约测试。

## Non-goals

本 ADR 不在第一阶段完成：

- corporate action adjustment engine；
- dataset release / range-scoped eligibility；
- provider license registry；
- available_at 时间语义重构；
- cross-source quality suite v2。

这些工作分别进入后续 ADR / PR，以保持当前变更可独立审核。
