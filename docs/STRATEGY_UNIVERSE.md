# Investment Strategy Lab — STRATEGY_UNIVERSE.md

> **定位**：本文件维护 Investment Strategy Lab 的“策略宇宙（Strategy Universe）”。  
> **用途**：统一策略分类、命名、研究优先级、适用资产、主要参数、外部证据强弱以及潜在失败模式。  
> **注意**：列入 Strategy Universe **不等于策略有效**。Universe 是研究候选池，不是推荐清单。  
> **配套协议**：所有正式研究必须执行 `STRATEGY_RESEARCH_PROTOCOL.md` 与 `BACKTEST_DATA_INTEGRITY.md`。

---

# 0. 标签说明

## Popularity

```text
⭐⭐⭐ P3 — 极常见 / 主流研究或投资实践中反复出现
⭐⭐   P2 — 常见
⭐     P1 — 小众但有代表性
○      P0 — 实验性 / 新假设
```

Popularity 只表示“常见程度”，**不表示有效性**。

---

## Evidence

```text
E3 — 有较强、较广泛外部研究基础
E2 — 有实证/机构研究，但结论或适用范围存在限制
E1 — 常见 practitioner / technical heuristic，严格证据有限或混合
E0 — 未验证假设
```

---

## Research Priority

```text
CORE      第一阶段必须实现，用作整个实验室的 benchmark
P1        高优先级
P2        中优先级
P3        后续 / 实验
```

---

# 1. 第一阶段 Core Strategy Set

第一版不要一上来实现所有策略。

建议先固定以下 Core Set：

| ID | 策略 | Family | Popularity | Evidence | Priority |
|---|---|---|---|---|---|
| B01 | Buy & Hold | Baseline | ⭐⭐⭐ | E3 | CORE |
| B02 | Fixed DCA | Contribution | ⭐⭐⭐ | E3/Benchmark | CORE |
| V02 | PE Percentile DCA | Valuation | ⭐⭐⭐ | E1-E2 | CORE |
| T02 | Price vs SMA200 / 10M SMA | Trend | ⭐⭐⭐ | E2-E3 | CORE |
| T05 | MA5/10/20/30 Structure | Trend | ⭐⭐⭐ | E1 | CORE |
| M01 | 12M Time-Series Momentum | Momentum | ⭐⭐⭐ | E3 | CORE |
| M03 | Relative Momentum | Rotation | ⭐⭐⭐ | E3 | CORE |
| M04 | Dual Momentum | Rotation | ⭐⭐ | E2 | CORE |
| BR01 | Donchian / N-day Breakout | Breakout | ⭐⭐⭐ | E2-E3 | CORE |
| R01 | Volatility Targeting | Risk | ⭐⭐⭐ | E2-E3 | CORE |
| A01 | Static 60/40 | Allocation | ⭐⭐⭐ | Benchmark | CORE |
| A03 | Periodic Rebalancing | Allocation | ⭐⭐⭐ | E2 | CORE |
| C01 | Valuation + Trend | Composite | ⭐⭐ | E1-E2 | CORE-Research |
| C02 | Trend + Momentum + Vol | Composite | ⭐⭐ | E1-E2 | CORE-Research |

这组策略覆盖：

```text
不择时
定投
估值
趋势
动量
突破
风险控制
资产配置
组合信号
```

足以作为项目 V0 / V1 的主骨架。

---

# 2. Family A — Baseline / Contribution Strategies

## B01 — Buy & Hold

```text
Rule:
Initial capital → 100% asset → hold
```

用途：

> 所有单资产策略最重要的 Benchmark。

- Popularity: ⭐⭐⭐
- Evidence: Benchmark
- Priority: CORE
- Parameters: none
- Risk: Max Drawdown 高
- Key issue: Price Return vs Total Return

---

## B02 — Fixed Amount DCA

```text
Every period:
Invest fixed amount A
```

频率：

```text
Daily
Weekly
Monthly
```

- Popularity: ⭐⭐⭐
- Evidence: Benchmark / household investing practice
- Priority: CORE
- Best assets: broad indices / ETF
- Metrics: XIRR, Ending Wealth, Total Contribution

---

## B03 — Fixed Share DCA

每期买固定股数，而不是固定金额。

```text
shares_t = constant
```

