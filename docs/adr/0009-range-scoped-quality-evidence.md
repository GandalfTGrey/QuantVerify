# ADR-0009：Range-scoped Quality Evidence 与 Research Eligibility

- Status: Proposed
- Date: 2026-08-11
- Owner: Argus
- Reviewer: S-5.6
- Depends on: ADR-0004, ADR-0006, ADR-0007
- Tracking: Issue #10

## Context

现有 `CrossSourceValidator` 将单日价格差异、来源缺失与整体数据准入绑定在一个 PASS/WARNING/FAIL 结果中。这个模型适合早期异常探针，但无法安全扩展到长历史、多来源和多资产研究：一个发生在研究区间之外的历史异常会污染整个数据集状态，而单一验证源缺失也容易被错误解释为已有来源的数据本身无效。

QuantVerify 需要同时保存两种不同事实：

1. **完整历史上发现了什么异常或不确定性；**
2. **在某一精确研究区间和某一版本化 policy 下，数据是否具备研究准入条件。**

这两个问题必须分离，否则数据质量系统会把异常检测变成过度阻塞，也无法解释同一历史数据为何能支持 2015–2026 的实验却不能支持 1999–2026 的实验。

## Decision

### 1. Finding、Check Status 与 Eligibility 分离

A3 引入三层语义：

```text
immutable findings / evidence
        -> check results
        -> policy evaluation for requested range
        -> range eligibility
```

- `QualityFinding` 表示可重放的异常证据，不直接保存 `eligible=true/false`；
- `CheckResult` 表示一个检查器本次运行的 `pass / warning / fail / incomplete / not_applicable`；
- `RangeEligibility` 只回答当前 `requested_start..requested_end` 在记录的 policy 下是 `eligible / ineligible / incomplete`。

### 2. 完整历史 Finding 永久可见，但只按区间交集影响 Eligibility

每个 finding 必须带 `affected_start` / `affected_end`。Eligibility 只使用与请求研究区间相交的 finding 做 gate。

例如：QQQ 在 2002-11-01 的 unresolved cross-source conflict 必须继续出现在完整报告中，但它本身不得让只请求 2015–2026 的研究变成 INVALID。

### 3. Verification incomplete 不等于 canonical value invalid

`source A 有 session、source B 缺 session` 是验证覆盖不足的证据，不自动证明 A 的值错误。是否要求每个 session 至少两个来源由 `QualityPolicy` 决定，而不是全项目硬编码。

因此 dual-source requirement 是 dataset/policy-level setting，可设置为 optional 或 required；任何情况下都禁止平均冲突来源或按策略收益选择来源。

### 4. 质量报告必须绑定不可变 Lineage

每个 `DataQualityReportV2` 必须引用构成证据的：

```text
capture_hash
manifest_hash
provider
endpoint
capture_schema_version
adapter_version
request_fingerprint
```

A3 不允许通过 live provider 重新抓取数据，也不允许自行解析 CaptureStore 私有目录来补 lineage。CaptureStore 公共契约不足的问题单独由 Issue #11 审计和修复。

### 5. Policy 与检查实现均版本化

`QualityPolicy` 至少记录：

- policy id/version；
- cross-source requirement；
- field tolerance；
- revision handling。

检查结果同时记录 `check_id` 和 `check_version`。阈值或检查语义变化必须生成新的 policy/check identity，不得静默重写旧报告。

### 6. Cross-source price 使用对称相对差

对 compatible raw price field 使用：

```text
abs(a - b) / ((abs(a) + abs(b)) / 2)
```

再转换为 bps。这样比较不依赖人为指定所谓 primary source 作为分母。

Adjusted/derived series 的比较必须等到双方 adjustment semantics 可证明兼容；A3 不把 AkShare `qfq` 或 Yahoo `Adj Close` 自动提升为 total return。

### 7. Provider revision 是 Evidence，不默认等于研究失败

同一 provider + endpoint + semantic request 的两个 capture content hash 不同，应形成 revision finding 并标记具体变化 session/field。是否因此阻塞请求区间由 policy 决定；后续 A4 必须让 revision 产生新的 DatasetRelease identity/review 证据。

### 8. 报告身份必须可离线确定性重建

报告 identity 由以下科学输入与结果决定：

- asset/frequency/calendar/adjustment semantics；
- requested/observed range；
- policy version；
- ordered lineage refs；
- check versions；
- canonical findings/results。

墙钟执行时间属于运行 metadata，不进入科学报告 identity。

## Initial A3 Checks

第一阶段实现：

1. schema contract evidence；
2. session uniqueness / monotonicity；
3. OHLC finite/positive/internal consistency；
4. volume finite/non-negative；
5. calendar membership；
6. per-source coverage；
7. requested-range aggregate coverage；
8. cross-source overlap；
9. field-aware cross-source OHLC tolerance；
10. provider history revision；
11. explicit adjustment semantics evidence。

Corporate-action window 与 adjusted-return comparison 保留 registry 扩展点，不在本 ADR 中假装已有可靠输入。

## Consequences

- 同一完整历史可以对不同请求区间产生不同、可解释的 eligibility；
- 数据异常不会被隐藏，但区间外异常不再无条件阻塞研究；
- 双源校验从“全局真理规则”变为版本化 evidence policy；
- 后续 A4 `DatasetRelease` 可以直接消费 range eligibility，而无需重新解释 raw findings；
- 报告模型和测试数量增加，但换来可追溯、可重算和可扩展的数据质量语义。

## Non-goals

- 本 ADR 不创建 Gold DatasetRelease；
- 不决定 canonical provider 或 source ranking；
- 不实现 corporate-action adjustment engine；
- 不改变 CaptureStore A2 实现；
- 不允许 Quality Suite 自动运行策略或 Promotion。

## Review Gate

ADR 在 S-5.6 对 Issue #10 / Draft PR 完成语义 review 并决定合并后改为 `Accepted`。在此之前实现作为 proposed contract 接受 CI 与 adversarial review。