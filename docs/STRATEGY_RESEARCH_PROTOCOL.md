# Investment Strategy Lab — STRATEGY_RESEARCH_PROTOCOL.md

> **定位**：本文件定义 Investment Strategy Lab 中 Agent 研究、翻译、实现、回测、验证和评级任何投资策略时必须遵循的标准流程。  
> **适用对象**：来自论文、书籍、机构报告、博客、X/微博/小红书/雪球帖子、视频口述、聊天记录、截图、人工想法或已有代码的策略。  
> **上位约束**：本文件必须与 `BACKTEST_DATA_INTEGRITY.md` 同时执行；若两者冲突，以更严格的完整性规则为准。  
> **核心目标**：把“听起来有道理的投资观点”变成“定义明确、可以复现、可以证伪、可以做样本外验证的策略假设”。

---

# 0. Agent 的角色

Agent 不是“帮用户把历史曲线调漂亮”的优化器。

Agent 的职责是：

```text
自然语言 / 截图 / 文章 / 视频 / 论文
                ↓
          Claim Extraction
                ↓
        Strategy Formalization
                ↓
           Data Contract
                ↓
        Frozen Strategy Spec
                ↓
        Reproducible Backtest
                ↓
       Robustness & Falsification
                ↓
        Evidence + Strategy Grade
                ↓
       Dashboard / Research Report
```

优先级必须始终是：

```text
定义准确
  >
数据完整
  >
无未来函数
  >
可复现
  >
样本外稳定
  >
风险控制
  >
历史收益率
```

---

# 1. Strategy Research Lifecycle

每个策略必须具有明确状态。

```text
INBOX
  ↓
PARSED
  ↓
FORMALIZED
  ↓
DATA_READY
  ↓
BASELINE_TESTED
  ↓
ROBUSTNESS_TESTED
  ↓
OOS_TESTED
  ↓
REVIEWED
  ↓
────────────────────────
│ CORE / VALIDATED      │
│ RESEARCH / WATCHLIST  │
│ REJECTED              │
│ INVALID               │
────────────────────────
```

## 状态含义

### `INBOX`

刚被收集，还没有进行正式解释。

来源可能是：

- 社交媒体帖子
- 截图
- 论文
- 网友策略
- 用户自己的想法

---

### `PARSED`

Agent 已经区分：

- 作者明确说了什么
- Agent 推测作者可能是什么意思
- 尚未定义的参数
- 无法复现的模糊条件

---

### `FORMALIZED`

策略已经转成：

- 数学公式
- Boolean Rules
- Numeric Score
- Position Sizing Rule
- Execution Rule

不存在“趋势较强”“估值比较低”等无法执行的模糊描述。

---

### `DATA_READY`

策略所需数据：

- 来源明确
- Point-in-Time 合规
- 频率匹配
- 指标定义完整
- 数据质量通过 `BACKTEST_DATA_INTEGRITY.md`

---

### `BASELINE_TESTED`

完成最基础的策略回测，并与合理 Benchmark 比较。

---

### `ROBUSTNESS_TESTED`

完成：

- 参数稳定性
- Rolling Window
- Start-Date
- Transaction Cost
- Regime
- Cross-Asset

等至少一组稳健性测试。

---

### `OOS_TESTED`

完成真正未用于选规则和调参数的数据测试。

---

### `REVIEWED`

Agent 生成完整 Research Card 并决定：

```text
CORE
VALIDATED
RESEARCH
WATCHLIST
REJECTED
INVALID
```

---

# 2. 第一步：Natural Language → Claim Extraction

当 Agent 遇到网上的新策略时，不允许直接写代码。

首先生成：

```yaml
source_claim:
  source_type:
  author:
  source_date:
  source_reference:

  claimed_asset:
  claimed_timeframe:
  claimed_indicator:
  claimed_rule:
  claimed_return:
  claimed_risk:
  claimed_reason:

  explicit_parameters:
  implicit_parameters:
  ambiguous_terms:
  missing_information:
```

---

# 3. Source Claim 与 Agent Interpretation 必须分开

例如帖子：

> 周线 MACD 顶背离之后基本都没行情。

Agent 必须拆成：

## 原始 Claim

```text
作者声称：
周线 MACD 顶背离出现后，后续行情较弱。
```

## 尚未定义的问题

```text
1. “顶背离”精确定义是什么？
2. 两个价格高点间隔多久？
3. MACD 用 DIF 还是柱体？
4. “没行情”是：
   - 未来4周收益 < 0？
   - 未来12周跑输指数？
   - 最大回撤 > 某阈值？
5. 是否要求价格创新高？
6. 局部高点怎么识别？
```