- Popularity: ⭐
- Evidence: E1
- Priority: P3
- Risk: 资金投入随价格变化，不适合与 Fixed Amount DCA 直接比较

---

## B04 — Value Averaging

设定目标资产路径：

```text
Target Value_t = Target Value_{t-1} + Growth
```

实际投入：

```text
Contribution_t = Target Value_t - PortfolioValue_t
```

下跌时需要投入更多资金。

- Popularity: ⭐⭐
- Evidence: E1-E2
- Priority: P2
- Critical Risk: 极端熊市资金需求可能暴增

---

## B05 — Drawdown-Weighted DCA

例如：

```text
Drawdown <10%  → 1X
10–20%         → 1.5X
20–30%         → 2X
>30%           → 3X
```

- Popularity: ⭐⭐
- Evidence: E1
- Priority: P1
- Hypothesis: 逆周期投入
- Risk: 趋势性熊市中持续加码

---

# 3. Family V — Valuation Strategies

## V01 — Absolute PE Threshold

例如截图式策略：

```text
PE >= 35      → 0.67X
25 < PE < 35  → 1.0X
PE <= 25      → 2.0X
```

- Popularity: ⭐⭐⭐
- Evidence: E1-E2
- Priority: P1
- Best assets: equity index / mature profitable stocks
- Main Risk: 不同资产 PE 中枢不同；阈值容易样本依赖

---

## V02 — PE Percentile DCA

推荐 Core 版本。

```text
PE percentile >80% → 0.5X
20–80%             → 1X
<20%               → 2X
```

Percentile 必须是：

```text
Expanding
```

或：

```text
Rolling N-year
```

禁止全样本泄漏。

- Popularity: ⭐⭐⭐
- Evidence: E1-E2
- Priority: CORE
- Main Parameters:
  - valuation definition
  - percentile window
  - thresholds
  - multipliers

---

## V03 — PB Percentile DCA

适合：

- 银行
- 保险
- 部分成熟资产
- broad equity indices

对轻资产科技股解释力可能较弱。

- Popularity: ⭐⭐
- Evidence: E2
- Priority: P2

---

## V04 — CAPE / Smoothed PE Allocation

使用长期平滑盈利：

```text
CAPE low  → higher equity allocation
CAPE high → lower equity allocation
```

- Popularity: ⭐⭐⭐
- Evidence: E2-E3 for long-horizon return predictability
- Priority: P1
- Frequency: monthly / quarterly
- Main Risk: 长期高估状态可以维持很多年，不适合简单短期择时

---

## V05 — Earnings Yield vs Bond Yield

```text
Earnings Yield = 1 / PE
Spread = Earnings Yield - Bond Yield
```

依据 Spread 调整股权风险暴露。

- Popularity: ⭐⭐
- Evidence: E1-E2
- Priority: P2
- Main Risk: 利率期限、盈利定义、风险溢价口径复杂

---

## V06 — Dividend Yield Timing

例如：

```text
Dividend Yield percentile high → overweight
```

- Popularity: ⭐⭐
- Evidence: E2
- Priority: P2
- Best: broad indices / dividend equities

---

## V07 — Multi-Valuation Composite

组合：

```text
PE
PB
PS
Dividend Yield
FCF Yield
```

形成：

```text
Valuation Score
```

- Popularity: ⭐⭐
- Evidence: E2
- Priority: P2
- Risk: 参数过多；不同资产不可硬套

---

# 4. Family T — Trend / Moving Average

## T01 — Price > SMA20

```text
Close > SMA20 → Risk On
```

- Popularity: ⭐⭐⭐
- Evidence: E1-E2
- Priority: P2
- Frequency: daily
- Risk: 高频 Whipsaw

---

## T02 — Price > SMA200 / 10-Month SMA

经典长期趋势过滤。

```text
Close > SMA200 → Long
Close <= SMA200 → Defensive
```

或月线：

```text
Month-end Price > SMA10M
```

- Popularity: ⭐⭐⭐
- Evidence: E2-E3
- Priority: CORE
- Main Goal: often more useful as drawdown/risk filter than pure return maximizer
- Research: test MA150–250 neighborhood

---

## T03 — SMA50 / SMA200 Golden Cross

```text
SMA50 > SMA200 → Long
SMA50 <= SMA200 → Defensive
```

- Popularity: ⭐⭐⭐
- Evidence: E1-E2
- Priority: P1
- Risk: signal lag

