# ADR-0013：可重放 Metrics v2 与 Fixture Run Artifact v2

- Status: Proposed
- Date: 2026-08-13
- Owner / Reviewer: S-5.6 / Dev-Lead、Q-Lead、QA-Lead
- Depends on: ADR-0003, ADR-0008, ADR-0012
- Tracking: Issues #17, #21, #27, #66

## Context

CORE-05A 已冻结 fixture run 的科学意图，但有意不提供 `RunFixtureHandler`。现有
`RunArtifactManifest v1` 只绑定 `DataSnapshot`、engine 和 `ReferenceResult`，没有绑定
fixture manifest、完整 `FixtureRunSpec`、targets、指标输入或指标输出；因此它只能证明一个
reference result 的内部完整性，不能证明一个完整 fixture 实验已被按同一组科学输入执行。

Metrics v1 也不能直接承载所有真实 engine 结果。它要求同时提供 equity 和 Decimal return 时，
每个 return 必须与相邻 equity 的精确有理数比率一致。例如 `10300 -> 10400` 的收益为
`1/103`，不存在有限 Decimal 表示；任何固定精度的小数都会被 v1 正确拒绝。放宽成容差、使用
进程默认 Decimal context，或分别计算后手工拼接一个 `MetricSet`，都会让相同运行身份对应不同
指标证据。

此外，reference engine 只输出每个 session close 的 `PortfolioPoint`，没有单独的开盘前 equity
observation。fixture v1 的第一个收益锚点必须明确，不能由 application 临时猜测。

## Decision

### 1. Metrics v1 保持不可变

`MetricInput v1`、`MetricSet v1`、其 calculator 和既有 artifact 均不修改、不放宽，也不做原地
migration。v1 继续服务已有手工指标 fixture 和兼容读取；CORE-06 新增独立的 v2 类型、factory、
calculator 与 identity namespace。

### 2. MetricInput v2 以完整 equity trajectory 为唯一收益权威

`MetricInputV2` 必须绑定：

- 固定 `metric-input-v2` schema；
- calendar id/version、return basis、annualization、strict non-negative ddof 和 risk-free policy；
- `opening_equity_convention=first_close_flat-v1`；
- 按 session 严格递增且至少两个元素的完整 equity observations；
- 由这些 equity **精确派生**的 `RationalReturnObservation`；
- `return_derivation_id=equity-ratio-rational` 与固定 version `1`。

`RationalReturnObservation` 使用最简、分母严格为正的整数 `numerator/denominator`；日期必须等于
后一个 equity observation 的 session。每项必须精确等于
`Fraction(current_equity) / Fraction(previous_equity) - 1`。`-1` 只允许为终端吸收态，零必须写成
`0/1`。Factory 从 equity 推导 rational returns；validator、content identity 和 persistence boundary
再次重导并逐项比较。调用者填写的 detached rational values 不是权威。

`EquityObservationV2` 的数值是 finite Decimal：第一项与所有非末项必须严格大于零；只有最后一项
可以等于零。零是破产吸收态，之后不得出现 observation 或 return。分子、分母、ddof 和全部 count
使用 `StrictInt`，明确拒绝 bool/float/string coercion。每个 Decimal 最多 64 位 coefficient、非零值
adjusted exponent 绝对值不超过 1000；每个 rational numerator/denominator 最多 4096 bits；fixture v2
最多 10000 个 equity/return/target/point/trade rows，单个 canonical evidence JSON 最大 32 MiB。超限在
hash、calculator 或 persistence 前使用固定 typed error fail closed。

输入 content identity 覆盖完整有序 equity、完整 rational returns、全部 policy 和 derivation version；
Decimal identity 使用明确 payload：零恒为字符串 `0`；非零为 sign、删除 coefficient 末尾零后的十进制
digits、同步增加后的 exponent。它不调用 `normalize()`，等值 scale 与 signed zero 收敛。

### 3. Metric calculator v2 使用固定数值环境

`MetricCalculatorRef` 固定绑定：

- calculator id/version；
- Decimal precision；
- rounding mode；
- `Emin`、`Emax`；
- 启用的 arithmetic traps；
- metric-set schema version。

`decimal-context-v1` 是 calculator ref 的组成部分，必须枚举 `prec=34`、
`rounding=ROUND_HALF_EVEN`、`Emin=-999999`、`Emax=999999`、`capitals=1`、`clamp=0`，以及
`InvalidOperation/FloatOperation/DivisionByZero/Overflow=true`、
`Underflow/Subnormal/Inexact/Rounded/Clamped=false`。每次计算都从该完整 record 新建 context 并
`clear_flags()`；不得复制宿主 flags/traps。numeric backend id/version 也进入 calculator ref；v2 baseline
是 `python-decimal/libmpdec` 与项目声明支持的 backend version range，跨 backend 的一致性必须由 golden
确认，不能仅凭同 calculator label 假定。

