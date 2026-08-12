# CI 与依赖更新政策

> Status: Active
> Owner: S-5.6
> Operational tracker: GitHub Issue #26

## 1. 适用范围

本文定义 GitHub Actions、Python 依赖、CI 缓存和兼容性工作流的审查与回滚规则。它不替代数据许可、CaptureStore credential guard、原始数据完整性、A3/A4 准入或研究结果审核。

## 2. 自动提议，不自动合并

Dependabot 每周一按 Asia/Shanghai 时区提出两类更新：

- GitHub Actions：minor/patch 合并为一组，major 独立提出，最多同时打开 3 个 PR；
- Python：minor/patch 合并为一组，major 独立提出，最多同时打开 5 个 PR。

Dependabot 只创建待审 PR。仓库不得为依赖更新配置自动批准或自动合并。每个更新仍须通过当前 required checks 和本文规定的人工审查。

## 3. GitHub Actions 必须使用完整 SHA

所有 `uses:` 引用必须固定到 40 位 commit SHA，并保留可读的 release/version 注释。依赖 PR 的 reviewer 必须：

1. 从 action 的官方仓库与 release/tag 核对目标版本；
2. 验证提议 SHA 确实是该版本对应的 commit；
3. 查看 major 版本的 runtime、permissions、输入默认值和 breaking changes；
4. 确认 `contents: read`、`persist-credentials: false`、timeout 和 concurrency 没有回退；
5. 在 Linux、offline-extras、wheel 和 macOS arm64 门禁全绿后才允许合并。

Dependabot 提议不是可信证明；若提议把完整 SHA 改为 tag、branch 或短 SHA，必须拒绝或人工修正。

## 4. Python 版本范围与解析证据

`pyproject.toml` 中的上下界是兼容范围，不是 lock。当前仓库没有受审 lock/constraints artifact，因此同一源码 SHA 在不同日期可能解析到不同的允许版本。CI cache 只用于提速：

- cache hit 不构成环境身份或可复现性证明；
- cache key 变化不构成依赖审查；
- CI 日志中的实际安装版本是一次运行的解析证据，不是永久冻结；
- 生产研究 artifact 在 CORE-06 完成前不得声称已经绑定完整环境依赖身份。

修改 Python 上下界必须是独立 PR，说明兼容性、许可、Apple Silicon wheel 可用性、回滚版本和对历史 artifact 的影响。是否引入 constraints/lock 及其生成平台、哈希和更新流程，需要单独 ADR；Dependabot 配置本身不解决该问题。

## 5. 容器与供应链边界

offline market-data workflow 当前使用可变的 Python image tag；日志会记录该次运行解析出的 digest，但这不等于 workflow 固定了 digest。将该 workflow 晋升为 required gate 前，必须另行评审 base-image digest 固定及受审更新机制。

CI 不读取或枚举本地 `.env`/credential 值，不访问真实市场 endpoint。断网 workflow 只证明测试阶段的 egress isolation；它不替代 CaptureStore 的 secret-field 检查。

## 6. Reviewer 与回滚

- Owner：Dev-Lead 提交依赖/CI 更新；S-5.6 批准 policy、权限和 required-gate 变化；QA-Lead 可独立重放兼容性门禁。
- Python runtime/provider 更新需 Q-Lead 或数据 reviewer 检查数值、时间和数据边界是否改变。
- GitHub Actions major、Python major、runner image 或权限变化必须独立 PR，不与产品功能混合。
- 回滚使用普通 revert PR 回到最后已审 SHA/版本范围；不得直接推 main，也不得关闭失败门禁以强行合并。
- 若更新改变结果 identity、serialization、calendar、Decimal 或 timezone 行为，相关 artifact/experiment 版本必须先升级，不能用依赖更新悄悄改写历史语义。

## 7. 未关闭风险

- CaptureStore crash-safe atomic publication 仍由 DATA-01/#19 负责；CI 平台覆盖不能关闭该风险；
- APFS power-loss、network volume、case-collision 和目录 durability 仍是显式残余风险；
- lock/constraints、base-image digest 固定和完整环境 identity 尚未决策；
- macOS arm64 绿色只证明 observed hosted image 兼容，不证明所有本地 M1 环境等价。