---

## T04 — Dual Moving Average Crossover

```text
Fast MA > Slow MA → Long
```

Research Grid:

```text
Fast: 5,10,20,50
Slow: 50,100,150,200
```

- Popularity: ⭐⭐⭐
- Evidence: E2
- Priority: P1

---

## T05 — MA5/10/20/30 Structure Score

非常贴合本项目。

### Strong Bull

```text
Close > SMA5 > SMA10 > SMA20 > SMA30
Score = +4
```

### Strong Bear

```text
Close < SMA5 < SMA10 < SMA20 < SMA30
Score = -4
```

中间状态根据 Pairwise Order 评分。

- Popularity: ⭐⭐⭐
- Evidence: E1
- Priority: CORE
- Research Need: 必须验证它是否比单一 SMA20/SMA200 提供额外信息

---

## T06 — Moving Average Slope

```text
Slope(SMA20, 5) > 0
```

或：

```text
SMA20_t / SMA20_{t-N} - 1
```

- Popularity: ⭐⭐
- Evidence: E1-E2
- Priority: P2

---

## T07 — Trend Distance

```text
Distance = Close / SMA200 - 1
```

将趋势变成连续信号。

例如：

```text
Distance > +5% → Strong Trend
-5% to +5%     → Neutral
< -5%          → Weak
```

- Popularity: ⭐⭐
- Evidence: E1
- Priority: P2

---

## T08 — Weekly Trend Filter

在周线数据上计算：

```text
Price
SMA10W
SMA20W
SMA30W
```

- Popularity: ⭐⭐⭐
- Evidence: E1-E2
- Priority: P1
- Benefit: 降低日线噪音
- Risk: 更慢的风险响应

---

## T09 — MACD Trend

例如：

```text
DIF > DEA
AND
DIF > 0
```

- Popularity: ⭐⭐⭐
- Evidence: E1
- Priority: P2
- Important: MACD 是 Indicator；需要完整 Signal Rule 才是策略

---

## T10 — Weekly MACD Trend

在 Weekly OHLC 上重新计算 MACD。

- Popularity: ⭐⭐⭐
- Evidence: E1
- Priority: P2

---

## T11 — ADX Trend Strength Filter

例如：

```text
Trend Signal
AND
ADX14 > 25
```

用于过滤弱趋势。

- Popularity: ⭐⭐
- Evidence: E1
- Priority: P3

---

# 5. Family M — Momentum / Relative Strength / Rotation

## M01 — Time-Series Momentum 12M

```text
Return_{t-12m,t} > 0 → Long
else → Defensive
```

- Popularity: ⭐⭐⭐
- Evidence: E3
- Priority: CORE
- Assets: equities / bonds / commodities / FX where implementable
- Main Risk: trend reversals / crash-like reversals

---

## M02 — Multi-Horizon Momentum

例如：

```text
Score =
0.2 × 1M
+0.3 × 3M
+0.3 × 6M
+0.2 × 12M
```

- Popularity: ⭐⭐⭐
- Evidence: E2
- Priority: P1
- Risk: weights easily overfit

---

## M03 — Relative Momentum

在资产池：

```text
NASDAQ
S&P500
HS300
Gold
Treasury
```

选择过去 N 月表现最强者。

- Popularity: ⭐⭐⭐
- Evidence: E3
- Priority: CORE

---

## M04 — Dual Momentum

```text
Step 1:
Relative Momentum → select strongest risky asset

Step 2:
Absolute Momentum > threshold ?
Yes → hold selected asset
No  → defensive asset
```

- Popularity: ⭐⭐
- Evidence: E2
- Priority: CORE
- Risk: asset universe choice can dominate result

---

## M05 — 12-1 Momentum

常见横截面动量定义：

```text
Past 12 months excluding most recent month
```

- Popularity: ⭐⭐⭐
- Evidence: E3
- Priority: P1
- Best use: stock / sector ranking

---

## M06 — Sector Momentum Rotation

```text
Rank sectors by 6M/12M momentum
Hold Top K
```

- Popularity: ⭐⭐⭐
- Evidence: E2-E3
- Priority: P1
- Risk: historical sector constituent bias

---

## M07 — Risk-Adjusted Momentum

```text
Momentum / Volatility
```

或：

```text
Return / MaxDrawdown
```

