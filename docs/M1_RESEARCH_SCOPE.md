# M1 可信研究范围：QQQ 与 DIA

> 状态：Approved baseline
> 冻结日期：2026-08-10
> 运行目标：Apple Silicon M1，本地单用户，单批最长约 24 小时

## 1. 资产身份

| Asset ID | Ticker | 类型 | 跟踪对象 | 币种 | 用途 |
|---|---|---|---|---|---|
| `US_ETF_QQQ` | QQQ | ETF | Nasdaq-100 Index | USD | 美国大型非金融成长股代理 |
| `US_ETF_DIA` | DIA | ETF | Dow Jones Industrial Average | USD | 美国 30 只蓝筹股代理 |
| `USD_CASH` | — | Cash | USD cash/risk-free proxy | USD | long/flat 策略防御仓位 |

QQQ 不是 Nasdaq Composite，也不是 Nasdaq-100 原始指数。DIA 也不是 DJIA 指数本身。研究结果统一称为 ETF 可投资代理结果，并计入基金费用、跟踪误差和成立日期限制。

官方身份锚点：

- QQQ：https://www.invesco.com/us/financial-products/etfs/product-detail?productId=QQQ&ticker=QQQ
- DIA：https://www.ssga.com/us/en/individual/etfs/state-street-spdr-dow-jones-industrial-average-etf-trust-dia

## 2. 数据获取与双源验证

### 2.1 数据源角色

| 角色 | 接口 | 用途 |
|---|---|---|
| Primary | Tushare Pro `us_daily_adj` | 美股复权日线生产候选源 |
| Secondary | AkShare `stock_us_daily` / `stock_us_hist` | 独立聚合源交叉验证 |
| Official anchor | Invesco / State Street | 标的身份、基金行动和关键冲突人工校验 |
| Cash | FRED DFF/EFFR（M2） | 未投资现金收益；M1 fixture 可显式使用 0% |

Tushare 官方文档说明 `us_daily_adj` 的复权因子可能因除权事件刷新。因此每次抓取必须保存不可变 raw snapshot 和内容哈希，不能只保存“最新复权历史”。AkShare 由公开网站聚合，作为验证源而不是无条件事实源。

2026-08-10 的本机接口探针结果：base conda 中 AkShare 1.18.83 可获取 QQQ 与 DIA 的 raw/qfq 日线，最新 session 为 2026-08-07；当前返回的 QQQ 起点为 2001-01-02、DIA 起点为 2005-01-03。该起点明显不是基金身份意义上的成立日，只代表当前接口可见覆盖范围。Tushare 1.4.29 已安装，但当前进程未配置 token，尚未进行第二源实数对账。

### 2.2 校验口径

不同供应商的前复权基准可能不同，不能直接要求整个 adjusted price level 相等：

1. raw OHLC 在相同交易日比较绝对值和相对误差；
2. adjusted series 比较单期收益、拆分/分红附近累计收益和方向；
3. volume 先确认单位再比较；
4. 日期先映射到交易 session，禁止按字符串盲目 join；
5. 任一来源缺失、历史发生修订或误差越界都进入 `DataQualityReport`；
6. 冲突不静默平均，也不自动偏向更有利于策略的来源。

初始阈值：

```text
raw close difference <= 0.10%       PASS
0.10% < difference <= 0.50%         WARNING
difference > 0.50%                  FAIL / manual review
adjusted daily return difference <= 10 bps  PASS
```

阈值将在首批真实 snapshot 后根据 corporate action 和供应商口径校准，修改需要新 policy version。

### 2.3 频率生成

生产研究只下载日线，由本地交易日历生成周线和月线：

- Weekly：该交易周最后一个真实 session 的 OHLCV；
- Monthly：该自然月最后一个真实 session 的 OHLCV；
- 指标在重采样后的 OHLC 上重新计算；
- 不允许计算日线指标后只抽取周末/月末值冒充周/月指标；
- 周/月 close 产生的信号均在下一真实交易 session open 执行。

## 3. 强制 Benchmark

每个策略必须与以下基准比较：

1. QQQ Buy & Hold；
2. DIA Buy & Hold；
3. 对应 ETF 100% exposure；
4. USD cash；
5. 对轮动策略增加 QQQ/DIA 50/50 月度再平衡。

同时报告 gross/net return、exposure 和 cash return。M1 若使用 0% cash，必须显著标注；M2 接入滞后一日可用的 FRED cash rate 后重跑。

## 4. 推荐的五个首批策略

这些是“研究候选”，不是投资建议，也不预设其有效。

### S1 — Daily RSI2 Pullback with Long-Term Trend Filter

```text
Frequency: daily
Entry: Wilder RSI(2) < 10 AND Close > SMA(200)
Exit: Wilder RSI(2) > 70
Position: 100% target ETF or cash
Decision: Day T close
Execution: Day T+1 open
```

