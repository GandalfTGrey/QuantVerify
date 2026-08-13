# QuantVerify 协作范围与并行交付地图

> Status: Active execution contract
> Baseline: 2026-08-12
> Accountable technical lead: S-5.6
> Dynamic status source: GitHub coordination Issue #14
> Stable process rules: `COLLABORATION_PROTOCOL.md`

## 1. 文档职责

本文定义当前阶段可并行的工作包、Owner、文件边界、输入输出契约、依赖、验收条件和合并顺序。它解决“谁可以在什么边界内做什么”，不替代：

- `COLLABORATION_PROTOCOL.md`：稳定的协作、审查和合并规则；
- GitHub Issue #14：每个 PR、branch、blocker 和 head SHA 的高频状态；
- ADR：跨模块的数据、时间、收益和实验身份决策；
- 角色 Charter：某一贡献者的长期专业职责。

结论：当前人力足以形成四条并行泳道，但不能并行宣称完成真实数据研究闭环。真实数据准入仍受 CaptureStore、Quality Suite、DatasetRelease 和公司行动口径共同约束。

## 2. 角色、决策权与当前容量

| 角色 | 当前职责 | 可同时进行的工作 | 不应承担 |
|---|---|---:|---|
| 项目所有者 | 产品目标、风险偏好、最终争议裁决 | 决策/验收 | 日常代码合并门禁 |
| S-5.6 | 架构、共享契约、关键路径、review、主线合并 | 1 个关键 review + 1 个小型契约工作 | 长期占用已可委派的独占模块 |
| Argus | CaptureStore、数据谱系、A3/A4 与数据正确性复核 | A4 design/implementation + 1 个数据复核 | 新 provider、CLI、策略、公司行动实现 |
| 资深量化工程师（Q-Lead） | 频率变换、策略/指标 golden、研究语义复核 | 1 个实现 + 1 个只读审计 | CaptureStore/A3、应用编排 |
| 公司行动专员（CA-Lead） | point-in-time action vintages 与收益序列变换 | 1 个设计或实现 | provider 准入、策略优化 |
| 资深软件开发者（Dev-Lead） | artifact、metrics、fixture、CLI shell、CI 可靠性 | 1 个实现 + 1 个只读审计 | 自行定义研究准入语义 |
| 独立验证者（QA-Lead） | 黑盒、metamorphic、golden 与跨平台验证 | 1 个验证包 | 修改产品源码以迁就测试 |

新增角色在获得独立 GitHub 账号前以 PR 描述和 commit trailer 标识：

```text
Contributor-Identity: <name>
Contributor-Role: <S-5.6|Argus|Q-Lead|CA-Lead|Dev-Lead|QA-Lead>
```

同一 GitHub 账号无法可靠执行角色级 `CODEOWNERS`，当前不引入伪强制规则。角色边界由 Issue、PR 模板、review 和合并门禁执行。

## 3. S-5.6 必须先冻结的共享契约

下列文件和语义不能由各泳道自行扩展。任何改动必须由 S-5.6 通过 Issue #21 建立或批准一个小型 contract PR，并在必要时记录 ADR。

| ID | 共享契约风险 | 冻结结果 |
|---|---|---|
| CORE-01 | 已完成：周/月频率契约 | `BarFrequency` 已区分 daily input 与 derived weekly/monthly frequency；各模块不得自造字符串/枚举 |
| CORE-02 | 已完成：period series envelope | `SeriesDescriptor` / `DerivedPeriodBar` 已绑定 frequency、adjustment、source lineage、constituent schedule、`available_at` 与 completeness；release source bridge 已冻结 |
| CORE-03 | 已完成：DatasetRelease reference contract（PR #59、ADR-0011） | RAW/daily/single-source `DatasetReleaseRef` 绑定 normalizer、quality policy/report、eligible intervals、calendar/schedule 与单资产 experiment identity；A4 authenticity 仍由 verified factory/store 证明 |
| CORE-04 | 已完成契约层：显式 session schedule | reference strategy 使用显式 schedule 的下一 session open；生产权威性仍由 A4 pinned calendar/release 证明 |
| CORE-05 | 05A 已完成（PR #61、ADR-0012）；05B 待实现 | command DTO、科学 identity、capability、plan/inspect handler ports 已冻结；registry-backed preflight/run handler 等 CORE-06 与 SW-03 |
| CORE-06 | 设计已接受（Issue #66、ADR-0013 Accepted）；06A/06B 待实现 | rational-return MetricInput/MetricSet v2、完整 replay evidence、artifact v2/dispatcher 与 hardened publication 已冻结；不破坏 v1 verified read |