作为排名。

- Popularity: ⭐⭐
- Evidence: E1-E2
- Priority: P2

---

## M08 — Momentum Breadth

例如：

```text
% constituents above SMA200
% constituents with positive 6M momentum
```

决定指数暴露。

- Popularity: ⭐⭐
- Evidence: E1
- Priority: P2
- Data Risk: point-in-time constituents

---

# 6. Family BR — Breakout / Channel

## BR01 — Donchian N-Day Breakout

```text
Close > prior N-day high → Long
Close < prior M-day low  → Exit
```

经典参数：

```text
20/10
55/20
```

- Popularity: ⭐⭐⭐
- Evidence: E2-E3
- Priority: CORE

---

## BR02 — Trading Range Break

```text
Price breaks rolling resistance/high
```

- Popularity: ⭐⭐⭐
- Evidence: E2
- Priority: P1

---

## BR03 — ATR Breakout

```text
Close > SMA + k × ATR
```

- Popularity: ⭐⭐
- Evidence: E1-E2
- Priority: P2

---

## BR04 — Bollinger Breakout

注意这不是均值回归版本。

```text
Close > Upper Band → Trend Entry
```

- Popularity: ⭐⭐
- Evidence: E1
- Priority: P3

---

# 7. Family MR — Mean Reversion / Oscillator

## MR01 — RSI Oversold

```text
RSI14 < 30 → Buy
```

必须定义退出：

```text
RSI > 50
or
N-day holding period
```

- Popularity: ⭐⭐⭐
- Evidence: E1
- Priority: P2
- Risk: 强趋势下“超卖”可持续很久

---

## MR02 — RSI2 Short-Term Mean Reversion

```text
RSI2 very low
AND long-term trend positive
```

- Popularity: ⭐⭐
- Evidence: E1
- Priority: P2
- Best: liquid equity indices
- High sensitivity: execution cost

---

## MR03 — Bollinger Mean Reversion

```text
Close < Lower Band → Buy
Exit near Midline
```

- Popularity: ⭐⭐⭐
- Evidence: E1
- Priority: P2

---

## MR04 — Z-Score Mean Reversion

```text
Z = (Price - MA) / Std
Z < -k → Long
```

- Popularity: ⭐⭐⭐
- Evidence: E1-E2
- Priority: P2

---

## MR05 — Long-Horizon Reversal

过去多年极弱的股票/资产出现反转。

- Popularity: ⭐⭐
- Evidence: E2-E3
- Priority: P2
- Main reference area: overreaction literature
- Risk: value traps / delisting bias

---

## MR06 — Drawdown Recovery

```text
Drawdown > X
→ increase allocation
```

- Popularity: ⭐⭐
- Evidence: E1
- Priority: P2

---

## MR07 — Gap / Extreme Return Reversal

例如：

```text
1-day return < -Nσ
→ mean-reversion entry
```

- Popularity: ⭐⭐
- Evidence: E1
- Priority: P3
- Risk: event-driven jumps are not ordinary noise

---

# 8. Family R — Volatility / Risk Management

## R01 — Volatility Targeting

```text
Weight_t =
TargetVol / EstimatedVol_t
```

并设置：

```text
min_weight
max_weight
```

- Popularity: ⭐⭐⭐
- Evidence: E2-E3
- Priority: CORE
- Critical tests:
  - leverage cap
  - smoothing
  - turnover
  - volatility estimator

---

## R02 — Inverse Volatility Position Sizing

多资产：

```text
w_i ∝ 1 / σ_i
```

- Popularity: ⭐⭐⭐
- Evidence: E2
- Priority: P1

---

## R03 — Drawdown Control

例如：

```text
DD <10% → 100%
10–20%   → 75%
20–30%   → 50%
>30%     → 25%
```

- Popularity: ⭐⭐
- Evidence: E1
- Priority: P2
- Risk: 卖在底部 / 复苏迟滞

---

## R04 — Volatility Regime Filter

```text
Realized Vol high → reduce risk
```

或：

```text
VIX high → reduce risk
```

- Popularity: ⭐⭐⭐
- Evidence: E1-E2
- Priority: P1
- Key distinction: realized vs implied vol

---

## R05 — ATR Position Sizing

```text
Position Size ∝ RiskBudget / ATR
```

- Popularity: ⭐⭐⭐
- Evidence: E1-E2
- Priority: P2

