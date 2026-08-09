# Investment Strategy Lab — 数据准确性与回测完整性守则

> **用途**：本文件作为 Investment Strategy Lab 中所有数据采集、指标计算、策略回测、策略比较、可视化与 Agent 自动研究任务的强制行为规范。  
> **目标**：优先保证结论可复现、数据可追溯、无未来函数、无隐含偏差，而不是追求“更漂亮”的历史收益曲线。  
> **原则**：**宁可输出“数据不足 / 无法验证”，也不得用未经确认的数据定义、代理数据或未来信息补全结论。**

---

## 0. Agent 总原则：先验证，再计算，再解释

任何策略分析必须遵循以下顺序：

1. **确认标的定义**
2. **确认数据源与数据口径**
3. **检查时间可用性（Point-in-Time）**
4. **检查复权、股息、成分股与公司行动**
5. **计算指标**
6. **生成策略信号**
7. **按明确的成交规则执行回测**
8. **计算收益与风险指标**
9. **执行数据一致性检查**
10. **最后才允许生成投资策略解释**

Agent 不得跳过第 1–4 步直接根据价格序列或第三方指标计算策略收益。

---

# 1. 数据源可信度与 Source of Truth

## 1.1 数据源分级

所有数据源按以下等级管理。

### Level A — Primary / 官方一手数据

包括但不限于：

- 交易所
- 指数公司
- 上市公司公告 / 财报
- SEC / CNINFO 等监管披露
- 央行 / 国家统计部门
- FRED 等官方宏观数据库
- 基金公司官方净值
- ETF 官方分红与拆并信息

用途：

- 关键字段最终校验
- Corporate Action 校验
- 指数规则、成分调整校验
- 财报发布日期校验
- 宏观指标发布日期校验

**关键结论出现冲突时，Level A 优先级最高。**

---

### Level B — Professional Data Provider

例如：

- Bloomberg
- Refinitiv
- Wind
- Choice
- Tushare Pro
- Polygon
- Tiingo
- Nasdaq Data Link

用途：

- 日常生产数据
- 历史行情
- 财务数据
- 指数估值
- 资产属性数据

---

### Level C — Public Aggregator / 免费聚合源

例如：

- Yahoo Finance
- Stooq
- AkShare 所聚合的公开数据
- 其他公开行情网站

用途：

- 原型
- 交叉验证
- Fallback

**不得在没有校验的情况下，将 Level C 作为长期回测唯一真相源。**

---

## 1.2 双源校验

核心数据至少应支持两个独立来源。

建议字段：

```text
symbol
date
source_primary
source_secondary
value_primary
value_secondary
difference_abs
difference_pct
validation_status
```

例如收盘价：

\[
difference\_pct =
\frac{|P_A-P_B|}{\max(|P_A|,\epsilon)}
\]

默认建议：

```text
difference_pct < 0.1% → PASS
0.1% – 0.5%          → WARNING
> 0.5%                → FAIL / MANUAL REVIEW
```

阈值必须允许按资产类型配置。

---

# 2. 标的身份必须明确：Ticker ≠ Asset

在进行任何回测前，必须明确“研究对象是什么”。

例如：

```text
NASDAQ-100 Index
QQQ ETF
NASDAQ Composite
NDX Total Return Index
```

是四个不同对象。

不能因为走势相近而混用。

必须记录：

```yaml
asset_id:
display_name:
asset_type:
ticker:
exchange:
currency:
price_return_or_total_return:
underlying_index:
data_source:
inception_date:
```

---

# 3. Price Index 与 Total Return Index 不得混淆

长期回测中最常见的误差之一：

```text
Price Return
```

只考虑价格变化。

而：

```text
Total Return
```

考虑：

- 股息
- 分红再投资
- 部分情况下的资本返还

例如比较：

```text
NASDAQ
S&P 500
沪深300
```

长期收益时，如果一个使用 Total Return、另一个使用 Price Index，比较结果无效。

Agent 必须显式标注：

```text
RETURN_TYPE = PRICE_RETURN
```

或

```text
RETURN_TYPE = TOTAL_RETURN
```

### 强制规则

如果无法获取 Total Return 数据，但用户要求长期投资回测：

Agent 必须提示：