`quantverify/core/models.py`、`quantverify/core/ports.py`、配置 schema、实验身份和 ADR 编号属于共享热点。除 S-5.6 的 contract PR 外，其他 PR 若必须修改这些文件，需先在 Issue 中列出理由、影响和兼容方案并获得批准。

## 4. 并行泳道与关键路径

```text
Lane A — Data trust
#18 credential guard -> #19 atomic publish -> #20 verified replay
    -> #16 VerifiedCapture integration / A3 -> CORE-03 release ref [Done]
    -> DATA-02 A4 verified factory/store + authoritative calendar resolver

Lane B — Research correctness
QD-01 #5 conflict evidence (independent now)
CORE-01/02/04 -> QF-01 causal week/month bars
    -> QF-02 S4 -> S2 -> S3 -> S1 -> S5 signal-only

Lane C — Platform
SW-01 artifact inspection + DEV-01 metrics + SW-02 CI audit [Done]
    -> SW-03 FixtureBundle || CORE-05/06
    -> DEV-02 CLI/application wiring

Lane D — Return semantics
CA-01 contract/design -> action transform -> A4-derived release integration

Independent QA consumes merged contracts and never becomes a production dependency.
```

真实数据实验的总门禁为：CaptureStore P0/P1、VerifiedCapture、A3、A4，以及目标收益语义所需的公司行动 policy 全部通过。fixture-only 闭环可先完成，但其结果不是 QQQ/DIA 或中国市场的生产级研究结论。

## 5. 当前工作包

每个工作包都使用个人分支，不共享 head。下表中的 branch 是命名约定；实际 PR/Issue 状态维护在 #14。

### DATA-01 — CaptureStore hardening 与 A3 Quality Suite

| 字段 | 内容 |
|---|---|
| Owner / Reviewer | Argus / S-5.6；A3 另需 Q-Lead 科学复核 |
| Branch / Status | Done；#18/#19/#20/#16 已合并，A3 为 Quality Suite v2，ADR-0009 Accepted |
| Input contract | immutable capture bytes、request identity、manifest、normalized input reference、显式 quality policy |
| Output contract | verified capture；内容寻址且区间级的 quality report；可重复的 eligibility 决定 |
| 独占文件 | `quantverify/data/store.py`、`quantverify/data/quality/**` 及对应测试、ADR-0007/0009 |
| 共享文件 | `quantverify/data/__init__.py` 由 S-5.6 在堆叠 rebase 时协调 |
| Dependencies | #18 P0 -> #19 -> #20 -> #16 接入 `load_verified()` |
| Acceptance | secret fail closed；atomic publish；verified replay；report identity 绑定 normalized content、完整 policy、capture/manifest/normalizer/schema version；区间 eligibility；真实异常 fixture |
| Forbidden | 网络 CI、冲突值静默平均、同一 evidence/provider 伪装双源、区间外异常全局封杀、修改 strategy/engine/CLI |
| Merge order | 已完成：#18 -> #19 -> #20 -> #16；每层均在新 `main` 重放 CI |

DATA-01 队列已清空。Argus 可以领取 A4，但必须先把 verified calendar resolver、完整 A3 replay input closure 和 immutable publication 边界写入 #29；不得从 `DatasetReleaseRef` 自洽性推导 authenticity。

### DATA-02 — A4 immutable DatasetRelease