---

## R06 — Maximum Drawdown Budget

动态调整：

```text
Remaining Risk Budget
```

- Popularity: ⭐
- Evidence: E1
- Priority: P3

---

# 9. Family A — Asset Allocation / Rebalancing

## A01 — Static 60/40

```text
60% Equity
40% Bond
```

- Popularity: ⭐⭐⭐
- Evidence: Benchmark
- Priority: CORE

---

## A02 — Equal Weight Multi-Asset

例如：

```text
Equity
Bond
Gold
Commodity
```

各 25%。

- Popularity: ⭐⭐⭐
- Evidence: E2
- Priority: P1

---

## A03 — Calendar Rebalancing

```text
Monthly
Quarterly
Annual
```

恢复目标权重。

- Popularity: ⭐⭐⭐
- Evidence: E2
- Priority: CORE

---

## A04 — Threshold Rebalancing

例如：

```text
Target = 60/40

Only rebalance when
|actual-target| > 5%
```

- Popularity: ⭐⭐
- Evidence: E2
- Priority: P1

---

## A05 — Risk Parity

```text
Risk Contribution_i ≈ Equal
```

- Popularity: ⭐⭐⭐
- Evidence: E2
- Priority: P1
- Main Risk: covariance estimation / leverage / bond regime

---

## A06 — Minimum Variance

优化：

```text
min w'Σw
```

- Popularity: ⭐⭐⭐
- Evidence: E2
- Priority: P2
- Risk: estimation error / concentrated weights

---

## A07 — Maximum Diversification

目标：

```text
maximize weighted individual vol / portfolio vol
```

- Popularity: ⭐⭐
- Evidence: E2
- Priority: P3

---

## A08 — Permanent Portfolio / All-Weather-Like Static Mix

多资产静态组合：

```text
Stocks
Bonds
Gold
Cash / Commodities
```

- Popularity: ⭐⭐⭐
- Evidence: E1-E2
- Priority: P2
- Note: 各种“All Weather”公开版本定义不同，不能混用

---

# 10. Family F — Factor / Stock Selection

这一组只有在项目扩展到“股票池”后才优先。

---

## F01 — Value Factor

例如：

```text
High Book-to-Market
Low PE
High FCF Yield
```

- Popularity: ⭐⭐⭐
- Evidence: E3
- Priority: P1 after stock-universe infrastructure
- Data Risk: delisting + PIT fundamentals

---

## F02 — Quality Factor

例如：

```text
ROE
Gross Profitability
Stable Earnings
Low Leverage
```

- Popularity: ⭐⭐⭐
- Evidence: E2-E3
- Priority: P2

---

## F03 — Low Volatility

```text
Rank stocks by historical volatility
Hold low-vol names
```

- Popularity: ⭐⭐⭐
- Evidence: E2-E3
- Priority: P2

---

## F04 — Size

Small vs large capitalization.

- Popularity: ⭐⭐⭐
- Evidence: E3
- Priority: P3 for this project
- Reason: 与当前“指数/核心资产择时”主线关系较弱

---

## F05 — Dividend / Shareholder Yield

```text
Dividend Yield
+
Buyback Yield
```

- Popularity: ⭐⭐⭐
- Evidence: E2
- Priority: P2

---

## F06 — Quality Value

```text
Value Rank + Quality Rank
```

避免纯低估值价值陷阱。

- Popularity: ⭐⭐⭐
- Evidence: E2
- Priority: P2

---

## F07 — Quality Momentum

特别适合未来的“老登股票 / Quality Basket”。

```text
Quality Screen
+
Momentum Ranking
```

- Popularity: ⭐⭐
- Evidence: E2
- Priority: P1 for Old-Money Basket

---

# 11. Family MAC — Macro / Rates / Regime

宏观策略最容易产生数据修订和发布时间问题。

必须使用 Point-in-Time 数据。

---

## MAC01 — Yield Curve Regime

例如：

```text
10Y - 2Y
10Y - 3M
```

作为风险环境变量。

- Popularity: ⭐⭐⭐
- Evidence: E2
- Priority: P2
- Warning: 预测经济 ≠ 精确股票择时

---

## MAC02 — Inflation Regime

```text
Inflation Rising/Falling
```

对：

```text
Stocks
Bonds
Gold
Commodities
```

做资产配置。

