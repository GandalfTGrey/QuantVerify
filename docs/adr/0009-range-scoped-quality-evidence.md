# ADR-0009：Range-scoped Quality Evidence 与 Research Eligibility

- Status: Accepted
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

### 3.1 A3 v1 的独立信源身份固定为 provider

`minimum_sources_per_session=2` 表示至少两个**独立 provider authority**，而不是两个 Python source objects、两个 capture、两个 endpoint 或同一 vendor 的两个历史版本。

A3 v1 明确定义：

```text
independent_source_key = casefold(QualityEvidenceRef.provider)
```

因此 active quality source set 必须满足：

- `evidence_id` 唯一；完全重复的 observation 不得重复计数；
- provider authority 比较使用 ASCII provider id 的大小写无关形式；仅改变大小写不得伪装成第二个信源；
- 每个独立 `provider` 最多出现一个 current active observation；
- 同 provider 的旧/新历史 capture 应进入 `RevisionPair`，不得伪装成两个 independent verifier；
- requested-range coverage 对每个 session 统计的是 distinct provider identities；
- pairwise cross-source overlap / OHLC comparison 只允许发生在不同 provider 之间。

两个 endpoint 即使来自同一 provider，也不构成独立验证来源。未来若业务确实需要更细的 source-authority 语义，必须通过新的 versioned policy/ADR 显式修改，不能静默改变 `provider` 的含义。

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

`content_hash` 对调用方提供的完整 normalized bar **序列**做 canonical SHA-256，覆盖行顺序以及：

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

行顺序是科学输入的一部分，不得在 identity 计算前排序。否则相同 rows 的有序与倒序输入会共享一个 normalized identity，却得到不同的 monotonicity 结论。`non_monotonic_sessions` finding 只覆盖发生倒序的相邻 session pair 的最小日期区间，不得用整份历史的 min/max 扩张 finding、污染不相交的后续研究区间。

质量专用 canonicalization 会将非有限 Decimal/float 编码为显式 evidence token，使 NaN/Infinity 异常行也具有完整、可重复的内容 identity，而不是回退到占位 hash。

`QualitySourceData` 在正常构造路径下验证 `NormalizedInputRef.content_hash` 与实际 bars 一致；`QualitySuite.evaluate()` 会在公开计算边界再次重建 evidence/input envelope、重算完整 bars hash，并检查 session/timestamp/asset/source 的结构契约。测试中的 adversarial fixture 可以绕过上游 Pydantic 构造以产生 OHLC/volume finding，但不能绕过 A3 的内容 identity。

A3 不允许通过 live provider 重新抓取数据，也不允许自行解析 CaptureStore 私有目录来补 lineage。生产入口必须携带已合并的 `CaptureStore.load_verified()` / `VerifiedCapture` 完整对象，而不是由调用方手填一组看似合法的 hash 字符串。A3 在 provenance adapter 与 suite 计算边界都会重新构造并校验 `VerifiedCapture`，然后从中派生 `QualityEvidenceRef`；unsafe `model_copy`、嵌套 manifest/license/capture 篡改或声明 evidence 不一致均 fail closed。

测试可以通过显式 adversarial fixture 绕过 normalized bar 的上游构造，以验证质量检查本身；但不能绕过 verified raw lineage 后仍生成生产级 `ELIGIBLE` 报告。

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

若请求区间内没有任何 expected exchange session，A3 v1 返回 `INCOMPLETE`，不得用空集合的真空逻辑产生 `ELIGIBLE`。Calendar artifact 的交易所权威性仍由后续 verified calendar loader / A4 pin 负责。

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

Adjusted/derived series 的比较必须等到双方 adjustment semantics 可证明兼容；A3 不把 AkShare `qfq` 或 Yahoo `Adj Close` 自动提升为 total return。A3 v1 仅对 `RAW` 日线执行 cross-source OHLC compare；`SPLIT_ADJUSTED` / `TOTAL_RETURN` 会产生 `unsupported_adjustment_semantics` 并将区间标为 `INCOMPLETE`，直到 point-in-time corporate-action policy 被接受。

### 9. Provider revision 是 Evidence，不默认等于研究失败