v2 baseline 为 precision 34、`ROUND_HALF_EVEN`，并在每次计算的 `localcontext()` 内显式设置全部
字段；不得读取或继承宿主的 precision、rounding 或 traps。Total return 和 MaxDD 从 equity 计算；
CAGR 使用明确 days/year；Volatility 和 Sharpe 将精确 rational returns 在该固定 context 内逐项转换，
再按声明的 periods/year、ddof 和 risk-free policy 计算。运算顺序属于 calculator version，不能被并行
求和或第三方库静默替换。

rational 转 Decimal 固定为按 observation 顺序执行 `Decimal(numerator) / Decimal(denominator)`，每项
只在上述 context 内舍入一次；均值使用从零开始的顺序加和再除 count；variance 使用相同顺序累计
`(r-mean)**2`；sqrt、CAGR power 与 annual-effective risk-free power 均调用 Python Decimal 对应操作，
调用顺序和异常映射属于 calculator version。InvalidOperation/DivisionByZero/Overflow 为
`FAILURE / numeric_error`；样本不足、非正 elapsed time、zero volatility 保持 `UNDEFINED` 的稳定 reason；terminal
bankruptcy 的 total/CAGR/max-drawdown 为有效 `-1`，其后不得计算复活路径。

`MetricSetV2` 必须绑定 `metric_input_content_hash` 和完整 calculator ref，并保持 VALID、UNDEFINED、
FAILURE 状态矩阵。其 content identity 覆盖所有结果。Calculator 输出前重验证 input；artifact 接受前
重新计算并要求完整 `MetricSetV2` 相等。不得把另一个 input 或 calculator 的指标拼接进来。

### 4. fixture v1 的 opening anchor 是首个 close 的已证明 flat equity

fixture-run v2 第一版只允许**完整消费一个 SW-03 bundle**，不支持任意切片：
`ConsumedSessionRange.start/end/count/schedule_id/schedule_content_hash` 必须逐字段等于 bundle 完整
schedule 的 requested bounds、session count、schedule id/content hash；engine bars、result points 和
metrics equity 必须覆盖其全部 sessions。prefix/suffix omission、相同 schedule hash 的手填 range 或只取
performance range 均拒绝。未来如需切片，必须先新增绑定 ordered-bar content hash 与派生 schedule hash
的 `ConsumedFixtureSliceV1`，不能复用本 ADR 的完整消费语义。

CORE-05B 只有在以下条件全部成立时，才能使用 `first_close_flat-v1`：

- bars、schedule 和 result points 非空且 session/timestamp 一一精确匹配；
- 第一个 point 的 cash/equity 都精确等于 `FixtureRunSpec.execution.initial_cash`；
- 第一个 point 的 quantity、target weight、actual weight 都为零；
- 不存在首个 session open 的 target 或 trade；
- 第一条及其后的 point、trade、target 都通过完整重验证。

第一条 equity observation 的日期是首个 session label，数值是第一个 close 的 flat equity；收益从
第二个 close 相对第一个 close 开始。该约定不宣称包含首个 session open-to-close return。任何首日
建仓、非 flat point、缺失 point 或未来 engine capability 必须 fail closed，直到新 opening convention
通过独立 ADR。

### 5. FixtureRunEvidence v2 是确定性 artifact 内容

小型 fixture 的 `fixture-run-evidence-v2` canonical JSON 必须包含并交叉验证：

- experiment id、fixture-run-spec id、run id 和完整 `FixtureRunSpec`；
- 完整、自校验的 SW-03 `FixtureManifest`，而不只是自由填写的 fixture/hash refs；
- strategy adapter id/version/code hash；
- 完整有序 `TargetPosition` 和其 content hash；
- engine id/version/code hash 与完整 `ReferenceResult`；
- `MetricInputV2`、其 content hash、`MetricCalculatorRef`、`MetricSetV2` 和 metric-set content hash。

`StrategyImplementationRefV1` 和 `EngineImplementationRefV1` 都包含 strict id、version、code hash，并
由显式静态 registry exact resolve。strategy ref 必须逐字段匹配 `ExperimentConfig.strategy`；engine ref
必须逐字段匹配 experiment engine 和 reference engine capability。`FixtureManifest.manifest_content_hash`、
`bundle_content_hash`、snapshot content/schema/source、asset/frequency/adjustment、完整 schedule identity、
spec consumed-session identity、cost bps、initial cash 与 metric policy 都分别进入 evidence identity；不能用
一句 DTO equality 或 generic ref 替代。

