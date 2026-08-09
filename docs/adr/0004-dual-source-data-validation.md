# ADR-0004：双源数据校验与冲突处理

- Status: Accepted
- Date: 2026-08-10

## Context

M1 使用 Tushare Pro 和 AkShare 获取 QQQ/DIA 日线。两者来源、字段、复权基准和历史覆盖不同。简单平均不能增加真实性，反而会创造不存在于任一来源的新价格。

## Decision

- Tushare `us_daily_adj` 是初始 primary candidate，AkShare 是 secondary verification source；
- raw OHLC 比较价格水平，adjusted series 主要比较收益与 corporate-action 区间；
- 每次抓取保存不可变 raw snapshot 和供应商 metadata；
- 默认 raw close 容差：10 bps 内 PASS、10-50 bps WARNING、超过 50 bps FAIL；
- 缺失 session、重复 session、资产身份不一致和无法解释的 corporate action fail closed；
- 不平均冲突值，不按策略收益高低选择来源；
- Level A 官方资料用于身份和关键冲突人工裁决；
- tolerance 是 versioned policy，修改后历史报告不得被静默重写。

## Consequences

正式数据接入需要额外存储和审计工作，部分实验会因源冲突无法运行。这是预期行为：数据不足应产生“无法验证”，而不是虚假精度。
