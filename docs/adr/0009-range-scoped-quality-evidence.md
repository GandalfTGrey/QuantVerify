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

同时，报告 identity 必须绑定真正参与计算的科学输入，而不仅是 raw capture lineage 或人类可读的 policy/version 标签。否则两个不同 normalized datasets 或两个不同阈值 policy 可能得到同一个 `report_id`，破坏可审计性。

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

### 4. 质量报告必须同时绑定 Raw lineage 与 Normalized input identity

每个 source 的 raw evidence 继续记录：

```text
capture_hash
manifest_hash
provider
endpoint
capture_schema_version
adapter_version
request_fingerprint
```

但 raw capture identity **不能替代** normalized input identity。A3 同时引入 `NormalizedInputRef`：

```text
content_hash        # full SHA-256
schema_version
normalizer_id
normalizer_version
row_count
```

`content_hash` 对完整、确定性排序后的 normalized bars 做 canonical SHA-256，覆盖：

```text
asset
session
session_open_at
session_close_at
available_at
OHLCV
source semantics
```

因此，即使 raw evidence 相同、所有 quality checks 都 PASS，只要任一 normalized bar 内容或 normalizer identity 改变，`report_id` 也必须改变。

`QualitySourceData` 在正常构造路径下验证 `NormalizedInputRef.content_hash` 与实际 bars 一致；测试中只有显式 adversarial fixture 可以绕过该边界，用于验证 Quality Suite 的 defense-in-depth。

A3 不允许通过 live provider 重新抓取数据，也不允许自行解析 CaptureStore 私有目录来补 lineage。CaptureStore 公共 replay provenance 的不足继续由 Issue #11 独立处理。

### 5. Policy 内容 identity 与标签 identity 分离

`policy_id/version` 是治理标签，不足以证明 policy 内容未改变。因此 `QualityPolicy` 对完整 policy 内容计算 full SHA-256 `content_hash`，并将其绑定到 `QualityEvaluationContext.policy_hash`。

被 hash 的 policy 内容包括：

- accepted normalized schema versions；
- cross-source requirement；
- price pass / warning tolerances；
- revision handling；
- 以及后续所有会影响 scientific conclusion 的 policy 字段。

因此即使人为错误地复用了同一个 `policy_id/version`，只要阈值或规则内容改变，报告 identity 仍然不同。

检查结果同时记录 `check_id` 和 `check_version`。检查语义变化必须更新 check version，不得静默改写旧报告。

### 6. Exact expected-session set 进入报告 identity

仅记录 `calendar_id="XNYS"` 不能证明某次评估实际使用了哪些 session。A3 引入 `ExpectedSessionSetRef`：

```text
calendar_id
content_hash        # full SHA-256 of exact de-duplicated session set
session_count
first_session
last_session
```

报告因此可以证明当时实际用于 coverage/calendar checks 的精确 session 集合，而不是依赖未来可能改变的 calendar-library 行为。

### 7. Normalized schema contract fail closed

`schema_contract` 不再只是列出版本后永远 PASS。`QualityPolicy.accepted_normalized_schema_versions` 明确声明可接受 schema；未知或不兼容的 normalized schema 产生：

```text
check_status = INCOMPLETE
finding_code = unsupported_normalized_schema
```

若该 finding 与 requested range 相交，则 research eligibility 也是 `INCOMPLETE`。系统不会把未知 schema 当成已验证数据继续研究。

### 8. Cross-source price 使用对称相对差

对 compatible raw price field 使用：

```text
abs(a - b) / ((abs(a) + abs(b)) / 2)
```

再转换为 bps。这样比较不依赖人为指定所谓 primary source 作为分母。

Adjusted/derived series 的比较必须等到双方 adjustment semantics 可证明兼容；A3 不把 AkShare `qfq` 或 Yahoo `Adj Close` 自动提升为 total return。

### 9. Provider revision 是 Evidence，不默认等于研究失败

同一 provider + endpoint + semantic request 的两个 capture content hash 不同，应形成 revision finding 并标记具体变化 session/field。是否因此阻塞请求区间由 policy 决定；后续 A4 必须让 revision 产生新的 DatasetRelease identity/review 证据。

### 10. 报告身份必须可离线确定性重建

报告 identity 至少由以下科学输入与结果决定：

- asset/frequency/adjustment semantics；
- requested/observed range；
- raw evidence refs；
- ordered normalized input refs；
- exact expected-session set identity；
- full policy content identity + governance labels；
- check versions；
- canonical findings/results。

墙钟执行时间属于运行 metadata，不进入 scientific report identity。

## Initial A3 Checks

第一阶段实现：

1. normalized schema contract；
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
- normalized rows、normalizer、policy 内容、calendar session set 的任何科学变化都会改变报告 identity；
- unknown normalized schema fail closed，而不是静默 PASS；
- 后续 A4 `DatasetRelease` 可以直接消费 range eligibility 和 immutable scientific input refs，而无需重新解释 raw findings；
- 报告模型和测试数量增加，但换来可追溯、可重算和可扩展的数据质量语义。

## Non-goals

- 本 ADR 不创建 Gold DatasetRelease；
- 不决定 canonical provider 或 source ranking；
- 不实现 corporate-action adjustment engine；
- 不改变 CaptureStore A2 实现；
- 不允许 Quality Suite 自动运行策略或 Promotion。

## Review Gate

ADR 在 S-5.6 对 Issue #10 / Draft PR 完成语义 review 并决定合并后改为 `Accepted`。在此之前实现作为 proposed contract 接受 CI 与 adversarial review。