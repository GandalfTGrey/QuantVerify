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
2. `SessionSchedule` 表示所请求输入范围的完整、显式、带版本交易 session 集合。它包含实际开闭市时间、IANA timezone、calendar id/version，并对完整内容计算稳定身份。
3. 日线策略输入必须与传入 schedule 的 session 和开闭市时间精确一致。缺失、重复、额外或错位 bar 一律 fail closed；不得用“下一行”推断下一真实 session。
4. close-based signal 的 `decision_at` 使用输入的 `available_at`，并且必须早于下一真实 session open。`session_close_at` 只表示市场事件时间，不等于数据已经可用于决策。
5. `SeriesDescriptor` 统一记录 asset、frequency、adjustment mode、fixture/release 来源、内容 hash/schema、producer 版本和 calendar 版本。其完整内容产生稳定 `series_id`。
6. `DerivedPeriodBar` 只允许 weekly/monthly，记录 period/constituent range、实际与预期组成 session 数及两组 schedule identity、`complete`、period open/close、`available_at`、OHLCV 和 `SeriesDescriptor`。
7. `complete` 必须同时满足实际/预期组成数相等且实际/预期 schedule identity 相等，避免同数量的错误 session 集合伪装完整。默认策略不得消费 `complete=false` 的周期。

## 边界

- 本 ADR 冻结 QF-01 的输入输出契约，不实现重采样算法；
- A4 `DatasetRelease` 将定义正式 Gold release，当前 `SeriesDescriptor` 只提供可同时引用 fixture 和未来 release 的统一 lineage envelope；
- 当前 reference engine 仍是单资产 long/flat；本 ADR 不扩展 S5 多资产组合；
- `DatasetReleaseRef`、application ports 与 artifact v2 分别留给 CORE-03、CORE-05 和 CORE-06 的窄 PR。

## 后果

- 现有 SMA golden target 的 `decision_at` 从 session close 更新为 bar `available_at`；effective time 仍为下一真实 session open；
- QF-01 可以在不修改 core/data contract 的情况下实现假日短周、非交易月末、DST、partial period 和 truncation invariance；
- 调用策略时必须提供显式 schedule，测试和 application 不能再依赖 DataFrame 行位置代表交易日历；
- 未来 calendar、producer、adjustment 或 source content 的变化会改变 series identity，避免语义不同的序列共享身份。
