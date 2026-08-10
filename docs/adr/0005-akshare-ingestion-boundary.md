# ADR-0005：AkShare 数据接入边界

- Status: Accepted
- Date: 2026-08-10

## Context

M1 需要先以 AkShare 获取 QQQ/DIA 日线，但 AkShare 是聚合服务，接口响应的复权口径、历史修订与下载时刻不能直接等同于可验证研究数据。项目已在 ADR-0004 中规定 AkShare 是 Tushare primary candidate 的独立验证源。

## Decision

- `AkShareUSDailyProvider` 仅适配 `stock_us_daily` 的 `date/open/high/low/close/volume` 原始响应；缺字段、重复 session、非法数值和非交易日均 fail closed；
- 原始响应保留为带 `akshare` 来源标签的 `NormalizedBar`，不得在 adapter 中与其他来源混合或平均；
- `RawSnapshotWriter` 将 adapter 所见的完整响应规范化为内容寻址 JSON，以 exclusive-create 写入；每次抓取另写不可变 manifest，保存 SHA-256、抓取时刻和调整模式。相同内容可复用，内容不一致的同 hash 路径或 manifest 路径必须报错；
- `adjust=""` 映射为 `raw`；`adjust="qfq"` 至多声明为 `split_adjusted`，在分红与复权因子审计完成前不得声明为 total return；
- session open/close 由 `pandas_market_calendars` 的 `NYSE` 交易日历提供，覆盖 AkShare 当前 QQQ/DIA 可见历史，并包含休市和提前收市；QQQ 与 DIA 的 M1 日线使用这一共同的美国股票交易时段；
- 日线的 `available_at` 表示该 session close。所有 close-derived 信号仍须遵守 ADR-0002 的下一真实 session open 执行规则；
- AkShare 为可选的 `market-data` 依赖，导入核心领域层不依赖其 SDK。没有安装时给出可操作的错误。

## Consequences

该实现先使 AkShare 可复现地进入数据校验管线；它本身不构成 Tushare 双源通过、raw snapshot 持久化或可发布研究结论。后续 snapshot writer 必须保存供应商响应、抓取时间、内容哈希和 adapter 版本，然后才能创建 `DataSnapshot`。