| 字段 | 内容 |
|---|---|
| Owner / Reviewer | Argus / S-5.6 + Q-Lead |
| Branch / Status | `argus/dataset-release-v1`；Issue #29，Ready for design；实现仍需 verified calendar resolver contract |
| Input contract | 完整 `QualitySourceData`/revision/policy/expected-sessions replay closure、确定性 ordered normalization、权威 calendar artifact/schedule、显式 adjustment mode |
| Output contract | immutable release ID、normalized content hash、eligible intervals、exception refs、quality policy/report refs、adjustment mode |
| 独占文件 | 新建 `quantverify/data/releases/**` 及对应测试 |
| 共享文件 | `DatasetReleaseRef`、ExperimentConfig 仅由 CORE-03 修改 |
| Acceptance | 每 interval 的 report 完整重放为 ELIGIBLE；v1 恰好一个 active source；发布 bars 与 selected ordered normalized identity 精确一致；pinned schedule exact slice；identity 对内容、normalizer、schema、quality policy/report、eligible range 和 adjustment 敏感；旧 release 不覆盖；requested range fail closed |
| Forbidden | 多 source report、按策略表现选源、无证据自动 PASS、mutable `latest`、从 bars 自举 calendar、直接调用 provider、把 fixture 晋升 Gold |
| Merge order | CORE-03 后；verified calendar resolver 先于 Gold factory；真实数据 preflight 前 |

### QD-01 — QQQ/DIA 冲突证据与独立裁决包

| 字段 | 内容 |
|---|---|
| Owner / Reviewer | Q-Lead / Argus + S-5.6 |
| Branch / Status | `quant/us-etf-evidence-v1`；Issue #5，evidence-only 可立即开始 |
| Input contract | QQQ 2002-11-01、DIA 2015-04-09 的已有 raw evidence、官方基金行动资料、独立第三来源、许可/引用信息 |
| Output contract | 前后窗口对照、来源/时间/调整口径矩阵、可复核裁决候选、最小可再分发 regression fixture |
| 独占文件 | 新建 `docs/evidence/**`、`tests/fixtures/data_conflicts/**`；不得修改用户的 `docs/tushare教程/` |
| Acceptance | 每个事实有 URL/抓取时间/适用日期/许可说明；区分交易价格、split-adjusted、total return；不确定性和替代解释保留 |
| Forbidden | 写入正式 CaptureStore、创建 Gold DatasetRelease、直接修改 A3、用策略表现裁决数据、把网络请求放进 CI |
| Merge order | evidence 报告可独立合并；#20 后再用正式 CaptureStore 保存新证据；A3/A4 接受后才能晋升 release |

### QF-01 — 交易日历感知的日到周/月因果重采样

| 字段 | 内容 |
|---|---|
| Owner / Reviewer | Q-Lead / S-5.6 + QA-Lead |
| Branch / Status | `q-lead/causal-frequency-v1`；Issue #22，Done，PR #37 |
| Input contract | ordered daily bars、显式 session calendar/schedule、cutoff、`SeriesDescriptor` |
| Output contract | derived period bars，携带 constituent start/end、`available_at`、`complete` 和 lineage |
| 独占文件 | 新建 `quantverify/research/frequency/**`、`tests/research/frequency/**` |
| Acceptance | 假日短周、月末非交易日、DST、缺最后 session、partial period、cutoff、truncation invariance 均有测试 |
| Forbidden | 裸 `resample('W'/'M')`、周末占位、静默 fill、下载供应商周/月线、默认纳入未完成周期 |
| Merge order | CORE-01/02/04 后；所有周/月策略前 |

### QF-02 — 五策略 fixture reference pack

| 字段 | 内容 |
|---|---|
| Owner / Reviewer | Q-Lead / S-5.6 + QA-Lead |
| Branch / Status | Q-Lead 每策略个人分支；Issue #30，Done，PR #39/#41/#43/#45/#49 |
| Input contract | verified fixture bundle、完成的 derived period bars、显式 eligible session schedule、reference engine |
| Output contract | versioned feature/strategy signals、手算 golden、causality/metamorphic evidence |
| 独占文件 | `quantverify/features/**`、`quantverify/strategies/**`、`tests/strategies/**` |
| Acceptance | 决策时间不早于 constituent `available_at`；下一真实 session open 成交；Donchian `shift(1)`；周/月指标在重采样后重算 |
| Forbidden | 参数优化、解锁 OOS、provider 访问、adjusted open 冒充成交价、从缺 bar 推断现金 |
| Merge order | S4 -> S2 -> S3 -> S1 -> S5；每个策略可独立窄 PR |

