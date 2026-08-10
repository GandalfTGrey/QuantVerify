# ADR-0001：架构治理与文档优先级

- Status: Accepted
- Date: 2026-08-10

## Context

QuantVerify 同时维护架构、数据完整性、研究协议、策略宇宙、实施计划和机器可读 StrategySpec。这些文档来自不同阶段，可能对同一问题给出不同建议。机械合并会留下互相矛盾的规则，按“最新文件覆盖”也可能降低研究完整性。

## Decision

发生冲突时按以下顺序裁决：

1. 用户最新明确决定及适用的安全、法律约束；
2. `BACKTEST_DATA_INTEGRITY.md` 的强制完整性规则；
3. 状态为 Accepted 的 ADR；同一主题以更具体、更新且明确 supersede 的 ADR 为准；
4. `STRATEGY_RESEARCH_PROTOCOL.md`；
5. `PROJECT_ARCHITECTURE.md`；
6. 已冻结且版本化的 Strategy/Experiment Spec；它只能细化，不能绕过上位约束；
7. `IMPLEMENTATION_PLAN.md`；
8. `STRATEGY_UNIVERSE.md`，它是候选目录，不是有效性证明或实现命令。

裁决原则依次为：因果正确性、数据完整性、可复现性、可证伪性、简单性、性能和开发便利。存在无法证明的选择时采用更严格、fail-closed 的方案。

每次实质冲突必须：

- 记录冲突及选择理由；
- 更新或标记过时文档，不能让两个有效版本长期并存；
- 若改变既有运行语义，增加 schema/policy/strategy version；
- 若影响历史结果，执行 golden/regression 对账。

## Consequences

维护成本略有增加，但任何实现者都能判断真正的 source of truth。策略目录中的高优先级候选不能覆盖数据完整性规则；工程计划也不能以交付速度为由降低回测标准。
