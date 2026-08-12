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

The initial equity must be strictly positive and finite; subsequent equity may be zero but may
not be negative. Simple returns must be finite and greater than or equal to `-1`. These bounds
preserve a legitimate 100% long-only loss while rejecting impossible unlevered losses below
100%. Each observation series must have strictly increasing, unique dates. Metrics can be
computed independently: missing equity observations do not suppress return-based metrics, and
missing return observations do not suppress equity-based metrics.

When both observation series are supplied, they must describe exactly one trajectory. There
must be one return for every adjacent equity pair; each return is dated on the later equity
observation and must exactly equal `equity_t / equity_(t-1) - 1`. V1 has no reconciliation
tolerance. Zero equity and a `-1` simple return are terminal because percentage returns after a
zero base are undefined. Equity-only and returns-only inputs remain supported, with metrics
requiring the absent source reported as `undefined`.

The status/reason matrix is closed: `valid` has a finite value and no reason; `failure` has no
value and uses only `numeric_error`; `undefined` has no value and uses only the declared
mathematical-domain reasons. A numeric calculation error cannot be mislabeled as undefined, and
a mathematically undefined result cannot be mislabeled as a calculation failure.

The risk-free policy is a scalar assumption in v1, but it is never anonymous: its unit,
`policy_id`, `source_id`, and `source_version` are persisted in the result. A future version
may add an as-of dated risk-free curve without silently changing v1 semantics.

## Deferred integration requirements

V1 does not yet bind observation content, range, or count into an artifact identity. Artifact v2
must bind the full `MetricInput` lineage before persistence or application use. Upstream
frequency/calendar preflight must prove that dated return intervals support the declared
`periods_per_year`. The scalar risk-free source has no as-of, availability, or currency contract
and must not be presented as a causal risk-free curve.