Validator 必须证明：spec 与 manifest 的 fixture/dataset/content/schedule identities 一致；bars、targets、
points、trades 的 asset/session/timestamps 一致；result 的 initial cash/costs 与 spec 一致；metrics equity
逐项等于 result points；全部派生 id/hash 可重算。任一 row 的缺失、增加、重排或修改都改变 artifact
identity 或被拒绝。

verified replay 不只检查自洽性：它必须从静态 registry 解析 strategy/engine implementation，在完整
manifest bars 与 schedule 上重新运行 strategy，逐项比较 ordered targets（含 decision watermark、next
open effective time、asset/weight）；再用 bars、targets、initial cash、commission/slippage 重跑 reference
engine并逐字段比较完整 points/trades/result；随后由 MetricInputV2 factory 和 calculator 重算 metrics。
任一步不相等都拒绝。自洽但非由注册实现生成的 targets/result/metrics 不是 verified evidence。

artifact content 不包含 `created_at`、store root、hostname 或绝对路径。v2 仍只适用于小型 fixture
JSON，不替代未来真实数据的 Parquet/DuckDB artifact 设计。

### 6. Manifest v2 与 v1 dispatcher

`run-artifact-manifest-v2` 记录 run/experiment/spec id、v2 artifact ref、runtime、created-at UTC observation
和 canonical relative content path。显式 inspector 先以严格、无重复键的最小 envelope 读取
`manifest_version`，随后只分派到已注册的 v1 或 v2 loader；未知版本拒绝。不得 fallback、目录扫描、
implicit latest、URL decode 或把 v1 当 v2 升级。

v1 loader、v1 bytes、v1 canonical path 和 `VerifiedRunArtifact` 保持兼容。v2 使用单独的 verified DTO，
不得用 generic `ArtifactRef` 或可自洽 Pydantic DTO 代替 store-backed replay。

新 dispatcher 只接受与版本对应的 canonical relative path grammar。它先以 duplicate-key rejecting JSON
读取一个只含 `manifest_version` 的受限 envelope，再由版本 loader 对完整原 bytes 做 canonical parse 和
path/hash/schema 验证；envelope 不能改写或重新序列化后再交给 loader。v1 可调用既有
`inspect_reference_result()`，但其 trust scope 仍是 artifact-v1 integrity-only，且不宣称具备 v2 hostile-FS
hardening；v2 使用 hardened regular-file/no-follow reader。URL decode、version fallback 和未知字段均拒绝。

v2 的两个相对路径是协议的一部分，只能由以下纯函数生成：

- evidence content：
  `artifacts/fixture_run_evidence_v2/<evidence_content_hash[0:2]>/<evidence_content_hash>.json`；
- observation manifest：
  `run_manifests_v2/<run_id>/<evidence_content_hash>/<YYYYMMDDTHHMMSSffffffZ>-<manifest_hash>.json`。

`YYYYMMDDTHHMMSSffffffZ` 必须由一个真实、aware 且已经规范为 UTC 的 `created_at` 以
`%Y%m%dT%H%M%S%fZ` 生成；loader 必须执行真实日历/时分秒解析和逐字 round-trip，不得只检查长度或数字位置。
manifest 内 v2 artifact ref 的 `kind=fixture_run_evidence`、`schema_version=fixture-run-evidence-v2`，其 URI
必须逐字等于上述 evidence content path；manifest path 必须同时逐字绑定 `run_id`、
`evidence_content_hash`、UTC stamp 和 `manifest_hash`。hash 均为 64 位小写十六进制，`run_id` 必须满足冻结
的 CORE-05A grammar。

两个函数都返回 strict POSIX relative path。每个 segment 必须是规范 ASCII，不允许空 segment、`.`、`..`、
反斜杠、控制字符、percent encoding、URL scheme、绝对路径或任何大小写形式的 `latest`；dispatcher/store
不会 URL decode 或 Unicode normalize 后再接受。loader 必须从已验证字段重新计算唯一预期路径并与调用路径
逐字比较。即使 bytes、hash 和内部字段已被攻击者自洽重算，任何不同目录层级、hash 分片、时间格式、扩展名
或字段到 segment 的映射也必须拒绝。

### 7. 发布必须复用 hardened immutable publisher

在实现 v2 store 前，先抽取或复用已经通过 CaptureStore 审计的同目录 staging、fsync、no-overwrite
hard-link、regular-file/no-follow collision verification、typed cleanup/error precedence 语义。不得复制当前
artifact v1 中较弱的 `path.read_bytes()` collision 路径。