- Popularity: ⭐⭐⭐
- Evidence: E2
- Priority: P2

---

## MAC03 — Rate Trend

```text
Policy Rate / 10Y Yield trend
```

作为 equity duration / bond allocation signal。

- Popularity: ⭐⭐
- Evidence: E1-E2
- Priority: P2

---

## MAC04 — PMI / Growth Regime

```text
PMI > 50
PMI rising/falling
```

- Popularity: ⭐⭐⭐
- Evidence: E1-E2
- Priority: P3
- Critical: release lag and revision

---

## MAC05 — Liquidity / Financial Conditions

组合：

```text
Credit Spread
Dollar
Rates
Liquidity
```

- Popularity: ⭐⭐
- Evidence: E1-E2
- Priority: P3
- Complexity: high

---

# 12. Family CARRY — Carry / Income

## CY01 — Bond Carry / Roll-Down

根据收益率曲线持有具有较高 carry/roll 的债券。

- Popularity: ⭐⭐
- Evidence: E2-E3
- Priority: P3

---

## CY02 — FX Carry

```text
Long high-rate currency
Short low-rate currency
```

- Popularity: ⭐⭐⭐
- Evidence: E3
- Priority: P3
- Tail Risk: high

---

## CY03 — Commodity Futures Carry

根据期货曲线：

```text
Backwardation / Contango
```

进行配置。

- Popularity: ⭐⭐
- Evidence: E2-E3
- Priority: P3
- Data complexity: high

---

# 13. Family C — Composite Strategies

## C01 — Valuation + Trend

推荐研究。

```text
Valuation determines amount
Trend determines risk multiplier
```

例如：

```text
Amount =
Base
× ValuationFactor
× TrendFactor
```

- Popularity: ⭐⭐
- Evidence: E1-E2
- Priority: CORE-Research

必须做：

```text
Valuation only
Trend only
Combined
```

---

## C02 — Trend + Momentum + Volatility

```text
Trend → direction
Momentum → ranking
Volatility → position size
```

- Popularity: ⭐⭐
- Evidence: E2
- Priority: CORE-Research

---

## C03 — Valuation + Momentum

解决：

```text
便宜但持续下跌
vs
贵但趋势强
```

的冲突。

- Popularity: ⭐⭐
- Evidence: E2
- Priority: P1

---

## C04 — Multi-Signal Score

例如：

```text
Valuation   [-2,+2]
Trend       [-2,+2]
Momentum    [-2,+2]
Risk        [-2,+2]

Total:
[-8,+8]
```

映射仓位：

```text
<= -4 → 25%
-3~0  → 50%
1~3   → 75%
>=4   → 100%
```

- Popularity: ⭐⭐⭐ in practitioner systems
- Evidence: depends on components
- Priority: P1
- Critical Risk: score weights are easy to overfit

---

## C05 — Regime-Switching Strategy

例如：

```text
Trending regime → Trend strategy
Range regime    → Mean-reversion strategy
```

- Popularity: ⭐⭐
- Evidence: E1-E2
- Priority: P2
- Risk: regime classifier itself can overfit

---

## C06 — Ensemble of Strategies

组合：

```text
SMA Trend
TSMOM
Breakout
Value
```

输出平均仓位。

- Popularity: ⭐⭐
- Evidence: E1-E2
- Priority: P2
- Benefit: reduce model risk
- Risk: false diversification among correlated signals

---

# 14. Family H — High-Popularity Technical Heuristics

这类策略非常适合本项目的一个特殊使命：

> 把“网上常见说法”变成可以证伪的统计假设。

不要因为它们 Popularity 高就认为 Evidence 高。

---

## H01 — MACD Golden Cross

```text
DIF crosses above DEA
```

- Popularity: ⭐⭐⭐
- Evidence: E1
- Priority: P2

---

## H02 — MACD Zero-Line Cross

```text
DIF crosses above 0
```

- Popularity: ⭐⭐⭐
- Evidence: E1
- Priority: P2

---

## H03 — MACD Bearish Divergence

必须正式定义 Pivot。

```text
Price High2 > High1
AND
MACD High2 < MACD High1
```

- Popularity: ⭐⭐⭐
- Evidence: E0-E1
- Priority: P1 as falsification project
- Main Goal: 验证“顶背离后都没行情”等市场说法

---