价值：代表短周期均值回归，与趋势策略形成互补；QQQ/DIA 流动性较高，便于隔离信号本身。主要风险是阈值经验性强、对开盘跳空和成本敏感。

研究邻域：RSI entry `[5, 10, 15, 20]`、exit `[50, 60, 70, 80]`、trend window `[150, 200, 250]`。先冻结默认参数，再做邻域，不在 OOS 选择最佳点。

### S2 — Daily Donchian Breakout

```text
Frequency: daily
Entry: Close_t > max(High, prior 55 sessions)
Exit: Close_t < min(Low, prior 20 sessions)
Position: 100% target ETF or cash
Decision: Day T close
Execution: Day T+1 open
```

滚动高低点必须 `shift(1)`，排除当前 bar。价值：代表经典突破/趋势规则；风险是震荡期 whipsaw。

研究邻域：`20/10`、`40/20`、`55/20`、`80/40`，并测试 T+1 close 与 T+2 open。

### S3 — Weekly Dual Moving-Average Trend

```text
Frequency: weekly
Risk-on: SMA(13 weeks) > SMA(40 weeks)
Risk-off: otherwise
Position: 100% target ETF or cash
Decision: final session close of the trading week
Execution: next trading session open
```

价值：降低日线噪声，以中期/长期趋势交叉检验周频信号。风险是转向较慢，并可能与月度趋势策略高度相关。

研究邻域：fast `[10, 13, 20]` weeks，slow `[30, 40, 52]` weeks。

### S4 — Monthly 10-Month SMA Tactical Allocation

```text
Frequency: monthly
Risk-on: month-end Close > SMA(10 months)
Risk-off: otherwise
Position: 100% target ETF or cash
Decision: month-end final session close
Execution: next trading session open
```

价值：简单、低换手、外部研究锚点清晰，适合作为长期趋势核心候选。Faber 的原始研究用于定义起点，不构成未来收益保证。

研究邻域：`8, 9, 10, 11, 12` months，并与日线 SMA200 及周线 SMA40 做 cross-frequency 对照。

### S5 — Monthly QQQ/DIA Dual Momentum

```text
Frequency: monthly
Relative step: select QQQ or DIA with higher trailing 12-month total return
Absolute gate: selected return > cash hurdle
Position: 100% selected ETF; otherwise cash
Decision: month-end final session close
Execution: next trading session open
```

价值：直接研究成长风格与蓝筹风格的相对强弱，同时用 absolute gate 控制风险。风险是只有两个 risky assets，分散度低，universe choice 可能主导结果。

研究邻域：lookback `[6, 9, 12]` months；默认不使用 `12-1`，但作为独立版本验证；cash hurdle 的定义必须版本化。

## 5. 推荐实施顺序

```text
Buy & Hold / Cash golden fixture
    -> S4 Monthly 10M SMA
    -> S2 Daily Donchian
    -> S3 Weekly MA
    -> S1 Daily RSI2
    -> S5 Dual Momentum
```

S4 规则最简单、换手最低，适合首先校验时间、成交和现金语义。S2 覆盖 stateful entry/exit；S3 验证交易日历重采样；S1 引入 Wilder RSI；S5 最后验证多资产选择和组合构建。

## 6. M1 验收矩阵

| 验收项 | QQQ | DIA | Daily | Weekly | Monthly |
|---|---:|---:|---:|---:|---:|
| 双源 raw snapshot | Required | Required | Required | Derived | Derived |
| Asset identity | Required | Required | — | — | — |
| Corporate action audit | Required | Required | Required | Inherited | Inherited |
| Signal causality | Required | Required | Required | Required | Required |
| T+1 execution | Required | Required | Required | Required | Required |
| Cost/delay stress | Required | Required | Required | Required | Required |
| Parameter neighborhood | Required | Required | Required | Required | Required |
| Rolling/OOS report | Required | Required | Required | Required | Required |

任何 P0 数据完整性错误都使结果标记为 `INVALID`，不得进入策略排名。

## 7. 外部研究锚点

- Mebane Faber, *A Quantitative Approach to Tactical Asset Allocation*：https://mebfaber.com/wp-content/uploads/2016/05/SSRN-id962461.pdf
- Moskowitz, Ooi & Pedersen, *Time Series Momentum*：https://w4.stern.nyu.edu/facdir/lpederse/papers/TimeSeriesMomentum.pdf
- AQR, *Time-Series Momentum Original Paper Data*：https://www.aqr.com/Insights/Datasets/Time-Series-Momentum-Original-Paper-Data

这些资料用于冻结可复现的研究假设；所有最终结论仍由 QuantVerify 的数据完整性、样本外和稳健性协议决定。