handler 的顺序固定为：完整 command 重验证 -> exact registry resolve -> preflight -> strategy targets ->
engine -> MetricInputV2 factory -> MetricSetV2 calculator -> FixtureRunEvidenceV2 重验证 -> 一次 publication。
任何前置失败必须零写入。内容和 manifest 分别不可变、幂等；同 identity 不同 bytes、FIFO、directory、
symlink、partial/crash、concurrent reader/writer 均 fail closed。成功返回的 `RunReceipt` 只能引用 verified
v2 manifest/artifact，不提供 mutable latest。

必须区分三种 identity：`evidence_content_hash` 标识确定性 evidence bytes；`run_id` 标识科学 spec + runtime；
`manifest_hash` 标识一次带 `created_at` 的 observation manifest。write API 要求调用方提供并重验证一个 UTC
`created_at`，重试必须复用完全相同的 manifest bytes；同 run/content 允许 append-only 的多个 observation
manifest，但 receipt 只返回本次显式 path，不提供“最近一次”。同 canonical path 不同 bytes 是 collision。
二文件发布的保证是：preflight/strategy/engine/metrics/evidence validation 失败时零写；content 成功但 manifest
link/fsync 失败时可以留下无 manifest 引用、不可被 inspector 发现为 run 的 orphan content，绝不返回
receipt。只有 verified manifest 才使 content 成为 trusted run artifact；不虚构跨两个文件的 filesystem
transaction。orphan cleanup 是后续维护工具，不参与科学 identity。

## Required Black-box Gates

1. `10300 -> 10400` 等循环小数收益无需容差即可精确 replay；
2. 宿主 Decimal precision/rounding/traps 改变不影响 input、metric 或 artifact identity；
3. Decimal scale/signed zero 等价，长 coefficient 与极端 exponent 不碰撞；
4. equity 与 rational return 任一不一致、非最简分数或 `-1` 后复活均拒绝；
5. 首 session target/trade、非 flat opening point 或 first point != initial cash 均零写入失败；
6. bar/target/point/trade/metric row 缺失、额外、重排、timestamp/asset 变化均拒绝或改变 identity；
7. good MetricSet + wrong MetricInput/calculator/result 无法构造 trusted evidence；
8. unsafe top/nested `model_copy()` 在 id、serializer、handler、store loader 四个边界拒绝；
9. v1 golden manifest/result 仍逐 byte verified；unknown v2、moved manifest、noncanonical JSON、duplicate key、
   path escape、latest 和 self-consistent detached DTO 均不获得 verified authority；
10. publication 在 8 路相同/不同内容并发、hostile filesystem nodes、fd/close/fsync/link/cleanup failures 下
    保持 typed、atomic、no-overwrite；计算/验证失败零写，publication 失败无 verified manifest/receipt，允许
    明确记录的 orphan content；
11. full-bundle start/end/count/schedule hash 任一篡改、prefix/suffix omission 均拒绝；
12. 静态 registry code hash/version 不匹配，以及自洽但未由注册 strategy/engine 重放产生的 evidence 均拒绝；
13. 10000-row/32MiB/Decimal/rational bit limits 的边界内通过、边界外固定 typed fail closed。
14. v2 evidence/manifest 的错误但自洽路径变体（目录、hash 分片、run/evidence/manifest hash、UTC stamp、
    扩展名）均拒绝；等价 UTC instant 只生成同一规范 stamp，非法日期或时间不得通过。

## Deferred / Non-goals

- 不在本 ADR 支持真实 `DatasetReleaseRef`、多资产 S5、cash flow、deposit/withdrawal、首日持仓或日内收益；
- 不修改 Metrics v1 或 artifact v1 bytes；
- 不实现 CLI parser/formatter、provider、A4、catalog、Parquet 或动态 plugin；
- 不把 `STRUCTURALLY_READY` 提升为 registry admission；
- 不把 artifact hash 称为作者签名或真实性证明。trusted authority 仍来自显式 manifest anchor 和 verified store read。

## Merge Sequence

1. #63/#64 修复 exact Decimal identity；
2. SW-03 #62 合并并冻结 `FixtureManifest`；
3. CORE-06A：MetricInput/MetricSet v2 + calculator contract；
4. CORE-06B：shared hardened immutable publisher + artifact v2/dispatcher；
5. CORE-05B：registry-backed preflight/run handler；
6. #17 CLI shell/composition root。

本 ADR 只有在 Dev-Lead、Q-Lead/量化 reviewer 和独立 QA 完成 exact-head 对抗复核后才能从
`Proposed` 改为 `Accepted`。