> 当前结果未包含股息再投资，长期收益可能被系统性低估，不能与 Total Return 基准直接比较。

---

# 4. 复权：前复权、后复权、Adj Close

股票和 ETF 历史价格可能受到：

- 分红
- 拆股
- 合股
- 配股
- 送股
- 特别分红
- Spin-off

影响。

必须区分：

```text
Raw Close
Adjusted Close
Forward Adjusted
Backward Adjusted
```

## 4.1 原则

### 技术指标

若目标是模拟当时市场参与者看到的价格结构，应确保复权方案不会引入未来信息。

### 收益计算

优先使用：

```text
Total Return
```

或经验证的：

```text
Adjusted Close
```

### 可视化

必须注明：

```text
Adjusted
```

或：

```text
Unadjusted
```

不得让用户误以为是原始交易价格。

---

# 5. Look-Ahead Bias：禁止未来函数

这是最高等级错误之一。

定义：

> 在时间 \(t\) 的策略决策中，使用了当时尚未公开的信息。

---

## 5.1 财报数据

例如：

```text
2025 Q1 EPS
```

虽然属于 Q1，但可能到：

```text
2025-04-30
```

才公布。

策略不能在：

```text
2025-03-31
```

使用该 EPS。

必须保存至少：

```text
period_end
report_date
publication_timestamp
effective_timestamp
```

回测中只能使用：

```text
publication_timestamp <= signal_timestamp
```

的数据。

---

## 5.2 PE / PB / ROE 等估值指标

禁止直接把“当前数据库回填后的历史 PE”默认视为 Point-in-Time 数据。

必须确认：

- 使用哪个 EPS
- EPS 当时是否已发布
- 指数成分是否按当时成分计算
- 历史数据是否被供应商回溯修订

---

## 5.3 宏观数据

CPI、GDP、PMI、就业等数据存在：

```text
观察期
发布日期
修订值
最终值
```

策略必须使用：

> 当时第一次能够获得的 vintage 数据。

不能使用后来修订后的最终值回测历史决策。

---

# 6. Survivorship Bias：幸存者偏差

错误案例：

> 用 2026 年 Nasdaq-100 成分股名单，回测 2005–2026。

这样会天然排除：

- 破产公司
- 被收购公司
- 被指数剔除公司
- 长期表现差的公司

结果通常会显著高估策略表现。

---

## 6.1 指数级回测

优先使用：

```text
Historical Index Level
```

或：

```text
Historical Total Return Index
```

而不是自己用当前成分股反推历史指数。

---

## 6.2 个股组合回测

如果研究历史选股策略，必须使用：

```text
Point-in-Time Constituents
```

即每个历史日期实际存在的股票池。

至少需要：

```text
effective_start
effective_end
ticker
company_id
index_membership
```

---

# 7. Delisting Bias：退市股票不能消失

如果研究股票池策略：

被退市股票不能简单从历史数据集中删除。

否则：

> 所有失败样本自动消失。

必须处理：

- 破产
- 退市
- 收购
- 私有化
- 换代码
- 合并

如无法获得 Delisting Return，应明确标记结果可能存在乐观偏差。

---

# 8. 指数成分调整与 Rebalancing

指数并不是静态股票组合。

必须记录：

```text
announcement_date
effective_date
rebalance_date
constituent_add
constituent_remove
weight_change
```

Agent 不得使用：

> 调整后的名单在 announcement_date 之前进行交易。

---

# 9. PE / PB 等估值指标定义必须完全明确

截图中类似：

```text
NASDAQ PE = 30.27
```

本身不足以用于研究。

至少要回答：

## PE 类型

```text
Trailing PE
Forward PE
Static PE
TTM PE
Dynamic PE
```

## 指数 PE 聚合方法

可能包括：

```text
Aggregate Earnings Method
Weighted Average PE
Median PE
Harmonic Mean
Ex-negative Earnings
Include-negative Earnings
```

不同方法可能得到明显不同结果。

---

## 9.1 估值策略强制 Metadata

```yaml
valuation_metric: PE_TTM
aggregation_method:
negative_earnings_handling:
source:
publication_frequency:
point_in_time: true/false
currency:
index_constituent_method:
```

没有这些 Metadata，不允许把两个数据源的 PE 做直接比较。

---

# 10. 历史百分位：禁止全样本泄漏