S5 双动量依赖多资产 allocator/engine。当前阶段只允许 signal golden，不得宣称端到端完成。候选 YAML 中的大写 ID 必须在统一 schema 后再进入运行时，DEV-02 不得临时兼容。

### CA-01 — Point-in-time Corporate Action Pipeline

| 字段 | 内容 |
|---|---|
| Owner / Reviewer | CA-Lead / Argus + S-5.6 |
| Branch / Status | `ca/action-series-v1`；Issue #25，contract design 可立即开始，集成等待 CORE-02/03 |
| Input contract | raw bars、immutable action event vintages、as-of cutoff、显式 return semantics |
| Output contract | RAW、SPLIT_ADJUSTED、TOTAL_RETURN 三种互斥 series；transform manifest/hash |
| 独占文件 | 新建 `quantverify/marketdata/corporate_actions/**` 及对应测试 |
| Acceptance | split conservation、cash/special dividend、同日多事件、事件修订改变 identity、as-of cutoff、股息不双计 |
| Forbidden | 把当前抓取的全历史复权曲线当 PIT 真相、静默覆盖事件、从 vendor Adj Close 反推并声称官方 action |
| Merge order | contract -> transform -> A4-derived release integration |

Argus 对 CA-01 是 correctness reviewer，不再同时做 Owner，以消除 A3/A4 数据串行瓶颈。

### DEV-01 — Metrics v1

| 字段 | 内容 |
|---|---|
| Owner / Reviewer | Dev-Lead 或 Q-Lead / Q-Lead + S-5.6（作者之外） |
| Branch / Status | `dev-lead/metrics-v1`；Issue #23，Done，PR #38 |
| Input contract | versioned equity/return observations、显式 calendar/annualization/ddof/risk-free policy |
| Output contract | versioned `MetricSet`：Total、CAGR、Vol、Sharpe、MaxDD，失败状态显式 |
| 独占文件 | 新建 `quantverify/metrics/**`、`tests/metrics/**`、指标口径文档 |
| Acceptance | 不规则时间、样本不足、零波动、收益符号、ddof、annualization、手算 golden |
| Forbidden | 匿名 annualization 常数、`inf/NaN` 冒充结果、将 rating/promotion 混入 metrics |
| Merge order | 可与 DATA-01 并行；CORE-06 前完成最有利 |

### SW-01 — Verified RunArtifact inspection API

| 字段 | 内容 |
|---|---|
| Owner / Reviewer | Dev-Lead / S-5.6 + QA-Lead |
| Branch / Status | `dev-lead/artifact-inspection-v1`；Issue #24，Done，PR #40 |
| Input contract | store root、显式相对 manifest path；不接受 implicit latest |
| Output contract | `VerifiedRunArtifact`：manifest、manifest hash、reference result、canonical paths |
| 独占文件 | `quantverify/artifacts/**` 及 artifact 专属测试 |
| Acceptance | 验证内容、manifest、canonical path；duplicate key、篡改、移动 manifest、path escape、并发/碰撞 fail closed；旧 loader 兼容 |
| Forbidden | 扫描任意外部目录、修改 CaptureStore/A3/application、把文件扫描器命名为 Research Catalog |
| Merge order | CORE-06/application artifact v2 前 |

### SW-02 — CI、安全与跨平台仓库加固

