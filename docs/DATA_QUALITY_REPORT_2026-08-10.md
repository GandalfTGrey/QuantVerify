# 数据质量报告：QQQ / DIA 初始双源检查

- Status: **INVALID — 不得用于回测或策略排名**
- 检查日期：2026-08-10
- 范围：AkShare `stock_us_daily` raw / qfq、Tushare Pro `us_daily_adj`、Massive `v1/open-close` raw probe、yfinance raw OHLCV probe
- 规则依据：[M1 研究范围](M1_RESEARCH_SCOPE.md)、[ADR-0004](adr/0004-dual-source-data-validation.md)、[ADR-0005](adr/0005-akshare-ingestion-boundary.md)

## 结论

当前数据**不能**进入 M1 策略研究。Tushare 的教程指定通道和 token 初始化已验证可用，但当前 token 没有独立美股日线权限；目标美股接口 `us_daily_adj` 返回“所有上游代理均无法访问”。Massive 的 QQQ 单日 raw OHLCV 探针已通过但当前基础计划只有两年历史。yfinance 已通过 QQQ/DIA 的长历史 raw OHLCV 连通性探针，并与 AkShare raw snapshot 完成重叠收盘价初比；其中 DIA 没有超过 1% 的差异，QQQ 有 1 个 2.851324% 的冲突交易日，且尚未保存 yfinance 不可变 snapshot。因此仍不能执行完整的 raw close 双源容差校验。与此同时，AkShare 本地 snapshot 存在覆盖缺口和 qfq 非正价格，不能作为单源替代。

## 已执行检查

| 检查 | QQQ | DIA | 结果 |
|---|---:|---:|---|
| Tushare token / 教程指定通道 | 可用 | 可用 | PASS（最小 `daily` 探针返回 13 行） |
| Tushare `us_daily_adj` | 无法取得 | 无法取得 | BLOCKED：token 无独立美股日线权限；服务端同时返回上游不可访问 |
| Massive `v1/open-close` raw（2025-01-03） | 1 行 QQQ OHLCV | 未测 | PASS（仅单日连通性；基础计划两年历史） |
| yfinance raw long-history（至 2026-08-07） | 6,896 行，起点 1999-03-10 | 7,182 行，起点 1998-01-20 | PASS（`auto_adjust=False`；长历史连通性） |
| AkShare/yfinance raw close 重叠比较 | 4,844 日：p50≈0、p95=0.014871%、1 日 >1% | 5,432 日：p50≈0、最大=0.145817% | REVIEW（QQQ 2002-11-01 为 2.851324% 冲突） |
| AkShare raw snapshot SHA-256 | 匹配 | 匹配 | PASS |
| raw 字段、数值、OHLC、时区与交易日映射 | 4,844 行可归一化 | 5,432 行可归一化 | PASS（仅表示已有行结构有效） |
| session 排序、重复、非正成交量 | 无重复、无非正 volume | 无重复、无非正 volume | PASS |
| 相对 NYSE 日历的缺失 session | 1,593 | 1 | FAIL |
| 最大连续缺口 | 2005-01-03 至 2011-04-25（1,589 个 session） | 2015-04-09（1 个 session） | FAIL |
| qfq 非正 OHLC 行 | 110 | 22 | FAIL |
| raw vs Tushare close（10/50 bps policy） | 未执行 | 未执行 | BLOCKED |
| adjusted return（10 bps policy） | 未执行 | 未执行 | BLOCKED |
| corporate action / official anchor | 未执行 | 未执行 | BLOCKED |

## 已识别的数据问题与处置

1. **QQQ 长历史缺口（P0）**：不得插值、不得以 DIA 或其他价格填补，也不得在缺口两端直接计算跨期收益。应由可用的 Tushare raw snapshot 或另一独立 Level B 源补齐，并记录补齐来源与版本。
2. **DIA 单日缺口（P0）**：2015-04-09 也必须由第二源或官方锚点裁决；即使只有一个 session，填补亦会改变持有期收益与成交时点。
3. **AkShare qfq 非正价格（P0）**：qfq 不能作为 split-adjusted 或 total-return 序列进入任何计算。当前 adapter 将其 fail closed；示例包括 QQQ 2002-05-03 low = -0.9583，以及 DIA 2009-02-20 多个 OHLC 字段为负。
4. **Tushare 美股权限与上游状态不可用（P0）**：服务 HTTP 可达、token 通道和 A 股 `daily` 探针可用，但 token 无独立美股日线权限，且 `us_daily_adj` 返回上游不可访问。先开通美股日线权限；若仍报相同错误，再由数据服务方恢复或说明美股上游后重新抓取不可变 snapshot。
5. **Massive 当前覆盖不足（P0）**：单日 raw probe 验证了凭据、endpoint 与字段，但基础计划仅提供两年历史，无法补齐 QQQ 2005-2011 的缺口。仅在升级到覆盖目标区间的计划，或将其限定为 2024 年后的独立验证窗口后，才可进入 provider contract tests。
6. **yfinance 的冲突裁决、snapshot 与许可边界（P0）**：长历史连通性已通过，且 DIA 重叠价格高度一致；但 QQQ 2002-11-01 的 AkShare close 为 24.55、yfinance close 为 25.25（相对差 2.851324%）。必须以官方基金行动/第三独立源裁决该日，并保存 yfinance 的不可变 raw snapshot 后再运行全量 contract tests。Yahoo 数据仍应标记为研究/交叉验证来源，不得成为生产唯一真相源或用于策略排名。
7. **复权口径不可假设（P0）**：即使 Tushare 恢复，raw OHLC 必须先比较价格水平；adjusted 序列只比较单期收益、除权窗口累计收益与方向，禁止比较绝对复权价格水平。
8. **凭据传输风险（P0 安全）**：项目内教程要求 HTTP 专用地址，token 已被显式提供给本任务。应在数据服务端启用 HTTPS，并在本次排障后轮换该 token；token 不得提交、写入日志或保存于 snapshot。

## 允许的下一步

仅在以下全部完成后，才可开始 S4 或其他策略开发：

1. `us_daily_adj` 成功拉取 QQQ/DIA，并为每个响应写入 raw snapshot 和不可变 manifest；
2. 两源 raw session 集合的差异全部被解释或被显式排除，且不存在未裁决缺口；
3. raw close 按 10/50 bps policy 生成 `DataQualityReport`；
4. adjusted-return 与 corporate-action 窗口校验通过；
5. 重新生成本报告并将状态更新为 `PASS` 或带有明确人工裁决的 `WARNING`。

## 校验链路修复

检查过程中修复了两项 fail-closed 行为：snapshot 序列化的午夜时间戳现在可安全重放为 session date；供应商返回违反 `NormalizedBar` 价格契约时，adapter 现在报告对应行号而非泄漏底层校验异常。