策略常用：

```text
当前 PE 历史百分位
```

错误算法：

```python
percentile = rank(PE_t, all_PE_2000_2026)
```

这是未来泄漏。

因为 2010 年的投资者不知道 2011–2026 的 PE。

---

## 正确算法

Expanding percentile：

```text
PE Percentile at t
=
Percentile(
    PE history available before or at t
)
```

或 Rolling percentile：

```text
过去 5 年
过去 10 年
过去 20 年
```

必须明确窗口。

例如：

```yaml
percentile_mode: rolling
lookback_years: 10
min_history_years: 5
```

---

# 11. 均线计算的时间边界

例如：

\[
MA_{20,t}
\]

必须明确是否包含当日 Close。

如果信号在：

```text
2026-08-07 close
```

计算：

```text
Close > MA20
```

则这个信号最早只能在：

```text
2026-08-07 收盘后
```

获得。

实际成交应默认：

```text
Next Trading Day Open
```

而不能用：

```text
Same Day Close
```

否则存在执行层面的未来函数。

---

# 12. Signal Time 与 Execution Time 必须分离

每笔策略动作必须记录：

```text
signal_timestamp
execution_timestamp
execution_price_type
```

推荐默认：

```text
Daily strategy:
signal = Day T Close
execution = Day T+1 Open
```

周线：

```text
signal = Friday Close
execution = Next Trading Day Open
```

如果使用其他规则，必须明确写出。

---

# 13. Weekly / Monthly Resampling 防止时间错位

例如周线：

```python
df.resample("W").last()
```

并不一定等价于交易周最后一个交易日。

节假日、时区、交易所日历都可能产生偏差。

必须使用交易日历。

推荐记录：

```text
exchange_calendar
timezone
session_open
session_close
holiday_calendar
```

---

# 14. Time Zone

跨市场策略尤其容易产生隐含未来数据。

例如：

```text
A股收盘：15:00 CST
美股开盘：09:30 ET
```

当天日期相同并不意味着数据在同一时刻可获得。

跨市场信号必须统一到：

```text
UTC timestamp
```

并根据真实发布时间排序。

Agent 不得简单按 `YYYY-MM-DD` join 跨市场数据。

---

# 15. Trading Calendar

不得默认：

```text
252 trading days
```

在任何环境都绝对成立。

不同市场有：

- 节假日差异
- 临时休市
- 半日交易
- 市场制度变化

年化计算可使用约定参数，但必须记录：

```yaml
annualization_factor: 252
```

并与实际交易频率保持一致。

---

# 16. Missing Data：禁止静默填充

缺失数据是另一个高风险源。

默认禁止：

```python
df.fillna(method="ffill")
```

无条件填充全部字段。

不同字段处理不同。

例如：

### 价格

非交易日缺失 ≠ 数据缺失。

### 财务数据

季度财务数据可以在公布后保持有效，属于合理 Step Function。

### PE

需要确认数据供应商频率。

### 成交量

不能随意 forward fill。

---

## 16.1 每个字段应定义 Fill Policy

```yaml
close:
  fill: none

pe_ttm:
  fill: forward
  max_age_days: 120

macro_cpi:
  fill: forward
  valid_after_release: true
```

---

# 17. Stale Data Detection

例如 API 异常导致：

```text
Price = 100
Price = 100
Price = 100
Price = 100
```

Agent 必须检查：

- 连续相同值
- 长时间无更新
- 最新日期落后
- 极端跳变
- Volume = 0
- OHLC 逻辑错误

基本规则：

```text
low <= open <= high
low <= close <= high
high >= low
volume >= 0
```

异常必须进入 Data Quality Report。

---

# 18. Outlier 不得自动删除

价格暴涨暴跌可能是真实事件，例如：

- 股灾
- 拆股
- 重大并购
- 极端行情

Agent 不得因为 Z-score 太高而自动删除。

正确流程：

```text
Detect
→ Flag
→ Check Corporate Action
→ Cross Source Verify
→ Decide
```

---

# 19. Corporate Action

必须识别至少：

```text
cash dividend
stock split
reverse split
rights issue
spin-off
merger
special dividend
ticker change
```

否则会制造：

- 假暴跌
- 假暴涨
- 错误均线
- 错误波动率
- 错误回撤

