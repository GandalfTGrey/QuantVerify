# ADR-0010：市场序列、派生周期与显式交易 Session 契约

- Status: Accepted
- Date: 2026-08-12
- Owner: S-5.6
- Tracks: Issue #21, #22
- Reserved: ADR-0009 belongs to Argus A3 / PR #16

## 背景

现有 `BarFrequency` 只有日、小时和分钟，但已冻结的候选研究配置使用 `1w` 与 `1mo`。同时，`price_above_sma_targets()` 把输入中的下一行视为下一交易 session；若中间缺 bar，策略会在更晚日期成交而不报告数据缺口。

另一个更直接的因果问题是：`NormalizedBar.available_at` 可能晚于 `session_close_at`，现有 target 却把 `decision_at` 写成 close。这样产生的谱系会声称策略在输入实际可用前已经完成决定。

周/月实现还缺少统一的频率、调整口径、上游 lineage、组成区间、完整性和可用时间契约。若让每个策略或 resampler 自行定义，实验身份和未来数据防线会分裂。

## 决定

1. `BarFrequency` 增加正式的 `1w` 与 `1mo`；二者表示本地从更细频率派生的研究周期，不授权下载供应商周/月线。
2. `CalendarArtifactRef` 绑定 calendar id/version、IANA timezone、来源/version、完整 artifact 内容 hash 和版本化 session-label policy。`SessionSchedule.content_hash` 另外覆盖请求日期范围、calendar ref 和 UTC 规范化后的精确 session 集合；对象加载和 identity 计算时必须重新验证该 hash，因此不能在保持内容身份不变的同时删减、替换或重排 session。领域模型对已构造的嵌套 Pydantic 实例也必须重新验证；schedule factory 和策略计算边界必须重建 schedule 与所有 bars，不得信任绕过验证的 `model_copy()` 顶层或嵌套输入。生产调用方只能使用由已验证 calendar artifact 唯一派生并按请求区间固定的 schedule，禁止从待验证 bars 反向自举 schedule。
3. 日线策略输入必须与传入 schedule 的 session 和开闭市时间精确一致。缺失、重复、额外或错位 bar 一律 fail closed；不得用“下一行”推断下一真实 session。
4. close-based signal 的 `decision_at` 等于该信号实际消费的全部 observations 的 `max(available_at)`，并且必须早于下一真实 session open。SMA 使用完整 lookback window 的 availability watermark；后续 stateful feature 必须显式给出等价 dependency watermark。`session_close_at` 只表示市场事件时间，不等于数据已经可用于决策。
5. schedule identity 把所有 session 时间规范化为 UTC instant 后再 hash；相同 instant 的不同 offset 表达必须产生相同 identity。timezone 仍作为 calendar 语义进入 identity。现有 experiment/run/artifact 的全局 datetime canonicalization 不在本 PR 改变。
6. M1 的 ETF/equity calendar 使用 `close_local_date`：session label 必须等于 calendar timezone 下的 close date。`open_local_date` 与 `calendar_defined` 是显式、版本化的未来市场 policy；跨夜市场只能使用经审计 calendar artifact 的适用 policy，不能取消标签校验后静默接入。
7. `SeriesDescriptor` 统一记录 asset、frequency、adjustment mode、fixture/release 来源、内容 hash/schema、producer 版本和完整 calendar artifact。其 `descriptor_id` 表示输入/变换语义，不冒充派生输出内容 identity。
8. `DerivedPeriodBar` 只允许 weekly/monthly。Weekly 使用 exchange trading-date label 所在的 Monday–Sunday 周；Monthly 使用自然月首日至末日。假日短周和月末非交易日由完整 expected schedule 表达，不使用周末占位。
9. 派生周期同时携带完整 expected schedule、截止时实际 constituent schedule、与 constituents 一一对应的 availability 和 `cutoff_at`。实际 sessions 必须是 expected sessions 的严格前缀，不允许中间缺口伪装成普通 partial period。`completeness` 是派生状态：两组 sessions 完全相等为 `complete`；cutoff 早于第一个未纳入 session 的 close 为 `partial_cutoff`；否则为 `incomplete_missing_data`。`complete` 只是该状态的布尔投影，调用方不能直接写入。
10. period `available_at` 是全部 constituent availability 的最大值；每个 constituent 必须在自身 session close 后可用且不晚于 cutoff。period open/close、constituent range/count 也由实际 schedule 派生，不能由调用方填写互相矛盾的值。
11. `period_bar_id` 绑定 descriptor、实际/预期 schedule identity、availability watermark 输入、cutoff 和完整 OHLCV；生成 identity 前必须重新验证完整对象并将 datetime 规范化为 UTC instant，从而拒绝绕过 Pydantic 的不安全复制、可变容器和宿主时区差异。

## 边界

- 本 ADR 冻结 QF-01 的输入输出契约，不实现重采样算法；
- A3 的 expected-session dates/calendar 必须与 `SessionSchedule` 的 date set/calendar 对齐；A4 还需绑定 calendar version/artifact identity。#16 rebase 时建立这一公开桥接，不在本 PR 修改 Argus 文件；
- `SessionSchedule.content_hash` 证明对象内部内容与身份一致，但不单独证明它是交易所权威日历。verified calendar loader 必须校验 `CalendarArtifactRef.content_hash`、由 artifact 唯一生成请求区间 schedule，并由 A4/research application 绑定预期的 schedule content hash；直接公开构造仅用于已验证的边界内部和固定 fixture。
- A4 `DatasetRelease` 将定义正式 Gold release，当前 `SeriesDescriptor` 只提供可同时引用 fixture 和未来 release 的统一 lineage envelope；
- 当前 reference engine 仍是单资产 long/flat；本 ADR 不扩展 S5 多资产组合；
- `DatasetReleaseRef`、application ports 与 artifact v2 分别留给 CORE-03、CORE-05 和 CORE-06 的窄 PR。

## 后果

- 现有 SMA golden target 的 `decision_at` 从 session close 更新为完整窗口 availability watermark；effective time 仍为下一真实 session open；
- QF-01 可以在不修改 core/data contract 的情况下实现假日短周、非交易月末、DST、partial period 和 truncation invariance；
- 调用策略时必须提供独立、带谱系的显式 schedule；测试和 application 不能再依赖 DataFrame 行位置或从 bars 构造的 schedule 代表交易日历；
- `tzdata` 成为核心依赖，使 IANA timezone 验证不依赖宿主机是否恰好安装系统 tzdb；
- calendar、producer、adjustment 或 source content 的变化会改变 descriptor identity；实际 period 内容变化会改变 period-bar identity。
