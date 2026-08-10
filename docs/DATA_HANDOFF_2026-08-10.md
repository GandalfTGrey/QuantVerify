# 数据接手说明与问题台账（2026-08-10）

> **当前结论：INVALID — 禁止用于回测、策略排名或发布投资结论。**
>
> 本文面向负责数据质量的新协作者。它记录截至 2026-08-10 已完成的接入、可复现实验、未决冲突和完成 M1 数据准入所需的验收条件。它是 [数据质量报告](DATA_QUALITY_REPORT_2026-08-10.md) 的执行型补充；判断规则以 [ADR-0004](adr/0004-dual-source-data-validation.md) 为准。

## 1. 当前状态一览

| 数据源 | 项目角色 | 已验证结果 | 不能做什么 |
|---|---|---|---|
| Tushare Pro `us_daily_adj` | primary candidate | 教程指定通道和 A 股 `daily` 最小探针可用 | 当前 token 没有独立美股日线权限，目标接口同时报告上游不可访问；不能提供美股 primary snapshot |
| AkShare `stock_us_daily` | secondary verification source | QQQ/DIA raw 响应可规范化、不可变 raw snapshot 已保存 | QQQ 仅从 2001-01-02 开始；DIA 有 2015-04-09 单日缺失；`qfq` 出现非正价，不能用作 total return |
| yfinance / Yahoo Finance | additional secondary / 研究交叉验证 | raw OHLCV adapter 已通过真实近期和长历史探针；覆盖 QQQ 1999-03-10、DIA 1998-01-20 起 | 尚无 yfinance raw snapshot writer；仅限研究/个人使用，不能成为 production sole source |
| Massive `v1/open-close` | 近期独立验证候选 | QQQ 2025-01-03 单日 raw OHLCV 探针通过 | 当前基础计划仅 EOD、约两年历史，不能解决早期覆盖问题 |

现有 universe 数据策略保留 Tushare 为 primary candidate、AkShare 为 secondary，并把 yfinance 加入 `additional_secondary`：[配置](../configs/universes/us_index_etfs_v1.yaml)。任何冲突都必须 `fail_or_manual_review`；禁止均值合成、静默填补，或按回测结果挑选来源。

## 2. 已实现的数据接入与使用方法

### 2.1 安装

在项目虚拟环境中安装可选行情依赖：

```bash
python -m pip install -e '.[market-data]'
```

这会安装 AkShare、交易日历和 yfinance。Tushare、Massive 凭据只放在本机忽略的 `.env`；不得提交、打印或写入 snapshot。

### 2.2 yfinance raw OHLCV

实现位于 [yfinance provider](../quantverify/data/providers/yfinance.py)，导出于 `quantverify.data.providers`。它的关键约束：

- 请求 `interval="1d"`、`auto_adjust=False`、`actions=False`；`Adj Close` 不会升级为 OHLC 字段；
- QuantVerify 的 `end` 是包含式，adapter 会向 yfinance 传入下一个日历日，以适配其排他式 `end`；
- 仅允许 ETF/equity；空响应、范围外日期、重复 session、缺列、非有限数值和无效 OHLCV 都会 fail closed；
- 返回的来源标签是 `yfinance:download:raw`，`available_at` 为该交易日收盘时刻。

最小复现示例：

```python
from datetime import date

from quantverify.core.enums import AssetClass
from quantverify.core.models import AssetId
from quantverify.data.providers import YFinanceUSDailyProvider

asset = AssetId(
    symbol="QQQ", venue="XNAS", asset_class=AssetClass.ETF, currency="USD"
)
bars = YFinanceUSDailyProvider().load_daily(
    asset, start=date(2025, 1, 2), end=date(2025, 1, 10)
)
```

测试位于 [test_yfinance_provider.py](../tests/test_yfinance_provider.py)。当前 41 个单元测试均通过。

### 2.3 Snapshot 与校验流程

