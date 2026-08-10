# ADR-0007：Provider-agnostic CaptureStore

- Status: Accepted
- Date: 2026-08-10
- Owner: T-5.6
- Depends on: ADR-0006

## Context

ADR-0006 建立了 `RawCapture -> offline normalization` 边界，但现有 `RawSnapshotWriter` 仍与 AkShare、资产和 adjustment mode 耦合，且无法直接离线重建通用 `RawCapture`。若每个 provider 分别实现 snapshot writer，会产生不同的 hash、manifest 和许可语义，破坏统一数据谱系。

## Decision

引入 provider-agnostic `CaptureStore`：

```text
one provider fetch
  -> deeply immutable RawCapture
  -> CaptureStore.write
       -> content object (hash covers provider/endpoint/request/records/schema)
       -> observation manifest (capture time/store time/adapter/license/path)
  -> CaptureStore.load
  -> offline normalization
```

规则：

1. content object 以 `RawCapture.content_hash` 寻址，内容相同可复用且不能覆盖；
2. `captured_at` 不进入 capture 内容身份，每次观测写入独立且同样内容寻址的 manifest；
3. manifest 必须记录 provider、endpoint、完整非凭据 request、capture schema、adapter version、记录数和 license profile；
4. token、cookie 和 API secret 禁止进入 request、capture、manifest 或路径；
5. replay 必须校验文件 SHA-256 以及 provider/endpoint/request/schema/record count；
6. 所有存储路径相对 store root，拒绝绝对路径和 `..` 逃逸；
7. normalizer 只接收 replay 后仍通过 adapter schema contract 的 capture；
8. 旧 `RawSnapshotWriter` 暂时保留兼容，不得用于新的 dataset release 流程，后续迁移后删除。

## Consequences

- 所有 provider 共用一套内容身份、manifest 和离线重放规则；
- 同一响应在不同时间获取时复用内容对象但保留各自观测证据；
- 数据许可成为每次 capture 的显式元数据；
- A3 Quality Suite 和 A4 Dataset Release 可以引用统一 capture hash；
- 写入内容成功但 manifest 失败时可能留下安全的 orphan content，可由后续维护工具清理，不允许自动覆盖或猜测修复。

## Non-goals

- 本 ADR 不定义 normalized dataset 的 columnar 格式；
- 不决定 provider 的真实性优先级；
- 不实现 corporate action adjustment；
- 不让实时网络调用进入 CI。