---

# 20. ETF ≠ Index

例如：

```text
QQQ
```

不是严格等于：

```text
NASDAQ-100 Index
```

原因包括：

- 管理费
- Tracking Error
- 分红处理
- 基金现金仓位
- 再平衡执行
- 税务
- ETF 成立时间限制

如果用 QQQ 代理历史 Nasdaq-100：

必须明确：

```text
Proxy = QQQ ETF
```

而不是称为指数原始表现。

---

# 21. 黄金数据必须区分资产形式

“黄金”可能是：

```text
Spot Gold (XAU/USD)
Gold Futures
Continuous Futures
GLD ETF
Physical Gold
人民币黄金
上海金
```

这些不是一个标的。

特别是期货需要处理：

```text
Contract Roll
Backwardation
Contango
Roll Yield
```

不能简单拼接主力合约价格。

---

# 22. 债券数据必须区分 Yield 与 Total Return

错误：

> 直接用 10Y Treasury Yield 当作债券收益率序列。

Yield 是收益率报价，不是债券资产回报。

债券策略应优先使用：

```text
Treasury Total Return Index
```

或真实可交易 ETF。

---

# 23. Currency / FX Effect

不同币种资产比较必须明确：

```text
Local Currency Return
```

还是：

```text
Base Currency Return
```

例如中国投资者比较：

```text
NASDAQ vs 沪深300
```

若基准货币是 CNY，则：

NASDAQ CNY return 应包括 USD/CNY 变化。

必须记录：

```yaml
base_currency: CNY
fx_hedged: false
```

---

# 24. Benchmark 必须同口径

策略 Benchmark 需要满足：

- 同资产
- 同币种
- 同起止日期
- 同 Return Type
- 同资金流
- 同交易成本假设

例如定投策略不能只和一次性 Buy & Hold 的 CAGR 比较。

定投优先比较：

```text
XIRR
Ending Wealth
Total Capital Invested
Money Weighted Return
```

---

# 25. 定投回测的现金流问题

普通 CAGR 不适合描述多次现金流。

必须至少提供：

```text
Total Contributions
Ending Value
Profit
XIRR
Time Weighted Return
```

对定投策略比较：

```text
相同累计投入
```

是最基本前提。

如果不同策略因为“少买”导致累计投入不同：

必须：

1. 明确剩余现金如何处理；
2. 或强制总预算一致；
3. 或同时报告现金余额。

---

# 26. 未投资现金不是 0

如果策略持有现金，应指定现金收益：

```text
0%
Risk Free Rate
Money Market Rate
```

长期回测中默认现金收益为 0 会改变结果。

建议：

```yaml
cash_return:
  source: risk_free_rate
```

---

# 27. 交易成本

至少考虑：

```text
commission
slippage
bid_ask spread
stamp duty
management fee
```

具体取决于资产类型。

高频策略特别敏感。

任何策略应同时报告：

```text
Gross Return
Net Return
```

---

# 28. Slippage

不得默认所有成交：

```text
exactly at Open
```

或：

```text
exactly at Close
```

可以支持：

```yaml
slippage_bps: 5
```

并做敏感性测试，例如：

```text
0 bps
5 bps
10 bps
25 bps
```

若策略只在 0 bps 下有效，应降低可信度。

---

# 29. Liquidity 与 Capacity

对指数/黄金通常影响较小。

但个股策略应检查：

```text
Average Daily Volume
Position / ADV
Turnover
```

不得假设任意规模均可无冲击成交。

---

# 30. 税费

不同投资者、市场、账户差异很大。

第一版可不建模复杂税务，但必须明确：

```text
Pre-Tax Backtest
```

不得把税前结果描述为真实到手收益。

---

# 31. 参数过拟合

禁止只展示：

> 历史表现最好的一个参数。

例如：

```text
MA = 178
```

比 MA200 好。

必须测试邻近参数。

例如：

```text
100
120
140
160
180
200
220
240
```

判断：

```text
Parameter Stability
```

---

# 32. Multiple Testing / Data Snooping

如果测试：

```text
1000 个策略
```

最后挑收益最高的一个，

即使完全随机，也可能出现非常漂亮的结果。

Agent 必须记录：

