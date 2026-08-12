# Metrics v1 Definitions

`MetricSet` v1 is engine-independent. Its input records dated equity and simple-return
observations together with the calendar version, gross/net cost basis, annualization policy,
volatility `ddof`, and a sourced risk-free-rate policy. No metric implementation supplies an
implicit trading-day constant.

## Definitions

- **Total Return:** `last equity / first equity - 1`.
- **CAGR:** `(last equity / first equity)^(days_per_year / elapsed_calendar_days) - 1`.
  Observation count does not stand in for elapsed time.
- **Annualized Volatility:** standard deviation of the declared simple-return observations,
  using the declared `ddof`, multiplied by `sqrt(periods_per_year)`.
- **Sharpe:** arithmetic mean simple excess return divided by periodic standard deviation,
  multiplied by `sqrt(periods_per_year)`. An annual-effective risk-free rate is converted to
  a periodic effective rate with the declared `periods_per_year`; a per-observation rate is
  used directly.
- **Maximum Drawdown:** the minimum of `equity / running_peak - 1`. Drawdowns therefore use
  zero or negative values, and a continuously rising series has drawdown zero.

## State and input policy

`valid` carries one finite Decimal value and no reason. `undefined` carries no value and names
the mathematical reason, including insufficient observations or zero-volatility Sharpe.
`failure` carries no value and identifies a numeric calculation failure. NaN and positive or
negative infinity can never be represented as a valid metric.

Equity must be positive and finite. Simple returns must be finite and greater than `-1`.
Each observation series must have strictly increasing, unique dates. Metrics can be computed
independently: missing equity observations do not suppress return-based metrics, and missing
return observations do not suppress equity-based metrics.

The risk-free policy is a scalar assumption in v1, but it is never anonymous: its unit,
`policy_id`, `source_id`, and `source_version` are persisted in the result. A future version
may add an as-of dated risk-free curve without silently changing v1 semantics.
