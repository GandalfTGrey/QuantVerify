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

| 角色 | 接口 | 用途与准入状态 |
|---|---|---|
| Primary candidate | Tushare Pro `us_daily_adj` | 美股复权日线生产候选源；当前 token 未开通独立美股日线权限，因而 blocked |
| Secondary | AkShare `stock_us_daily` / `stock_us_hist` | 独立聚合源交叉验证；仅 raw OHLC 可进入比较，当前 QQQ 覆盖缺口仍为 P0 |
| P1 professional candidate | Massive REST `v1/open-close` | 已配置 API key；用于独立日线 OHLCV 验证。当前基础计划仅 EOD、两年历史，适合近期窗口，不能补齐 QQQ 的早期缺口 |
| P1 public candidate | Alpha Vantage `TIME_SERIES_DAILY_ADJUSTED` | 可取得 raw OHLCV、adjusted close、拆分与分红事件的公开 API；接入前须以独立 API key、许可、限频、QQQ/DIA 覆盖和 corporate-action 窗口验证 |
| P2 public secondary | `yfinance` / Yahoo Finance | 已配置 `yfinance.download` raw OHLCV adapter，并通过 QQQ/DIA 近期实数探针；仅限研究和交叉验证，Yahoo 条款为个人使用，不能成为生产唯一真相源 |
| P2 official API candidate | Alpaca Market Data `StockHistoricalDataClient` | 官方 SDK；需要 key。Basic 计划美股历史自 2016 年起，适合近期窗口验证，不能补齐 QQQ 的早期缺口 |
| Integration only | OpenBB Platform | 高活跃开源数据集成层，不是独立行情事实源；其底层 provider 必须分别存储并参与双源校验 |
| Official anchor | Invesco / State Street | 标的身份、基金行动和关键冲突人工校验 |
| Cash | FRED DFF/EFFR（M2） | 未投资现金收益；M1 fixture 可显式使用 0% |

Tushare 官方文档说明 `us_daily_adj` 的复权因子可能因除权事件刷新。因此每次抓取必须保存不可变 raw snapshot 和内容哈希，不能只保存“最新复权历史”。AkShare 由公开网站聚合，作为验证源而不是无条件事实源。

候选源在 2026-08-10 按可部署性、公开 SDK 的维护活跃度和 GitHub 社区规模复核：[Massive Python client](https://github.com/massive-com/client-python) 约 1.5k stars、上月有推送；[yfinance](https://github.com/ranaroussi/yfinance) 约 24.9k stars、两日内有推送；[Alpha Vantage Python wrapper](https://github.com/RomelTorres/alpha_vantage) 约 4.9k stars、两周内有推送；[Alpaca 的官方 Python SDK](https://github.com/alpacahq/alpaca-py) 约 1.45k stars、当日有推送；[OpenBB](https://github.com/OpenBB-finance/OpenBB) 约 71.7k stars、上月有推送。星数与活跃度只用于降低接入维护风险，不构成数据准确性或授权证明。[Massive 的日线文档](https://massive.com/docs/rest/stocks/aggregates/daily-ticker-summary)说明其基础计划为 EOD、两年历史，且默认 split-adjusted；[Alpha Vantage 文档](https://www.alphavantage.co/documentation/)承诺其 adjusted 日线包含 raw OHLCV、adjusted close 及拆分/分红事件；`yfinance` 明示其数据来自 Yahoo 的公开 API、仅供研究教育且 Yahoo API 限个人使用；[Alpaca Basic](https://docs.alpaca.markets/us/docs/about-market-data-api) 的美股历史覆盖自 2016 年起；OpenBB 也明示其聚合数据未必准确。因此，上述候选在通过本项目的 snapshot、许可、覆盖和双源 contract tests 前均不得替代 primary。

2026-08-10 的本机接口探针结果：base conda 中 AkShare 1.18.83 可获取 QQQ 与 DIA 的 raw/qfq 日线，最新 session 为 2026-08-07；当前返回的 QQQ 起点为 2001-01-02、DIA 起点为 2005-01-03。该起点明显不是基金身份意义上的成立日，只代表当前接口可见覆盖范围。Tushare 1.4.29 已按供应商指定端点完成 `daily` 基线调用（13 行），但 `us_daily_adj` 仍被阻断；token 状态为有效、10,000 积分、无独立权限，而美股日线属于独立权限。隔离环境中的 yfinance 1.5.2 已使用 `auto_adjust=False`、`actions=False` 和 inclusive-range adapter 成功抓取 QQQ、DIA 在 2025-01-02 至 2025-01-10 的 raw OHLCV（各 6 个交易日），并完成长历史连通性探针：QQQ 为 1999-03-10 至 2026-08-07（6,896 行），DIA 为 1998-01-20 至 2026-08-07（7,182 行）。与 AkShare raw snapshot 的共同交易日收盘价对比中，DIA 5,432 日的最大相对差为 0.146%；QQQ 4,844 日的中位差约为 0、95 分位为 0.014871%，但 2002-11-01 有 2.851324% 的单日冲突，须保留为人工裁决样本。

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
