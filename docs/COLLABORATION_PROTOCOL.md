# QuantVerify 协作协议

> Status: Active
> Adopted: 2026-08-10
> Applies to: human owner、T-5.6、Argus 及后续具名贡献者

## 1. 协作目标

本协议把跨贡献者讨论保留在仓库和 GitHub 历史中，使“建议、异议、裁决、实现、验证”能够被后来者重建。个人角色章程用于说明专长；本协议定义所有贡献者共同遵守的沟通接口。

当前角色：

| 角色 | 主要职责 | 默认交付物 |
|---|---|---|
| 项目所有者 | 决定研究目标、风险偏好和最终裁决 | Issue/PR 中的明确决定 |
| T-5.6 | 架构整合、实现、验证与项目推进 | 个人分支、测试、Draft PR |
| Argus | 数据谱系、量化研究正确性与审计 | ADR、数据调查、review、Draft PR |

角色不形成“谁总是正确”的优先级。发生冲突时继续遵守 ADR-0001 的文档优先级和 fail-closed 原则。

## 2. 使用什么渠道

| 信息类型 | 主渠道 | 原因 |
|---|---|---|
| 尚未实现的问题、数据异常、候选方案 | GitHub Issue | 允许在写代码前对齐目标与验收条件 |
| 具体实现及逐行讨论 | Draft PR | diff、CI 和 review 上下文位于同一处 |
| 跨模块或长期语义决定 | ADR | 决定不可被后续代码静默改写 |
| 当前角色范围和工作队列 | 角色 Charter | 避免个人职责混入系统架构 |
| 临时状态 | PR comment | 便于交接，但不能替代 ADR 或测试 |

聊天可以启动工作，但关键结论必须回写上述渠道之一。

## 3. 标准讨论格式

Issue、PR 描述或协作评论至少包含：

1. **Owner / identity**：谁提出并负责当前改动；
2. **Objective**：要解决的具体问题；
3. **Affected semantics**：数据、时间、收益、实验身份或执行语义；
4. **Reproduction / evidence**：最小复现、fixture、日志摘要或数据 hash；
5. **Proposal and trade-offs**：方案、未选方案及代价；
6. **Acceptance tests**：什么证据代表完成；
7. **Open questions**：希望另一位贡献者或项目所有者回答什么。

## 4. PR 与分支协作

- 每个具名贡献者只在自己的分支写代码，不直接修改他人的 head 分支；
- 对尚未合并 PR 的跟进使用 stacked PR，并在描述中显式填写 `Depends on #N`；
- 子 PR 以被审查 PR 的 head 分支为 base，只包含审查增量；
- 未经分支所有者同意，不 force-push 其分支；
- PR 保持 Draft，直到依赖、关键异议和 CI 均已解决；
- 合并顺序从栈底到栈顶；底层合并后及时把上层 PR base 调整到新的稳定基线；
- 工作区存在无关或未跟踪用户文件时，显式逐文件暂存。

## 5. Review 严重性与处理

| 等级 | 含义 | 合并规则 |
|---|---|---|
| P0 | 会产生错误研究证据、泄漏凭据或破坏不可复现性 | 必须修复或由项目所有者书面裁决 |
| P1 | 重要契约缺失、常见输入失败或未来迁移风险高 | 原则上本 PR 修复；延期需建立 Issue |
| P2 | 可维护性、清晰度或低概率边界问题 | 可修复或记录后续工作 |
| Question | 需要解释但尚未证明为缺陷 | 由 owner 回答并记录结论 |

所有讨论都针对证据与语义，不针对贡献者身份。解决评论时应链接对应 commit/test；不得只回复“已修复”。

## 6. 分歧裁决

1. 先构造双方都能运行的最小复现或 golden fixture；
2. 按 ADR-0001 比较文档优先级；
3. 在数据不充分时选择 fail closed，并记录缺少的证据；
4. 若两种实现都正确，优先更简单且保留未来语义边界的方案；
5. 仍无法决定时，由项目所有者裁决，并将结果写入 PR/Issue；
6. 改变跨模块语义的裁决升级为 ADR。

## 7. Handoff 模板

```text
Owner / branch:
Depends on:
Completed:
Evidence / tests:
Known risks:
Decisions requested:
Recommended next PR:
```

## 8. 当前协作起点

- Argus PR #7 建立 `RawCapture -> offline normalization` 边界；
- T-5.6 的跟进审查验证嵌套内容是否真正不可变、schema drift 是否 fail closed；
- 下一独立能力应是 provider-agnostic CaptureStore（Argus A2），不与 A1 审查修复混入同一实现提交。

协议本身是活文档。实质规则修改通过 PR 讨论；研究语义变化仍须使用 ADR。
