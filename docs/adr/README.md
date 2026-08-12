# Architecture Decision Records

ADR 记录已经接受、会影响多个模块或研究结论的技术决策。状态为 `Accepted` 的 ADR 是当前实现依据；若后续决策取代旧 ADR，旧文件保留并标记为 `Superseded`，不得静默改写历史。

冲突裁决顺序见 [ADR-0001](0001-architecture-governance-and-document-precedence.md)。

当前新增数据边界决策：

- [ADR-0006：Raw Capture 与 Normalization 的单次抓取边界](0006-raw-capture-normalization-boundary.md)
- [ADR-0007：Provider-agnostic CaptureStore](0007-provider-agnostic-capture-store.md)
- [ADR-0008：Reference Result 不可变产物与运行清单](0008-immutable-reference-result-artifacts.md)
- [ADR-0009：Range-scoped Quality Evidence 与 Research Eligibility](0009-range-scoped-quality-evidence.md) — Accepted
- [ADR-0010：市场序列、派生周期与显式交易 Session 契约](0010-market-series-and-session-contracts.md)
- [ADR-0011：DatasetReleaseRef 与真实数据实验边界](0011-dataset-release-reference-contract.md) — Accepted
- [ADR-0012：Fixture Application Command、Identity 与 Handler 边界](0012-fixture-application-boundary.md) — Accepted