| 字段 | 内容 |
|---|---|
| Owner / Reviewer | 第二位 Dev-Lead / S-5.6 |
| Branch / Status | Done；Issue #26，audit 与 SW02-01..06 已合并 |
| Input contract | 当前 workflows、pyproject、安装与测试命令 |
| Output contract | 最小权限、timeout/concurrency、wheel/install smoke、离线测试和可追踪依赖更新 |
| 独占文件 | `.github/workflows/**`、`.github/dependabot.yml`、独立 CI/security 文档 |
| Acceptance | Python 3.11/3.12/3.13；regular wheel clean-install；不读取/输出本地 `.env`；安装 market-data extras 后网络禁用测试；Mac arm64 自动化 smoke |
| Forbidden | 暂不修改 `[project.scripts]`、不把不稳定外部扫描直接设 required gate、不把 CI 当 CaptureStore secret guard 的替代品 |
| Merge order | 审计可并行；每个工具链改变单独 PR |

### SW-03 — Versioned FixtureBundle 与显式 registry

| 字段 | 内容 |
|---|---|
| Owner / Reviewer | Dev-Lead / Argus + S-5.6 |
| Branch / Status | `dev/fixture-bundle-v1`；Issue #27，Ready；A3 ordered normalized identity 已随 #16 合并 |
| Input contract | 显式注册的 fixture ID/manifest |
| Output contract | immutable `LoadedFixture`：asset/frequency/calendar/adjustment、snapshot、ordered bars、content hash/schema、expected-session identity |
| 独占文件 | 新建 `quantverify/fixtures/**`、fixture 资源和测试 |
| Acceptance | Decimal/timezone/order 确定；manifest/hash 不一致失败；完全离线；仅显式资源；顺序变化不能静默改语义 |
| Forbidden | 修改 `data/store.py`、`data/quality/**`；任意 path/implicit latest；将 fixture 宣称为真实 Gold release |
| Merge order | 可与 CORE-05/06 并行；DEV-02 fixture mode 前 |

### DEV-02 — Fixture-only application service 与 CLI shell

| 字段 | 内容 |
|---|---|
| Owner / Reviewer | S-5.6 对 application/preflight Accountable；Dev-Lead 实现 CLI/registry/wiring；QA-Lead 黑盒复核 |
| Branch / Status | `dev/experiment-cli-v1`；Issue #17，blocked on CORE-05/06、SW-01/03、DEV-01 |
| Input contract | frozen command DTO/handler ports、ExperimentConfig/Identity、显式 fixture resolver、strategy registry、engine、metrics、artifact store、EligibilityGate protocol |
| Output contract | `PlanResult`、`RunOutcome/RunReceipt`、`InspectResult`；稳定 JSON/stdout/stderr/exit codes；不可变 refs |
| 独占文件 | Dev-Lead：`quantverify/interfaces/**`、CLI tests；S-5.6：`quantverify/application/**` 与 composition root |
| Acceptance | parser 用 fake handler；CLI 无业务逻辑；fixture PASS 显式；INELIGIBLE/INCOMPLETE fail closed；无网络；错误不泄漏环境/traceback |
| Forbidden | 动态 import、implicit latest、CLI 计算 eligibility/hash、提前接真实 provider、绕过 A4 |
| Merge order | contracts -> artifact inspection/metrics/fixture -> application -> CLI shell -> composition |

### QA-01 — 独立黑盒研究正确性审计

| 字段 | 内容 |
|---|---|
| Owner / Reviewer | QA-Lead / S-5.6；领域项由 Argus 或 Q-Lead 复核 |
| Branch / Status | `qa/contract-golden-audit-v1`；Issue #28，可在每个上游契约合并后增量开始 |
| Input contract | 仅公开 API、已接受 ADR、明确 fixture |
| Output contract | 可独立运行的 contract/golden/metamorphic suite 与审计矩阵 |
| 独占文件 | `tests/contracts/**`、`tests/golden/**`、QA 报告 |
| Acceptance | future truncation、周/月完成边界、corporate actions、signal/execution price、identity sensitivity、offline replay、Mac/Linux 差异 |
| Forbidden | 修改产品源码、网络测试、为迁就实现随意更新 golden、复制实现算法作为 oracle |
| Merge order | 跟随已合并公开契约；不对未冻结接口抢跑 |

## 6. 文件冲突热点