## H04 — RSI Divergence

同理。

- Popularity: ⭐⭐⭐
- Evidence: E0-E1
- Priority: P2

---

## H05 — Volume Breakout Confirmation

```text
Price breakout
AND
Volume / SMA20(volume) > k
```

- Popularity: ⭐⭐⭐
- Evidence: E1
- Priority: P2

---

## H06 — MA Bull Alignment

对应 T05 的离散版本。

```text
MA5 > MA10 > MA20 > MA30
```

- Popularity: ⭐⭐⭐
- Evidence: E1
- Priority: P1

---

## H07 — Death Cross Warning

```text
SMA50 crosses below SMA200
```

- Popularity: ⭐⭐⭐
- Evidence: E1
- Priority: P2

---

## H08 — New High / New Low Breadth

```text
52-week highs minus lows
```

作为市场内部强度。

- Popularity: ⭐⭐
- Evidence: E1
- Priority: P2

---

# 15. 初期 Asset × Strategy Compatibility Matrix

Legend：

```text
✓ 适合
△ 可研究但需注意
— 不适用
```

| Strategy | Nasdaq100 | S&P500 | Dow | HS300 | 茅台 | Gold | Treasury | Old-Money Basket |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Buy & Hold | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Fixed DCA | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| PE DCA | ✓ | ✓ | △ | ✓ | ✓ | — | — | ✓ |
| PB DCA | △ | △ | △ | ✓ | △ | — | — | △ |
| SMA200 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Multi-MA | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| TSMOM | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Relative Momentum | ✓ | ✓ | ✓ | ✓ | — | ✓ | ✓ | △ |
| Dual Momentum | ✓ | ✓ | ✓ | ✓ | — | ✓ | ✓ | △ |
| Breakout | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| RSI Mean Reversion | ✓ | ✓ | ✓ | ✓ | ✓ | △ | △ | ✓ |
| Vol Target | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Risk Parity | — | — | — | — | — | — | — | ✓* |
| Macro Regime | ✓ | ✓ | ✓ | ✓ | △ | ✓ | ✓ | △ |

`Risk Parity` 是 Portfolio Strategy，需要多个资产共同输入，单资产列仅用于说明其组件可参与组合。

---

# 16. 推荐第一阶段 Asset Universe

建议 V0：

```text
US Growth:
NASDAQ-100

US Broad:
S&P 500

US Old Economy / Blue Chip:
Dow Jones

China Broad:
沪深300

China Single Stock:
贵州茅台

Commodity / Store of Value:
Gold

Defensive:
US Treasury
Cash / Risk-Free
```

---

# 17. “老登股票”正式化建议

不要让 `Old Money Stocks` 只是一个模糊标签。

建议建立：

```text
OLD_MONEY_US_V1
```

候选筛选原则：

```text
Large Cap
Long Operating History
Positive FCF
Stable Profitability
Dividend / Buyback
Moderate Leverage
Lower Business Model Uncertainty
```

可以构建：

```text
Equal Weight Basket
Market Cap Weight Basket
Quality Score Basket
```

然后研究：

```text
Buy & Hold
DCA
Trend
Quality Momentum
Valuation DCA
```

注意：

> 构建历史 Basket 必须使用 Point-in-Time 公司池，避免幸存者偏差。

---

# 18. 研究优先级地图

## Phase 0 — Benchmark Infrastructure

```text
B01 Buy & Hold
B02 Fixed DCA
A01 60/40
A03 Rebalance
```

---

## Phase 1 — 最重要

```text
V02 PE Percentile DCA
T02 SMA200
T05 Multi-MA
M01 Time-Series Momentum
M03 Relative Momentum
M04 Dual Momentum
BR01 Breakout
R01 Vol Target
```

---

## Phase 2 — 你目前特别感兴趣

```text
T08 Weekly Trend
T09/T10 MACD
H03 Weekly MACD Bearish Divergence
MR01 RSI
B05 Drawdown DCA
C01 Valuation + Trend
C04 Multi-Signal Score
```

---

## Phase 3 — 扩展

```text
Factors
Macro Regime
Risk Parity
Mean Reversion
Carry
Advanced Composite
```

---

# 19. Strategy Universe 数据表建议

未来不要只维护 Markdown。

同步生成：

```text
strategy_universe.yaml
```

每个策略记录：