## Agent Interpretation

只能标为：

```text
PROPOSED FORMALIZATION
```

不能写成：

```text
AUTHOR'S ORIGINAL RULE
```

---

# 4. 模糊语言词典

以下表达不能直接进入策略：

```text
低估
高估
超跌
超买
趋势很好
均线发散
量价配合
放量
缩量
突破有效
明显背离
支撑位
压力位
恐慌
市场很贵
风险很高
```

Agent 必须将其转化为参数化定义。

例如：

```text
“低估”
→ PE rolling percentile < 20%

“放量”
→ Volume_t / SMA20(Volume) > 1.5

“明显突破”
→ Close_t > rolling_max(Close, 55).shift(1) × 1.01
```

**如果存在多种合理定义，不允许自行偷偷选择其中一种。**

应创建：

```text
Variant A
Variant B
Variant C
```

分别测试。

---

# 5. Strategy Spec：所有正式策略的统一格式

任何进入正式策略库的策略必须具有一个机器可读 Spec。

推荐 YAML：

```yaml
strategy_id: TREND_SMA_200_V1
name: Price Above SMA200
family: trend
status: candidate
version: 1.0.0

hypothesis:
  statement: >
    Long-term positive price trend may persist, while reducing exposure
    below a long moving average may reduce severe drawdowns.
  expected_edge:
  failure_mode:

asset_scope:
  supported:
    - equity_index
    - equity_etf
    - commodity_index
    - gold
  unsupported:
    - illiquid_microcap

data:
  price_field: total_return_or_adjusted_close
  frequency: daily
  required_history: 260
  point_in_time_required: true

indicators:
  - id: sma200
    type: SMA
    field: close
    window: 200

signal:
  long:
    rule: "close_t > sma200_t"
  defensive:
    rule: "close_t <= sma200_t"

position:
  long_weight: 1.0
  defensive_weight: 0.0

signal_time:
  when: market_close_t

execution:
  when: next_session_open
  price: open
  slippage_bps: 5

rebalance:
  frequency: daily_on_signal_change

benchmark:
  primary: buy_and_hold
  secondary: fixed_dca

parameters:
  tunable:
    ma_window:
      default: 200
      research_grid: [150, 175, 200, 225, 250]

validation:
  parameter_robustness: required
  rolling_window: required
  cross_asset: required
  out_of_sample: required
```

---

# 6. Strategy ≠ Indicator

必须严格区分：

```text
Indicator
Signal
Position
Portfolio
```

例如：

```text
SMA20
```

只是 Indicator。

```text
Close > SMA20
```

是 Signal。

```text
Signal=True → Position=100%
```

才构成最简单的 Strategy。

```text
NASDAQ 60%
Gold 40%
```

则是 Portfolio 层。

---

# 7. Strategy Hypothesis 必须先写，再回测

Agent 必须先记录为什么策略可能有效，再看结果。

格式：

```yaml
hypothesis:
  economic_mechanism:
  behavioral_mechanism:
  risk_premium_mechanism:
  implementation_mechanism:
  competing_explanations:
  falsification_condition:
```

例如 Trend Following：

```text
可能机制：
- 信息逐步反映
- 投资者反应不足
- 资金流与风险管理造成趋势延续

替代解释：
- 策略只是承担特殊尾部风险
- 参数选择造成数据挖掘

证伪条件：
- 多资产、多时期、成本后无法优于简单基准
- 参数邻域极不稳定
```

---

# 8. Freeze Before Backtest

策略正式回测前必须形成：

```text
FROZEN SPEC
```

包括：

- 规则
- 参数
- 数据定义
- Benchmark
- 成交逻辑
- 评价指标
- 样本区间

Freeze 后：

> 不能看到测试集表现不佳后偷偷修改规则，再继续称其为同一次测试。

如果修改：

```text
Strategy Version +1
```

并重新进入研究流程。

---

# 9. 研究问题必须写成可证伪形式

不推荐：

> PE 定投好不好？

推荐：

```text
H1:
在相同累计投入、相同资产、相同期间、相同现金收益假设下，
基于 rolling PE percentile 的动态定投，
是否比固定金额 DCA 提高 XIRR / Calmar，
且不显著增加资金需求？

H0:
两者不存在稳定差异。
```

---

# 10. Benchmark Protocol

每个策略至少需要一个简单 Benchmark。