```text
number_of_strategies_tested
number_of_parameter_combinations
selection_rule
```

策略筛选结果需考虑 Multiple Testing。

---

# 33. In-Sample / Out-of-Sample

推荐基本划分：

```text
Train / Research Period
Validation Period
Out-of-Sample Period
```

例如：

```text
2000–2016  Research
2017–2021  Validation
2022–2026  OOS
```

最终策略评价必须重点看 OOS。

---

# 34. Walk-Forward Validation

对于依赖参数估计的策略，推荐：

```text
Historical Window
        ↓
Fit Parameter
        ↓
Next Period Test
        ↓
Roll Forward
```

避免一次性使用完整历史数据调参。

---

# 35. Regime Robustness

策略不能只看全周期平均。

至少按市场环境拆分：

```text
Bull Market
Bear Market
Sideways
High Inflation
Low Inflation
High Rate
Low Rate
High Volatility
Low Volatility
```

检查是否只依赖某一种特殊时期。

---

# 36. Cross-Asset Validation

策略逻辑如果宣称普适，应在多个资产验证。

例如 MA Trend：

```text
NASDAQ
S&P 500
HS300
Gold
Treasury
```

如果只在单一资产 + 单一参数有效：

可信度下降。

---

# 37. Start-Date Bias

定投策略对起始日期可能非常敏感。

例如：

```text
每月 1 日定投
```

不能只测试一种起始日期。

建议进行：

```text
Rolling Start Date Test
```

例如每个月都作为一个新的起点。

---

# 38. End-Date Bias

同样，回测恰好结束在牛市顶点可能显著美化结果。

建议：

```text
Rolling Window
```

例如：

```text
5Y
10Y
15Y
20Y
```

滚动回测。

---

# 39. Strategy Definition 必须可执行、无模糊语义

禁止：

> 均线趋势走好时买入。

必须定义为：

```text
Close > MA20
AND
MA20 > MA60
AND
Slope(MA20, 5d) > 0
```

所有自然语言策略必须转换为：

```text
Boolean Rule
```

或：

```text
Numeric Score
```

才能进入正式回测。

---

# 40. 指标定义不可凭名字猜测

例如：

```text
MACD
RSI
ATR
Momentum
Volatility
Drawdown
```

都必须保存完整参数。

例如：

```yaml
MACD:
  fast: 12
  slow: 26
  signal: 9
  price: close

RSI:
  period: 14
  smoothing: Wilder
```

否则不同软件可能结果不同。

---

# 41. MA 的定义也要明确

例如：

```text
MA
```

可能是：

```text
SMA
EMA
WMA
RMA
```

必须明确。

默认命名建议：

```text
SMA20
EMA20
```

而不是只写：

```text
MA20
```

---

# 42. 周线 MACD / RSI 的计算方式

不能：

> 先计算日线 MACD，再抽周五数值，

来替代：

> 在周线 OHLC 上重新计算 MACD。

这两个定义不同。

Agent 必须明确使用：

```text
Daily Indicator
```

还是：

```text
Weekly Resampled Indicator
```

---

# 43. 数据修订与 Reproducibility

每次正式回测必须记录：

```text
data_version
download_timestamp
source
code_commit
strategy_version
config_hash
```

确保未来可以重现：

> 为什么 2026-08-07 的结果是这个数。

---

# 44. Cache 与 Raw Data 不可覆盖

建议：

```text
data/raw/
```

保存原始下载数据，不修改。

清洗结果：

```text
data/processed/
```

指标：

```text
data/features/
```

回测：

```text
data/backtest/
```

禁止直接覆盖 raw data。

---

# 45. 数据变更必须可追踪

如果供应商更新历史值：

需要检测：

```text
Historical Revision
```

并记录：

```text
old_value
new_value
changed_at
source
```

尤其重要：

- 财务数据
- 宏观数据
- 指数估值
- Corporate Action

---

# 46. Data Quality Score

每个数据集建议生成质量评分：

```text
Completeness
Freshness
Cross-source consistency
Point-in-time validity
Corporate-action integrity
Outlier status
```

输出例如：

```text
A — Production Ready
B — Minor Warnings
C — Research Only
D — Unreliable
```

---

# 47. Agent 的错误等级

## P0 — Critical

出现后必须停止回测。

包括：