1. 永远先抓 provider 原始响应，再生成内容寻址、不可变的 raw snapshot 与 manifest；保存抓取时刻、provider、endpoint、调整口径、schema version 和 SHA-256。
2. raw OHLC 只比较同一 session 的价格水平；调整后序列只比较单期收益和 corporate-action 窗口累计收益。
3. 依据 ADR-0004：raw close 在 10 bps 内 PASS、10–50 bps WARNING、超过 50 bps FAIL；缺失 session、重复、身份不一致和无法解释的公司行动均 fail closed。
4. 不混合或平均两个来源的价格。必须由 Level A 官方资料或第三独立源裁决后，才可选择可追溯的单一值。

当前 `RawSnapshotWriter` 只实现了 AkShare 写入。yfinance provider 的 `fetch_daily_records()` 已提供原始行，下一项工程工作是增加同等不可变的 yfinance snapshot/manifest writer，而不是把结果直接写入研究数据集。

## 3. 已执行的实数验证

所有结果来自 2026-08-10 的本机探针，之后供应商修订历史时应重新运行。

| 检查 | QQQ | DIA | 结果 |
|---|---:|---:|---|
| AkShare raw snapshot | 4,844 行，2001-01-02 至 2026-08-07 | 5,432 行，2005-01-03 至 2026-08-07 | 结构、排序、OHLC、交易日和成交量检查通过；覆盖未通过 |
| yfinance raw long-history | 6,896 行，1999-03-10 至 2026-08-07 | 7,182 行，1998-01-20 至 2026-08-07 | 连通性、字段和归一化通过 |
| AkShare/yfinance raw close 交集 | 4,844 日；p50 约 0、p95 0.014871%、1 日超过 1% | 5,432 日；p50 约 0、最大 0.145817% | QQQ 存在需裁决冲突；DIA 初比高度一致 |
| Massive raw 探针 | 2025-01-03 一行通过 | 未测 | 仅验证当前凭据/endpoint 连通性 |

QQQ 的最大冲突为 **2002-11-01**：AkShare close `24.55`，yfinance close `25.25`，相对差 `2.851324%`。这远超过 50 bps fail 阈值。次大差异也需要作为回归样本保留：2001-04-06 为 0.964185%、2003-04-02 为 0.796663%。

## 4. 问题台账与处理优先级

### P0-1：QQQ 的 AkShare 早期覆盖缺口

- **证据：** AkShare QQQ raw snapshot 从 2001-01-02 才开始；QQQ 的 yfinance 可见历史从 1999-03-10 开始。
- **风险：** 不能跨越缺口计算收益、做滚动指标或以 DIA/插值填补；这会制造未被来源支持的价格。
- **建议处理：** 为 yfinance QQQ 全历史生成不可变 raw snapshot，再按交易日将它与 AkShare 交集/差集明确报告。缺口段须标记为单一候选来源，直到得到第三源或官方资料支持。
- **验收：** 有 versioned manifest、连续 session 报告、来源标记和覆盖决策；不得把缺口值混入已双源通过的数据集。

### P0-2：DIA 2015-04-09 单日缺失

- **证据：** 已保存 AkShare snapshot 缺少该 session；该日对持有期收益与成交时点有影响。
- **建议处理：** 从 yfinance snapshot、第三独立来源和 State Street 官方资料检查该 session 的 OHLCV、基金行动与交易日身份。
- **验收：** 决策记录说明保留、排除或补入的原因；若补入，记录精确 source、snapshot hash、字段和审计者。

### P0-3：QQQ 2002-11-01 raw close 冲突

- **证据：** AkShare `24.55` 对 yfinance `25.25`，差异 2.851324%，超过 ADR-0004 的 FAIL 阈值。
- **待查假设：** 历史修订、拆分/分红口径、供应商字段映射或单日数据更正；在没有证据前不假设任一方正确。
- **建议处理：** 保留两个 raw payload 与 response metadata；用基金官方 corporate-action/history 页面及第三独立日线源比对同一 session 的 OHLCV。必要时扩展为前后各 10 个 session 的价格与收益比较。
- **验收：** 有可复查的裁决证据和回归测试；若无法裁决，该 session 继续 FAIL 并从已验证研究数据集排除。

### P0-4：AkShare `qfq` 存在非正价格

- **证据：** QQQ 2002-05-03 的 low = `-0.9583`；DIA 2009-02-20 的多个 OHLC 字段为负。
- **处理：** `qfq` 已由 adapter fail closed。不得把它称为 total return 或作为价格层输入。
- **验收：** 仅在完整审计复权因子、分红和拆分后，才可以为独立的 adjusted-return 管线另行准入。