## 单资产择时

```text
Primary:
Buy & Hold

Secondary:
Fixed DCA 或 Constant 100% Exposure
```

---

## 动态定投

```text
Primary:
Fixed Amount DCA

必须控制：
Total Contribution / Available Budget
```

---

## 资产轮动

至少比较：

```text
Equal Weight
Static 60/40
Buy & Hold Each Asset
```

---

## 风险管理策略

同时报告：

```text
Return
Volatility
Max Drawdown
Sharpe
Sortino
Calmar
```

因为其目标可能不是提高 CAGR。

---

# 11. Core Metrics

## Return

```text
CAGR
Total Return
Annualized Return
XIRR
Time-Weighted Return
Ending Wealth
```

---

## Risk

```text
Annualized Volatility
Max Drawdown
Ulcer Index
Downside Deviation
Worst Month
Worst Year
Tail Loss
```

---

## Risk Adjusted

```text
Sharpe
Sortino
Calmar
Information Ratio
```

---

## Trading

```text
Turnover
Trade Count
Average Holding Period
Win Rate
Profit Factor
Exposure
```

---

## DCA

```text
Total Contribution
Cash Balance
Average Cost
Ending Wealth
XIRR
Worst Contribution Drawdown
```

---

# 12. 参数分类

参数必须分成：

## Structural Parameter

决定策略本质。

例如：

```text
趋势窗口
估值指标
资产池
```

---

## Implementation Parameter

例如：

```text
slippage
rebalance_day
signal_delay
```

---

## Calibration Parameter

例如：

```text
PE percentile threshold = 20%
```

---

Agent 必须避免把 Implementation Noise 当成 Alpha 来源。

---

# 13. Parameter Search Protocol

参数研究必须分层。

## Level 0 — Literature / Source Parameter

先复现原策略。

例如作者写：

```text
SMA200
```

先测试 SMA200。

---

## Level 1 — Local Neighborhood

测试邻近参数：

```text
SMA:
150
175
200
225
250
```

目标不是找最优点，而是观察：

```text
Performance Surface
```

---

## Level 2 — Broad Sensitivity

例如：

```text
50 – 300
```

观察策略是否存在宽阔稳定区域。

---

## 禁止

```text
在测试集跑 10,000 个参数
→ 找最高 Sharpe
→ 称为策略有效
```

---

# 14. Parameter Robustness Score

建议计算：

```text
Neighborhood Stability
Rank Stability
Sign Stability
Performance Dispersion
```

一种简单定义：

```text
Robust:
周围 ±20% 参数多数仍保持相同方向的优势。

Fragile:
只有极小参数点表现突出。
```

Dashboard 应显示：

```text
Best Parameter
Median Parameter Performance
Neighbor Performance
```

而不是只显示 Best。

---

# 15. 时间维度验证

任何 Core Strategy 至少执行：

## Full Period

整体历史。

## Rolling Window

例如：

```text
3Y
5Y
10Y
15Y
```

## Rolling Start Date

避免起点偏差。

## Rolling End Date

避免终点偏差。

---

# 16. Market Regime Validation

建议最少分析：

```text
Bull
Bear
Sideways

High Volatility
Low Volatility

High Inflation
Low Inflation

Rising Rate
Falling Rate
```

不要假设一个策略必须所有时期都有效。

研究目标是识别：

```text
Where it works
Where it fails
Why
```

---

# 17. Cross-Asset Validation

如果策略宣称是一般价格行为规律，应进行跨资产验证。

推荐首批：

```text
NASDAQ-100
S&P 500
Dow Jones
沪深300
Gold
US Treasury
```

若是个股策略：

```text
贵州茅台
US Quality Basket
```

可作为补充。

---

# 18. Cross-Frequency Validation

对于技术策略：

```text
Daily
Weekly
Monthly
```

不是简单重复。

例如周线 MACD 必须：

```text
Daily OHLC
   ↓
Weekly OHLC
   ↓
Weekly MACD
```

而不是：

```text
Daily MACD
   ↓
Friday Sample
```

---

# 19. Out-of-Sample Protocol

至少支持以下一种：

## Fixed Split

```text
Research
Validation
OOS
```

---

## Walk Forward

```text
Train Window
     ↓
Freeze Parameter
     ↓
Next Period
     ↓
Repeat
```

---

## Expanding Window

更适合：

- 历史估值百分位
- 宏观模型
- 参数估计

---

# 20. Transaction Cost Stress Test

任何有换手的策略至少测试：