```yaml
strategy_id:
name:
family:

popularity:
evidence:
priority:

description:

supported_assets:
supported_frequency:

required_data:

core_parameters:

benchmark:

known_risks:

status:
spec_path:
research_path:
latest_grade:
last_validated:
```

Markdown 是人类阅读层。

YAML/JSON 是 Agent 执行层。

---

# 20. Strategy Universe 页面建议

Dashboard 增加：

```text
Strategy Library
```

筛选：

```text
Family
Asset
Frequency
Evidence
Popularity
Priority
Grade
Status
```

每张 Strategy Card 显示：

```text
SMA200 Trend

Family       Trend
Popularity   ⭐⭐⭐
Evidence     E2-E3
Complexity   C1
Grade        A
Assets       6 validated
OOS          PASS
Cost         PASS

[Open Research]
[Run Backtest]
[Current Signal]
```

---

# 21. “热门”策略不等于重点配置策略

Universe 中推荐同时展示：

```text
Popularity
Evidence
Robustness
```

例如：

```text
Weekly MACD Divergence

Popularity: ⭐⭐⭐
Evidence:   E0-E1
Status:     Research Hypothesis
```

而：

```text
Time-Series Momentum

Popularity: ⭐⭐⭐
Evidence:   E3
Status:     Core Research
```

让系统主动抵抗：

> “大家都在说，所以应该有效。”

---

# 22. 未来新策略如何进入 Universe

Agent 收到新策略：

```text
Source
↓
STRATEGY_RESEARCH_PROTOCOL
↓
Candidate ID
↓
Add to Universe
↓
Research
↓
Grade
```

命名：

```text
<FAMILY>_<CONCEPT>_<VERSION>
```

例如：

```text
VAL_PEPCTL_DCA_V1
TREND_SMA200_V1
TECH_WMACD_DIV_V1
MOM_DUAL_V1
```

---

# 23. Research Queue 示例

建议初始 Queue：

```text
RQ-001
截图 PE 25/35 定投
vs
Fixed DCA
vs
Rolling PE Percentile DCA

RQ-002
SMA200
vs
SMA150–250 Robustness

RQ-003
MA5/10/20/30 多头排列
是否增加 SMA20/SMA200 以外的信息

RQ-004
Weekly MACD Bearish Divergence
后 4/12/26 周表现统计

RQ-005
12M TSMOM
vs
SMA200

RQ-006
Dual Momentum
NASDAQ / HS300 / Gold / Treasury

RQ-007
Vol Target
是否显著改善 Nasdaq Max DD / Sharpe

RQ-008
Valuation + Trend
是否优于两者单独策略
```

---

# 24. 第一阶段建议暂缓的策略

不是说无效，而是优先级低或数据复杂度高。

```text
High-Frequency Intraday
Options Gamma / Vol Arbitrage
Pairs Trading
Stat Arb
Machine Learning Black Box
Deep Reinforcement Learning Trading
Crypto Microstructure
Complex Macro Forecasting
```

理由：

> 当前项目的核心价值首先应该是把长期投资、定投、趋势、估值和跨资产配置研究做得可信，而不是快速扩大策略数量。

---

# 25. 核心研究问题

Strategy Universe 最终不是为了回答：

> 哪个策略收益最高？

而是形成：

```text
Which strategy
works for
which asset
under which regime
with which risk
and how robustly?
```

中文即：

> **什么策略，在什么资产上、什么市场环境下，以什么风险代价，表现出多稳定的历史规律？**

这应成为整个 Investment Strategy Lab 的核心研究问题。

---

# 26. Evidence Anchors

作为 Universe 的研究文献起点：

- Brock, Lakonishok & LeBaron (1992) — moving-average / trading-range-break technical rules.
- De Bondt & Thaler (1985) — long-horizon reversal / market overreaction.
- Fama & French (1992) — size and book-to-market cross-sectional return evidence.
- Jegadeesh & Titman (1993) — cross-sectional momentum.
- Moskowitz, Ooi & Pedersen (2012) — time-series momentum across asset classes.
- Faber — long moving-average tactical asset allocation.
- Moreira & Muir — volatility-managed portfolios.
- Cederburg et al. — caution on universal direct benefits of volatility management.
- Antonacci — dual momentum framework.

这些文献用于：

```text
Define research starting point
```

而不是：

```text
Assume future profitability
```