### P0-5：Tushare 美股 primary 不可用

- **证据：** token 有效、10,000 积分、无独立美股日线权限；`us_daily_adj` 同时报告上游不可访问。
- **处理：** 先确认/开通独立美股权限；仍失败则向服务商取得上游状态说明。恢复后必须从零抓取 raw snapshot，不能把新返回与旧复权历史静默拼接。
- **验收：** token 权限明确、目标接口可用、QQQ/DIA 全区间 snapshot 与 yfinance/AkShare 比较完成。

### P0-6：yfinance 审计与许可边界

- **证据：** raw provider 和长历史连通性已通过，但没有 yfinance snapshot writer；其项目说明将数据定位为研究/教育用途，并提示 Yahoo API 仅限个人使用。
- **处理：** 实现 immutable snapshot/manifest，记录 SDK 版本和请求参数；在项目文档与产物 metadata 中保留研究/交叉验证限制。
- **验收：** 每次抓取可复现、可哈希、可追溯；未经单独商业授权，不得把 yfinance 设为 production sole source。

### P1：Massive 历史范围不足

- **证据：** 当前计划只覆盖约两年 EOD 历史；单日 probe 已成功。
- **处理：** 仅将其用于近期独立窗口，或在确认许可和成本后升级覆盖目标区间的计划。
- **验收：** 对所选窗口有 raw snapshot 和与另外两源的校验报告；不要把其有限覆盖误写为全历史验证。

### P1：凭据与 HTTP 传输风险

- **证据：** 教程指定 Tushare 专用 HTTP endpoint；凭据由本机 `.env` 管理。
- **处理：** 凭据绝不提交、输出或写入 snapshot；如果服务支持，应迁移 HTTPS，并在排障后轮换已暴露于人工工作流的 token。
- **验收：** 代码库、Git 历史、日志和产物扫描均不含密钥；端点与轮换状态有内部记录。

## 5. 建议执行顺序

1. 实现 yfinance raw snapshot/manifest，并为 QQQ、DIA 抓取完整历史；不要覆盖既有 AkShare snapshot。
2. 运行全量 session/字段/close-tolerance contract tests，生成只读差异报告。
3. 裁决 QQQ 2002-11-01 与 DIA 2015-04-09；每个裁决都保存证据、结论和回归 fixture。
4. 处理 Tushare 权限/上游状态；恢复后以其作为独立 primary candidate 重新验证。
5. 只有在每段历史都有满足 ADR-0004 的覆盖、snapshot、许可记录和双源结果后，才将 M1 状态从 INVALID 改为可研究。

## 6. 相关文件

### 外部接口与许可资料

- [yfinance download API](https://ranaroussi.github.io/yfinance/reference/api/yfinance.download.html)：参数、`auto_adjust` 与日期范围行为。
- [yfinance 项目说明](https://github.com/ranaroussi/yfinance)：研究/教育用途说明及 Yahoo API 的个人使用边界。
- [Massive 日线接口](https://massive.com/docs/rest/stocks/aggregates/daily-ticker-summary)：`v1/open-close` 使用方式、计划覆盖与调整口径。
- [Tushare 美股日线文档](https://tushare.pro/document/2?doc_id=338) 与 [权限说明](https://tushare.pro/document/2?doc_id=290)：目标接口与独立权限边界。

### 仓库内资料

- [数据质量报告](DATA_QUALITY_REPORT_2026-08-10.md)：当前 gate 状态和实测汇总。
- [M1 研究范围](M1_RESEARCH_SCOPE.md)：数据源角色与策略边界。
- [ADR-0004](adr/0004-dual-source-data-validation.md)：双源容差与冲突规则。
- [ADR-0005](adr/0005-akshare-ingestion-boundary.md)：AkShare 接入和 snapshot 边界。
- [AkShare provider](../quantverify/data/providers/akshare.py) 与 [yfinance provider](../quantverify/data/providers/yfinance.py)：归一化和 fail-closed 实现。
- [snapshot writer](../quantverify/data/snapshots.py)：现有 AkShare immutable storage 实现，供 yfinance 方案对照。