```text
0 bps
5 bps
10 bps
25 bps
```

视资产调整。

若：

```text
0 bps 有效
5 bps 失效
```

则策略应标记：

```text
IMPLEMENTATION_FRAGILE
```

---

# 21. Signal Delay Stress Test

特别重要。

测试：

```text
T+1 Open
T+1 Close
T+2 Open
```

若仅能依赖极理想成交时间取得优势：

```text
EXECUTION_FRAGILE
```

---

# 22. Randomization / Placebo Tests

适合部分策略。

例如：

```text
随机改变定投日期
随机移动信号 ±1–5 日
随机抽取同数量交易
```

目的：

> 判断策略是否真的利用了规则，而不是碰巧依赖某几个极端日期。

---

# 23. Multiple Testing Log

每次研究必须记录：

```yaml
research_search_space:
  strategies_tested:
  parameter_sets_tested:
  assets_tested:
  windows_tested:
  metrics_used_for_selection:
```

如果测试空间非常大：

Strategy Grade 必须受到惩罚。

---

# 24. Economic Significance > Statistical Curiosity

即使策略统计上略好，也必须问：

```text
改善有多大？
是否值得复杂度？
成本后还有多少？
是否显著降低回撤？
是否改善投资体验？
```

例如：

```text
CAGR +0.1%
但规则复杂 20 倍
```

通常不应升级为 Core。

---

# 25. Complexity Penalty

同等表现下：

```text
简单策略 > 复杂策略
```

建议 Complexity Level：

```text
C1:
1–2 个参数

C2:
3–5 个参数

C3:
6–10 个参数

C4:
>10 个参数 / 多层条件
```

复杂度越高：

- 越需要 OOS
- 越需要更大样本
- 越需要严格 Multiple Testing 控制

---

# 26. Strategy Evidence Level

注意：

> **Evidence Level 与历史回测表现分开。**

建议：

### E3 — Strong External Evidence

存在：

- 多篇学术研究
- 多市场 / 长时期研究
- 清晰经济机制

---

### E2 — Meaningful Evidence

存在：

- 论文或机构系统性研究
- 但范围较窄或结论存在争议

---

### E1 — Practitioner / Heuristic

常见于：

- 技术分析
- 行业实践
- 社交媒体

可研究，但不能因为流行就视为有效。

---

### E0 — Unverified Hypothesis

新想法或无法找到可靠外部证据。

---

# 27. Popularity Level

与 Evidence 分开记录：

```text
P3 = 极常见 / 主流
P2 = 常见
P1 = 小众
P0 = 实验性
```

例如：

```text
MACD
Popularity = P3

但某个具体“MACD 顶背离后必跌”规则
Evidence 可能只有 E0/E1
```

这是系统必须保持的区分。

---

# 28. Strategy Robustness Dimensions

每个策略至少评价：

```text
R1 Parameter Robustness
R2 Time Robustness
R3 Asset Robustness
R4 Regime Robustness
R5 Cost Robustness
R6 Execution Robustness
R7 Data Robustness
R8 OOS Robustness
```

每项：

```text
PASS
MIXED
FAIL
NOT_TESTED
```

---

# 29. 不建议把所有维度压成一个“神奇分数”

Dashboard 可以有 Summary Score，但必须保留原始维度。

例如：

```text
Evidence       E3
Data Quality   A
Parameter      PASS
Cross Asset    PASS
OOS            MIXED
Cost           PASS
Complexity     C1
```

比：

```text
Strategy Score = 87.3
```

更有信息量。

---

# 30. Strategy Grade

最终 Grade 只能在数据完整性通过后生成。

## S

```text
Data Integrity: PASS
Evidence: strong
OOS: strong
Cross-Asset: strong
Parameter: robust
Costs: robust
Failure modes understood
```

极少策略应得到 S。

---

## A

```text
较稳定
大部分关键验证通过
存在可解释局限
```

---

## B

```text
有研究价值
但存在明显 regime / asset / parameter dependency
```

---

## C

```text
结果脆弱
或优势很小
或主要依赖样本选择
```

---

## D

```text
无法提供稳定证据
与随机 / 简单 benchmark 难以区分
```

---

## INVALID

出现：

```text
Look-Ahead
错误复权
错误资产
Point-in-Time Failure
严重数据错误
```

---

# 31. Strategy Promotion Rule

建议：

```text
INBOX
  ↓
CANDIDATE
  ↓
RESEARCH
  ↓
VALIDATED
  ↓
CORE
```

