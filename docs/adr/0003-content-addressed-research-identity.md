# ADR-0003：内容寻址的研究身份

- Status: Accepted
- Date: 2026-08-10

## Context

“实验”描述科学问题，“运行”描述一次具体执行，“artifact”描述输出内容。使用自增 ID 或把三者混成一个 ID，无法判断不同环境的重跑是否属于相同实验，也无法可靠检测历史结果变化。

## Decision

- `experiment_id` 由全部科学输入的 canonical JSON 与 SHA-256 生成；
- `run_id` 由 experiment ID、source commit、环境锁哈希和 runtime context 生成；
- artifact 使用完整内容哈希，并携带 schema version；
- 参数映射顺序不改变 ID；非有限数和非字符串 mapping keys 拒绝进入 identity；
- 重跑不覆盖历史运行；相同内容可去重，但 lineage 必须保留；
- 数据供应商修订导致 snapshot hash 改变，必须产生新 experiment ID。

## Consequences

身份较长且不能人工指定，但能够证明结果是否真正相同。任何遗漏的科学输入都会变成复现风险，因此 ExperimentConfig 的 schema 变更需要审查。