同一 provider + endpoint + semantic request 的两个 capture content hash 不同，应形成 revision finding 并标记具体变化 session/field。是否因此阻塞请求区间由 policy 决定；后续 A4 必须让 revision 产生新的 DatasetRelease identity/review 证据。

报告 context 还必须绑定每个 revision pair 的 previous/current raw evidence 与 normalized input refs。即使两个 revision 输入的 OHLCV 恰好相同、没有产生 field-change finding，更换任一 observation 也必须改变 `report_id`。

### 10. 报告身份必须可离线确定性重建

报告 identity 至少由以下科学输入与结果决定：

- asset/frequency/adjustment semantics；
- requested/observed range；
- raw evidence refs；
- ordered normalized input refs；
- ordered revision raw/normalized input refs；
- exact expected-session set identity；
- full policy content identity + governance labels；
- check versions；
- canonical findings/results。

`report_id`、`finding_id`、`evidence_id`、`input_id` 与 policy `content_hash` 在计算前都重新验证完整模型；`DataQualityReportV2` 还会从 findings 重新推导 blocking/incomplete/warning ids 与 eligibility status，并绑定固定的 suite producer id/version、完整 check registry 与 report content hash。冻结模型内的 finding values 和 check metrics 使用递归 immutable mapping，避免对象创建后 identity 漂移。

必须区分 **deterministic integrity** 与 **authenticity**：没有私钥或外部 append-only anchor 的 Pydantic/JSON DTO 无法证明“这个对象一定由某个函数创建”。因此，反序列化的 `DataQualityReportV2` 只是可携带的确定性证据 DTO，不能仅凭其自洽 hash 晋升为 A4 Gold 输入。任何下游 eligibility assertion 必须调用 `QualitySuite.verify_report(...)`，携带完整 `VerifiedCapture`、normalized bars、exact sessions、policy 与 revisions 重新运行 suite，并要求结果逐字段相等。A4 在该 replay gate 落地前保持阻塞；不得直接消费孤立报告中的 `eligibility=ELIGIBLE`。

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

Corporate-action window 与 adjusted-return comparison 保留 registry 扩展点，不在本 ADR 中假装已有可靠输入。A3 v1 的输入类型是日线 `NormalizedBar`；周/月 `DerivedPeriodBar` 不得用 frequency 标签冒充进入本套检查。

## Consequences

- 同一完整历史可以对不同请求区间产生不同、可解释的 eligibility；
- 数据异常不会被隐藏，但区间外异常不再无条件阻塞研究；
- 双源校验从“全局真理规则”变为版本化 evidence policy，并且只按独立 provider 计数；
- normalized rows、normalizer、policy 内容、calendar session set 的任何科学变化都会改变报告 identity；
- unknown normalized schema fail closed，而不是静默 PASS；
- 后续 A4 `DatasetRelease` 只有在 `QualitySuite.verify_report(...)` 对完整输入闭包重放成功后，才可以消费其返回的 range eligibility 和 immutable scientific input refs；A4 无需自行重新解释 raw findings，但不得绕过 replay gate；
- `normalized-bar-v1` 在 A3 identity/evaluation 边界只接受最多 64 位有效数字、非零值 adjusted exponent 绝对值不超过 1000 的有限 Decimal。超出该研究数据域必须在生成 report 前 fail closed；此前 ambient Decimal context 下对超长系数或极端 exponent 产生的 hash/比较结果不构成受支持的历史 identity。普通行情数值的既有 report identity 不变；
- cross-source bps 阈值分类使用精确有理数交叉比较；展示性 bps 数值才使用 suite 固定的 Decimal context。宿主 precision、rounding 与 traps 不得改变 finding/status/report identity；
- 报告模型和测试数量增加，但换来可追溯、可重算和可扩展的数据质量语义。

## Non-goals

- 本 ADR 不创建 Gold DatasetRelease；
- 不决定 canonical provider 或 source ranking；
- 不实现 corporate-action adjustment engine；
- 不改变 CaptureStore A2 实现；
- 不允许 Quality Suite 自动运行策略或 Promotion。

## Review Gate

ADR 已由 S-5.6 在 PR #58 的最终候选 SHA 完成量化、架构与因果语义 review，并通过独立 QA 对抗重放。后续语义变更必须新建 ADR 或将本 ADR 显式标记为 `Superseded`，不得静默改写已接受契约。
