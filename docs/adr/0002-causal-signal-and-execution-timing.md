# ADR-0002：信号与执行的因果时间语义

- Status: Accepted
- Date: 2026-08-10

## Context

日、周、月策略都可能在 period close 使用该 period 的完整 OHLC。若同价成交，会使用只有收盘后才确定的信息，产生执行层 look-ahead。单纯使用整数 `shift(1)` 又无法表达节假日、半日市和跨频率下一 session。

## Decision

- 每个市场 bar 显式包含 `session_open_at`、`session_close_at` 和 `available_at`，均为带时区时间；
- 每个 `TargetPosition` 显式包含 `decision_at` 与 `effective_at`；
- `effective_at > decision_at` 是领域不变量；
- M1 默认 period close 决策、下一真实交易 session open 执行，至少延迟 1 bar；
- 周/月 bar 由日线按交易日历重采样，指标在重采样序列上重新计算；
- 末尾没有下一 session 的信号不产生可执行 target；
- same-bar execution 不能作为普通配置开放，未来若需要必须建立独立、可审计的 intrabar 模型。

## Consequences

策略不能只返回无时间语义的布尔数组。Calendar adapter 成为正式依赖，pandas `resample("W")` 不能独自决定交易周期边界。结果可能比同收盘成交回测更保守，但具有可执行因果解释。