- Look-ahead Bias
- 数据错位
- 标的身份错误
- Price / Total Return 混淆
- 时间穿越
- Point-in-Time 财务数据错误
- 严重 Corporate Action 错误

输出：

```text
BACKTEST INVALID
```

---

## P1 — High

可能显著改变结果。

例如：

- Survivorship Bias
- 缺失 Delisting
- 指数成分历史错误
- 现金收益忽略
- FX 口径错误

输出：

```text
RESULT NOT RELIABLE
```

---

## P2 — Medium

例如：

- Slippage 未建模
- 管理费未建模
- 轻微缺失值
- 数据源轻微差异

输出：

```text
RESULT WITH CAVEATS
```

---

## P3 — Low

例如：

- 可视化误差
- Metadata 不完整
- 非关键字段异常

---

# 48. Agent 在正式运行策略前的 Mandatory Checklist

任何正式策略必须通过：

```text
[ ] Asset identity confirmed
[ ] Currency confirmed
[ ] Price vs Total Return confirmed
[ ] Adjustment method confirmed
[ ] Data source recorded
[ ] Historical availability checked
[ ] Point-in-time validation passed
[ ] Look-ahead bias test passed
[ ] Survivorship bias assessed
[ ] Delisting bias assessed
[ ] Corporate actions validated
[ ] Trading calendar validated
[ ] Timezone validated
[ ] Missing-value policy applied
[ ] Outlier validation completed
[ ] Signal timestamp defined
[ ] Execution timestamp defined
[ ] Transaction cost configured
[ ] Slippage configured
[ ] Cash return configured
[ ] Benchmark matched
[ ] Strategy parameters versioned
```

任何 P0 项目失败：

```text
不得运行正式回测
```

---

# 49. Backtest Result 必须附带的 Metadata

每次输出策略表现时必须同时提供：

```yaml
asset:
asset_type:
currency:

start_date:
end_date:

data_source:
data_version:

return_type:
adjustment_method:

strategy:
strategy_version:

signal_frequency:
execution_rule:

commission:
slippage:
cash_rate:

benchmark:

lookahead_test:
survivorship_status:
data_quality_score:
```

---

# 50. Agent 不允许做的事情

Agent **禁止**：

1. 因为数据缺失而静默创造数据；
2. 未说明情况下替换资产；
3. 使用未来财报；
4. 使用完整样本计算历史百分位；
5. 使用当前成分股回测历史股票池；
6. 把 ETF 当成指数而不说明；
7. 把 Price Index 与 Total Return 直接比较；
8. 忽略分红后声称“长期真实回报”；
9. 忽略现金余额；
10. 根据最佳回测结果反推参数并称其有效；
11. 只展示最佳参数；
12. 删除不利异常值；
13. 只展示收益、不展示回撤；
14. 使用未经定义的 PE/PB 指标；
15. 在无法验证数据时编造精确数字。

---

# 51. Agent 遇到不确定性时的默认行为

若出现不确定性：

```text
STOP
↓
Identify uncertainty
↓
Search metadata / second source
↓
Cross-check
↓
Assign confidence
↓
Continue or reject
```

不得：

```text
Guess
↓
Continue backtest
```

---

# 52. Confidence 标签

所有重要结论建议加入：

### HIGH

```text
官方 / 专业数据源
+
定义清楚
+
双源验证
+
Point-in-Time
+
无关键偏差
```

### MEDIUM

```text
数据基本可信
但存在代理变量 / 轻微口径问题
```

### LOW

```text
单一聚合源
或存在历史数据定义不确定
```

### INVALID

```text
发现 P0 数据问题
```

---

# 53. 推荐自动化测试

## Price Test

```text
OHLC consistency
duplicate dates
missing trading days
extreme returns
zero prices
```

## Corporate Action Test

```text
price jump
vs
split/dividend event
```

## Indicator Test

与第二套实现交叉验证：

```text
SMA
EMA
RSI
MACD
ATR
```

## Backtest Test

使用简单可手算样本验证：

```text
Buy & Hold
DCA
MA crossover
```

## Look-Ahead Test

人为将未来数据延迟：

```text
signal should change accordingly
```

---

# 54. 数据与策略分层

必须保持：