| 热点 | 冲突方 | 处理方式 |
|---|---|---|
| `quantverify/data/__init__.py` | #20 / #16 | #20 合并后由 S-5.6 统一 rebase #16 |
| `quantverify/artifacts/store.py` | SW-01 / CORE-06 / application | SW-01 先合并；artifact v2 再设计 |
| `pyproject.toml` | SW-02 / CLI | SW-02 暂不改 project scripts；CLI 合并时由 S-5.6 接线 |
| `core/models.py`、`core/ports.py` | 所有泳道 | 只由 S contract PR 修改 |
| ADR 编号与索引 | 多个设计流 | 由 S-5.6 分配编号并合并 |

DuckDB Research Catalog 延至 M3。在 DatasetRelease、quality-to-run lineage、metrics artifact 和 application outcome 未冻结前，不建立临时 catalog schema。

## 7. WIP、PR 粒度与合并列车

- 每位贡献者最多 1 个进行中的实现 PR，加 1 个只读审计/review；
- 全团队最多 3 个 active implementation PR、2 个 ready-for-merge PR；
- stacked PR 最大深度为 3；Argus 当前属于历史超限，必须先清空现有队列；
- 单 PR 建议不超过 400 changed production LOC、7 个 production files；测试和文档后建议不超过 800 非生成 LOC；超限需说明原因并接受双人审查；
- 一个 PR 只改变一个跨模块契约；不得顺手重构其他泳道；
- 一次只向 `main` 合并一个 PR；锁定被审 head SHA，CI 对该 SHA 绿色；合并后在新 `main` 重放，再处理下一层；
- 数据身份、财务计算、权限/秘密边界必须有作者之外的领域 reviewer；
- 下游 PR 仍以分支为 base 时不删除上游 branch。

## 8. Definition of Ready

生产代码开始前必须具备：

1. Owner、Reviewer、Issue、个人 branch、base 和依赖明确；
2. 允许修改、禁止修改的文件范围明确；
3. affected semantics、non-goals、threat model 明确；
4. 可执行验收条件和至少一个失败 fixture；
5. 数据工作列出来源、许可、区间、调整口径和证据保存方案；
6. 不与 active PR 的文件/契约冲突；
7. 上游契约已合并，或工作明确标记为 design/audit-only；
8. 需要 ADR 的语义变更先提交 proposal。

## 9. Definition of Done

1. Issue 验收条件逐项满足；
2. Ruff、strict mypy、Python 3.11/3.12/3.13、全量测试通过；
3. 总覆盖率不低于 85%，本次高风险模块目标不低于 90%；
4. 测试离线、确定性，包含成功与失败路径；
5. 相关身份、篡改、重放、路径、时区和 secret 边界均有测试；
6. 数据/财务语义由独立领域 reviewer 复核；
7. 无未解决 P0/P1；
8. ADR、实施计划、本文与 GitHub #14 状态一致；
9. PR 包含 handoff、已知风险和 deferred scope；
10. 合并后的 `main` CI 再次绿色；
11. 不包含 secret、用户未跟踪文件或无关 diff。

## 10. 冲突、缺席与重新分配

- 接口冲突先停止相关实现，以最小 fixture/ADR proposal 交由 S-5.6 仲裁；
- 同一文件已被另一个 active PR 占有时，后开工作转为 design-only 或等待，不创建竞争实现；
- Owner 无法继续时，在 Issue #14 记录已完成证据、未完成项和最后可信 SHA；S-5.6 指定新 Owner 从新个人分支接手，不 force-push 原分支；
- blocked 工作不占实现 WIP，但必须记录 blocker、解除条件和下次检查点；
- 任何角色都无权因交付压力绕过 fail-closed、PIT、identity 或真实数据准入门禁。

## 11. 当前明确不启动的工作

- 真实数据策略排名、参数优化或 locked OOS；
- S5 多资产端到端回测；
- DuckDB Research Catalog；
- 新 provider 扩张；
- UI/Research Console；
- paper/live execution。

这些工作不是取消，而是其上游可信契约尚未完成。新增人力优先用于消除独立验证盲点和完成可合并的窄工作包，而不是扩大同时在建的系统表面积。