### CORE 条件

至少：

```text
[ ] Data Integrity PASS
[ ] 精确定义
[ ] Benchmark 完成
[ ] Parameter Robustness
[ ] Rolling Window
[ ] Cost Stress
[ ] OOS
[ ] Failure Mode 已记录
```

不要求策略必须 outperform Buy & Hold。

例如：

> 一个长期趋势策略即使 CAGR 略低，但显著降低 Max Drawdown，也可能是 Core Risk Strategy。

---

# 32. Reject 不等于“永远没用”

`REJECTED` 的原因必须分类：

```text
NO_EDGE
DATA_UNAVAILABLE
TOO_FRAGILE
TOO_COMPLEX
HIGH_COST
SAMPLE_TOO_SMALL
NOT_REPRODUCIBLE
CLAIM_FALSE
```

未来如果数据或研究条件改善，可以重新打开。

---

# 33. 网上策略 Intake Protocol

当用户发来帖子/截图：

Agent 顺序必须是：

```text
1. 保存原文 Claim
2. 不评价对错
3. 找出所有可执行条件
4. 列出模糊条件
5. 搜索原始来源/理论依据
6. 建立 Strategy Candidate
7. 给出 Formalization Variants
8. 确定最小可行数据
9. 先做 Baseline
10. 再做完整 Robustness
```

---

# 34. 对“作者晒收益图”的处理

收益截图不能作为策略有效性的主要证据。

Agent 必须寻找：

```text
完整规则
起止日期
标的
资金流
成交时间
复权
交易成本
是否调参
是否包含失败版本
```

如果缺失：

```text
SOURCE_CLAIM_NOT_REPRODUCIBLE
```

---

# 35. 对“历史胜率很高”的处理

胜率不是核心绩效指标。

例如策略：

```text
99 次 +1%
1 次 -80%
```

胜率很高，但风险极差。

必须同时检查：

```text
Payoff Ratio
Tail Loss
Max Drawdown
Expected Value
```

---

# 36. 对“背离”的特殊处理

背离策略通常存在较大主观性。

必须定义：

```text
Pivot Algorithm
Minimum Pivot Distance
Prominence
Price Higher High Threshold
Indicator Lower High Threshold
Maximum Lookback
Confirmation Delay
```

否则不可复现。

---

# 37. 对“均线多头排列”的标准化

推荐基础定义：

```text
Close > SMA5 > SMA10 > SMA20 > SMA30
```

但可以扩展：

```text
Slope(SMA20, N) > 0
Distance(SMA5, SMA30) > threshold
```

不同版本必须分开编号。

---

# 38. 对“估值低就多投”的标准化

至少创建三个 Candidate：

## A — Absolute Threshold

```text
PE < 25 → 2X
25–35 → 1X
>35 → 0.5X
```

## B — Expanding Percentile

```text
PE percentile <20% → 2X
20–80% → 1X
>80% → 0.5X
```

## C — Rolling 10Y Percentile

同上，但只使用过去十年。

不得直接把三者混成同一个策略。

---

# 39. Composite Strategy Protocol

例如：

```text
Valuation
+
Trend
+
Momentum
+
Risk
```

必须先测试单因子：

```text
V
T
M
R
```

再测试组合：

```text
V+T
V+M
T+M
V+T+M
V+T+M+R
```

防止：

> 复杂组合看起来有效，但其实只有一个因子贡献收益。

---

# 40. Ablation Test

Composite Strategy 必须做消融：

```text
Full Model
- Valuation
- Trend
- Momentum
- Risk
```

报告：

```text
Contribution to Return
Contribution to Drawdown
Contribution to Turnover
```

---

# 41. Strategy Comparison Protocol

禁止只做：

```text
A CAGR 15%
B CAGR 13%
→ A 更好
```

必须比较至少：

```text
Return
Risk
Drawdown
Turnover
Exposure
Capital Requirement
Complexity
Robustness
```

---

# 42. Paired Comparison

尽量保证：

```text
Same asset
Same period
Same source
Same costs
Same currency
Same contribution schedule
```

使差异主要来自策略。

---

# 43. Strategy Card

每个策略最终必须生成一张标准卡片：

```yaml
strategy_id:
name:
family:
status:

one_line_description:

source:
original_claim:

formal_rule:

assets:
frequency:

parameters:

economic_rationale:

benchmark:

full_period_result:
oos_result:

robustness:
  parameter:
  time:
  asset:
  regime:
  cost:
  execution:

evidence_level:
popularity_level:
complexity_level:
data_quality:

known_failure_modes:

strategy_grade:

agent_conclusion:
```