```text
Raw Data
   ↓
Normalized Data
   ↓
Feature / Indicator
   ↓
Signal
   ↓
Position
   ↓
Execution
   ↓
Portfolio
   ↓
Metrics
```

禁止：

```text
Strategy
   ↓
直接调用某网站 API
```

策略层不得知道数据来自 Yahoo、Wind 还是其他供应商。

---

# 55. 推荐核心数据结构

```text
timestamp
asset_id

open
high
low
close
adj_close
volume

total_return_index

pe_ttm
pb
dividend_yield

source
source_timestamp
effective_timestamp

quality_flag
```

---

# 56. 每次新增策略的研究标准

一个新策略进入正式策略库前必须完成：

## Step 1 — Strategy Definition

数学化策略。

## Step 2 — Economic Rationale

说明为什么理论上可能有效。

## Step 3 — Data Audit

检查需要的数据是否可靠。

## Step 4 — Baseline Backtest

与 Buy & Hold / DCA 比较。

## Step 5 — Parameter Robustness

参数扫描。

## Step 6 — Rolling Window

检查不同时间区间。

## Step 7 — Cross Asset

多个资产验证。

## Step 8 — Out-of-Sample

真正留出历史数据。

## Step 9 — Cost Sensitivity

加入成本。

## Step 10 — Strategy Grade

最终评级。

---

# 57. Strategy Grade

建议：

### S

```text
经济逻辑明确
跨资产有效
跨周期稳定
OOS 有效
参数稳健
成本后仍有效
```

### A

```text
总体可靠
存在部分 regime dependency
```

### B

```text
有一定效果
但稳定性一般
```

### C

```text
高度依赖参数 / 时间窗口
```

### D

```text
无法区别于数据挖掘
```

### INVALID

```text
回测存在数据偏差
```

---

# 58. Dashboard 必须展示的数据质量信息

Dashboard 不应只显示：

```text
CAGR
Sharpe
Max Drawdown
```

还应显示：

```text
Data Quality: A
Data Updated: YYYY-MM-DD
Source: ...
Return Type: Total Return
Backtest Integrity: PASS
```

如果存在问题：

```text
⚠ Valuation data is not Point-in-Time
⚠ Dividend reinvestment unavailable
```

应在页面显著显示，而不是藏在脚注。

---

# 59. 回测结果的默认解释顺序

Agent 必须按以下顺序解释策略：

1. 数据是否可信；
2. 策略定义；
3. 是否存在 Bias；
4. 收益；
5. 风险；
6. Benchmark；
7. 参数稳定性；
8. 不同时期；
9. 不同资产；
10. 最终结论。

不得以：

> CAGR 最高

作为策略“最好”的唯一依据。

---

# 60. 最终原则

Investment Strategy Lab 的目标不是寻找：

> **历史收益最高的策略。**

而是寻找：

> **在严格数据口径、无未来函数、多个市场环境、多个参数与样本外测试下仍然表现稳定的策略。**

因此，Agent 的优先级必须始终是：

```text
Data Integrity
    >
Backtest Integrity
    >
Robustness
    >
Risk
    >
Return
```

而不是：

```text
Return
    >
Everything Else
```

---

# Appendix A — Agent 启动 Prompt 建议

可将以下内容放入未来 Agent 的系统级行为指令：

> You are operating an investment strategy research system.  
> Never optimize for attractive backtest results at the expense of data integrity.  
> Before calculating any strategy performance, verify asset identity, return type, adjustment methodology, point-in-time availability, corporate actions, trading calendar, signal timing and execution timing.  
> Explicitly detect look-ahead bias, survivorship bias, delisting bias, historical percentile leakage, cross-market timestamp leakage and inconsistent benchmark definitions.  
> If any critical integrity check fails, mark the backtest INVALID and do not provide a quantitative strategy conclusion.  
> Never invent missing data or silently substitute proxy assets.  
> Preserve raw data, record source and data version, and ensure every result is reproducible.  
> Prefer a robust strategy across parameters, assets, regimes and out-of-sample periods over the single historically optimal parameter.

---

# Appendix B — 推荐文件名

```text
docs/
└── BACKTEST_DATA_INTEGRITY.md
```

建议将该文件视为：

```text
Agent Constitution / Guardrail
```

其优先级高于单个 Strategy 文件中的实现细节。
