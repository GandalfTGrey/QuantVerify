# ADR-0008：Reference Result 不可变产物与运行清单

- Status: Accepted
- Date: 2026-08-11
- Owners: S-5.6
- Tracks: Issue #13

## 背景

reference engine 已能用小型 fixture 产生可人工核对的逐期结果，但结果只存在于内存。若没有稳定 schema、内容身份和运行清单，相同指标无法回链到 dataset、engine、代码与环境，也无法判断重跑得到的是相同内容还是被静默改变的内容。

Stage 1 架构仍要求大体量逐期数据最终使用 Parquet；当前 golden loop 的记录很小，先引入列式依赖会把 schema、分区和 catalog 决策混入最小正确性闭环。

## 决定

1. 使用 `reference-result-v1` canonical JSON 保存小型 `ReferenceResult`；schema、kind 和 result 一起进入 SHA-256 内容身份。
2. 确定性 artifact 内容与运行观察元数据分离。相同结果跨运行复用同一个 content object。
3. `run-artifact-manifest-v1` 记录 experiment ID、run ID、runtime、engine、dataset、artifact 引用、相对路径和带时区创建时刻，并独立内容寻址。
4. 写入先完成同目录临时文件，再以不会覆盖既有目标的原子 hard-link 发布；同路径不同 bytes fail closed。
5. replay 必须验证 manifest 路径 hash、artifact hash、规范路径、schema/kind，并拒绝重复 JSON key。
6. artifact 与 manifest 只保存相对路径；本机绝对目录不进入可移植研究谱系。

## 后果

- 最小研究闭环可以离线重放并验证内容未被篡改；
- 同一科学结果与不同运行观察不会被错误合并为同一概念；
- JSON v1 只适用于当前小型 reference result，不是大规模回测存储格式承诺；
- Parquet 表 schema、DuckDB catalog、失败运行状态机和多 artifact run 留给后续独立 ADR/PR；
- 临时文件在进程被强制终止时可能成为可识别 orphan，但不会暴露部分写入的正式 artifact。