---

# 44. Agent 最终报告模板

```markdown
# Strategy Review — <name>

## 1. Original Claim
## 2. What Is Actually Defined
## 3. Ambiguities
## 4. Formal Strategy Rule
## 5. Data Requirements
## 6. Benchmark
## 7. Baseline Backtest
## 8. Parameter Robustness
## 9. Rolling Window
## 10. Regime Test
## 11. Cross-Asset Test
## 12. OOS / Walk Forward
## 13. Cost & Execution Stress
## 14. Failure Modes
## 15. Evidence Review
## 16. Strategy Grade
## 17. Current Signal
```

---

# 45. Agent 输出语言规范

允许：

> “在 2005–2026 的当前测试设定下，该规则降低了最大回撤，但没有稳定提高 CAGR。”

不允许：

> “这个策略能够规避熊市。”

除非有充分证据。

---

# 46. Current Signal 与 Backtest Result 分开

Dashboard 中：

```text
Current Signal
```

只是策略今天给出的状态。

不能因为：

```text
Signal = BUY
```

就写：

> 现在应该买。

推荐：

```text
TREND_SMA200:
Current mechanical signal = LONG

This is a model output, not a forecast guarantee.
```

---

# 47. Research Log

每一次研究运行建议保存：

```yaml
run_id:
timestamp:
strategy_version:
code_commit:
data_version:
asset:
period:
parameter_set:
result_hash:
notes:
```

避免未来无法回答：

> 为什么上个月这个策略的收益率是 11.2%，现在变成 10.7%？

---

# 48. 文件结构建议

```text
strategies/
├── universe/
│   └── STRATEGY_UNIVERSE.md
│
├── specs/
│   ├── TREND_SMA200_V1.yaml
│   ├── VAL_PE_DCA_V1.yaml
│   └── MOM_DUAL_V1.yaml
│
├── research/
│   ├── TREND_SMA200/
│   └── VAL_PE_DCA/
│
└── rejected/
```

---

# 49. 推荐 Agent 自动任务

## Daily

```text
更新价格
更新技术指标
生成 Current Signal
Data Quality Check
```

---

## Weekly

```text
更新周线指标
检查 Weekly Strategy Signals
```

---

## Monthly

```text
更新估值
策略状态汇总
Performance Attribution
```

---

## Quarterly

```text
数据源审计
策略稳定性回顾
Research Watchlist 更新
```

---

## Annual / Semiannual

```text
完整 OOS / Rolling Revalidation
Strategy Grade Review
```

---

# 50. Reference Evidence Anchors

以下文献可作为 Strategy Universe 中部分策略的研究起点，而不是“保证策略未来有效”的证明。

- Brock, Lakonishok & LeBaron (1992), *Simple Technical Trading Rules and the Stochastic Properties of Stock Returns* — moving-average / trading-range-break rules.
- De Bondt & Thaler (1985), *Does the Stock Market Overreact?* — long-horizon reversal / overreaction.
- Fama & French (1992), *The Cross-Section of Expected Stock Returns* — size / book-to-market cross-sectional evidence.
- Jegadeesh & Titman (1993), *Returns to Buying Winners and Selling Losers* — cross-sectional momentum.
- Moskowitz, Ooi & Pedersen (2012), *Time Series Momentum* — trend / time-series momentum across futures markets.
- Faber, *A Quantitative Approach to Tactical Asset Allocation* — long moving-average tactical allocation.
- Moreira & Muir, *Volatility-Managed Portfolios* — volatility-scaled exposure.
- Cederburg et al., *On the Performance of Volatility-Managed Portfolios* — important caution that direct outperformance is not universal.
- Antonacci, *Risk Premia Harvesting Through Dual Momentum* — relative + absolute momentum framework.

---

# 51. Agent 最终行为准则

遇到任何新策略时：

```text
Do not ask:
“怎样让这个策略收益最高？”

Ask:
“这个策略究竟在声称什么？”
“能不能写成确定规则？”
“当时真的能获得这些数据吗？”
“最简单的 benchmark 是什么？”
“换参数、换时期、换市场后还成立吗？”
“成本后还成立吗？”
“样本外还成立吗？”
“在哪里会失败？”
```

只有回答完这些问题，策略才有资格从：

```text
Interesting Idea
```

升级为：

```text
Research Strategy
```

更进一步，才可能成为：

```text
Core Strategy
```
