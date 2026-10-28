# Variation Analyzer and Dynamic Binning Worked Examples

**Status:** Executable directional and combined-reference examples
**Updated:** 2026-10-13

The Python examples connect the [mathematical rules](VARIATION_AND_DYNAMIC_BINNING.md)
to the [Python API](VARIATION_API_REFERENCE.md). They use synthetic data and do
not read or modify user databases. They require the existing Leonardo Python
environment with the checkout's `src` directory on the import path. No package
installation, GUI, feed or profile store is involved in those code examples.
The following GUI walkthrough is a separate retrospective workflow using saved
databases; it does not inherit the availability assumptions of the forward code.

The code blocks can run in order in one Python session. The restoration block
continues the first example. The tied-magnitude, constant-reference and EMA
examples each include their own imports and setup. The final replay block
continues the EMA example. The wider [Data Analysis Suite](DATA_ANALYSIS_SUITE.md)
remains under development.

## GUI walkthrough: a stored EMA percentage delta

Start with a database that already contains a numeric EMA separation column,
for example a column previously calculated as
`100 * (EMA20 - EMA50) / EMA50`. The GUI consumes its stored values. It does not
create either EMA, verify that formula from a column name, or infer its unit.
Use Data Manager's established workflow to create/import the underlying data.

1. Open **Analysis Suite**, then **Select Databases**. Filter as needed, check
   the saved database and choose **Add Selected**.
2. In **Variation & Binning**, choose it as the single **Active database**.
   Wait for revision validation and column loading; check the EMA delta column.
3. Keep **Directional intensity**, 10 positive bins, 10 negative bins and the
   default minimum of 2000 observations per populated side. If this history has
   fewer samples on a side, its support remains limited; the GUI does not lower
   the minimum automatically.
4. Optionally check additional numeric columns from this same database. Use
   **Column Overrides** to choose, for example, 15 positive bins and 7 negative
   bins for one column. Each selected column is still fitted independently.
5. Choose **Analyze & Bin**. Scroll down to the result-column selector. Select
   the EMA delta result and inspect Distribution, Bins / Bands, Diagnostics and
   Observations. Choosing another completed column only switches presentation.
6. On Observations, use Previous/Next or the page number and scroll horizontally
   to inspect tail frequencies and statuses. For a 6000-row database there are
   12 pages of 500 rows, including any missing warm-up rows.

If the EMA delta changes sign, P01 through P10 describe its positive-magnitude
reference and N01 through N10 its negative-magnitude reference. Equal labels
across signs do not imply equal numerical widths. A positive-only additional
column leaves the negative side absent. A constant column has degenerate support;
an entirely missing column has an issue outcome without a fabricated profile.
Other selected columns remain analyzable.

Inspect the pinned revision, content hash, effective policy and support in
Diagnostics. Historical blanks remain missing. Within-direction tails and
whole-reference tails use different denominators. The strongest bin is not
automatically a very-rare event, and limited support withholds rarity labels.

This run uses the entire saved history retrospectively. Its availability time
is the snapshot read instant, not the original candle/indicator availability.
Do not reuse the resulting interpretation as a causal forward backtest.
Refresh Databases discovers changed revisions; Reload Database clears and
reloads the active selection. Changing settings clears the old result. Cancel
waits for a running calculation to drain, and closing/reopening DAS starts a
fresh session. The workflow reads saved databases but does not save profiles or
write analysis columns back into them.

## Independent signs with ten bins each

This first example uses the directional API. Its positive history is
`[0.1, 0.2, 0.5, 1]`, while its negative magnitude history is `[1, 2, 4, 8]`.
Consequently +1 is at the 87.5th positive-magnitude percentile (P09), whereas
-1 is at the 12.5th negative-magnitude percentile (N02). The references are
neither centered nor mirrored. Zero does not enter either reference.

The tiny sample deliberately retains the default minimum of 2000 per sign.
Bins are descriptive, support is limited, and categorical rarity is withheld.

```python
import json
import numpy as np
import pandas as pd
from leonardo.data.market_id import canonicalize_market_id
from leonardo.financial_tools import (
    DirectionalBinningPolicy, DirectionalBinningProfile, VariationContext,
    analyze_directional_variation, fit_directional_binning,
    classify_directional_binning,
)

directional_context = VariationContext(
    "x", canonicalize_market_id("bybit", "linear", "BTCUSD", "4h"),
    "Synthetic supplied percentage delta; no additional differencing", "1", "percent",
)

def directional_frame(values, start=0):
    timestamps = np.arange(start, start + len(values), dtype="int64")
    return pd.DataFrame({"ts_ms": timestamps, "available_at_ms": timestamps + 1, "x": values})

directional_history = directional_frame([-8., -4., -2., -1., 0., 0.1, 0.2, 0.5, 1., None])
directional_policy = DirectionalBinningPolicy()  # 10 positive, 10 negative
directional_profile = fit_directional_binning(
    directional_history, directional_context, profile_id="directional-example-1",
    calibration_as_of_ms=10, provenance=("synthetic-example",), policy=directional_policy,
)
directional_query = directional_frame([-1., 1., 0., None], 100)
directional_rows = classify_directional_binning(
    directional_query, directional_profile, context=directional_context, mode="forward",
).to_frame()
assert directional_rows["bin_label"].iloc[:2].tolist() == ["N02", "P09"]
assert directional_rows["directional_percentile"].iloc[:2].tolist() == [12.5, 87.5]
assert directional_rows["status"].tolist() == ["limited_support", "limited_support", "zero_value", "missing_value"]
assert directional_rows["conditional_large_tail_label"].isna().all()
# A large negative magnitude occurs more often than this largest positive size:
assert directional_rows["conditional_large_tail_frequency"].iloc[:2].tolist() == [1.0, 0.25]
assert directional_rows["whole_large_tail_frequency"].iloc[:2].tolist() == [4/9, 1/9]
restored_directional = DirectionalBinningProfile.from_dict(
    json.loads(json.dumps(directional_profile.to_dict(), allow_nan=False))
)
pd.testing.assert_frame_equal(
    classify_directional_binning(directional_query, restored_directional,
                                context=directional_context, mode="forward").to_frame(),
    directional_rows, check_exact=True,
)
```

## One sign and independent bin counts

This block continues the directional example. A positive-only reference is
usable without negative observations. The first future negative value is
uncalibrated, regardless of how many positive samples exist. The same rule
applies with signs reversed. Zeros-only profiles are valid, but neither side
has an intensity distribution.

```python
positive_profile = fit_directional_binning(
    directional_frame([0., 1., 2., 4., None]), directional_context,
    profile_id="positive-only-example", calibration_as_of_ms=5,
    provenance=("synthetic-positive-only",),
    policy=DirectionalBinningPolicy(positive_bins=6, negative_bins=12),
)
positive_rows = classify_directional_binning(
    directional_frame([2., -2., 0.], 100), positive_profile,
    context=directional_context, mode="forward",
).to_frame()
assert positive_profile.analysis.reference_kind == "positive_only"
assert positive_profile.analysis.negative.reference_count == 0
assert positive_rows["bin_count"].iloc[:2].tolist() == [6, 12]
assert positive_rows["status"].iloc[1] == "uncalibrated_direction"
assert pd.isna(positive_rows["bin_label"].iloc[1])
assert positive_rows["status"].iloc[2] == "zero_value"

changed_positive_history = directional_history.copy()
changed_positive_history.loc[changed_positive_history["x"] > 0, "x"] *= 1000
before_negative = analyze_directional_variation(directional_history, "x").negative.to_dict()
after_negative = analyze_directional_variation(changed_positive_history, "x").negative.to_dict()
assert before_negative == after_negative
```

The remaining examples document the preserved combined-reference API. Their
seven-band labels and pooled frequencies have different denominators and should
not be interpreted as the directional results above.

## A reference small enough to count by hand

Consider `[1, 2, 3, 3, 4]` as a signed reference. Its five valid values have mean
2.6, population standard deviation approximately 1.019803903, and quartiles
2, 3 and 3. Under default cutoffs, its actual occupancy is
`(0, 0, 1, 3, 1, 0, 0)`.

| New value | L | E | Percentile | Lower tail | Upper tail | Band |
|---|---:|---:|---:|---:|---:|---|
| 0 | 0 | 0 | 0 | 0/5 | 5/5 | `very_low` |
| 1 | 0 | 1 | 10 | 1/5 | 5/5 | `below_typical` |
| 2.5 | 2 | 0 | 40 | 2/5 | 3/5 | `typical` |
| 3 | 2 | 2 | 60 | 4/5 | 3/5 | `typical` |
| 4 | 4 | 1 | 90 | 5/5 | 1/5 | `above_typical` |
| 5 | 5 | 0 | 100 | 5/5 | 0/5 | `very_high` |

Zero and five are outside the reference range. The five-row reference is below
the default support minimum, so all rarity labels are withheld, even for values
inside the range. We retain that default here rather than making a tiny teaching
sample look statistically well supported.

The code adds a sixth missing reference row to demonstrate that the span and
row count include missing observations, while distribution counts do not.

```python
import json
import numpy as np
import pandas as pd

from leonardo.data.market_id import canonicalize_market_id
from leonardo.financial_tools import (
    DynamicBinningProfile, VariationContext, analyze_variation,
    classify_dynamic_binning, fit_dynamic_binning,
)

step = 4 * 60 * 60 * 1000
start = 1_600_000_000_000
reference = pd.DataFrame({
    "ts_ms": start + np.arange(6, dtype="int64") * step,
    "x": [1.0, 2.0, 3.0, 3.0, 4.0, None],
})
reference["available_at_ms"] = reference["ts_ms"] + step
context = VariationContext(
    source="x",
    market_id=canonicalize_market_id("bybit", "linear", "BTCUSD", "4h"),
    parameter_definition="Synthetic supplied percentage values for hand counting",
    parameter_version="example-1",
    unit="percent",
)
analysis = analyze_variation(reference, "x")
assert (analysis.row_count, analysis.valid_count, analysis.missing_count) == (6, 5, 1)
assert analysis.band_counts == (0, 0, 1, 3, 1, 0, 0)
assert (analysis.q1, analysis.median, analysis.q3) == (2, 3, 3)

profile = fit_dynamic_binning(
    reference, context,
    profile_id="hand-counted-value-v1",
    calibration_as_of_ms=int(reference["available_at_ms"].iloc[-1]),
    provenance=("synthetic-hand-counted-example",),
)
query = pd.DataFrame({
    "ts_ms": start + np.arange(6, 13, dtype="int64") * step,
    "x": [0.0, 1.0, 2.5, 3.0, 4.0, 5.0, None],
}, index=range(100, 107))
query["available_at_ms"] = query["ts_ms"] + step
result = classify_dynamic_binning(query, profile, context=context, mode="forward")
rows = result.to_frame()
assert rows["percentile"].iloc[:6].tolist() == [0, 10, 40, 60, 90, 100]
assert rows["lower_tail_count"].iloc[:6].tolist() == [0, 1, 2, 4, 5, 5]
assert rows["upper_tail_count"].iloc[:6].tolist() == [5, 5, 3, 3, 1, 0]
assert rows.loc[103, "tie_lower_percentile"] == 40
assert rows.loc[103, "tie_upper_percentile"] == 80
assert rows.loc[100, "status"] == "outside_reference_range"
assert rows.loc[103, "status"] == "limited_support"
assert rows.loc[106, "status"] == "missing_value"
assert rows[["lower_tail_label", "upper_tail_label"]].isna().all().all()
assert rows.index.equals(query.index)
```

The reported percentile 60 at value 3 is the midpoint of its tie interval
[40, 80]. Calling it "80th percentile" would substitute an inclusive cumulative
convention for the implemented midpoint convention. The lower-tail frequency
0.8 remains separately available and unambiguous.

## Restore a profile and export result rows

This block continues the previous example. Conversion is in memory; a future
storage owner can save the payload without adding filesystem operations to the
financial engine.

```python
payload = profile.to_dict()
encoded_profile = json.dumps(payload, allow_nan=False, sort_keys=True)
restored = DynamicBinningProfile.from_dict(json.loads(encoded_profile))
restored_rows = classify_dynamic_binning(
    query, restored, context=context, mode="forward"
).to_frame()
pd.testing.assert_frame_equal(restored_rows, rows, check_exact=True)

# Mutating the detached payload does not change the original profile.
payload["values"][0] = -999.0
assert profile.values[0] == 1.0

# Convert pandas missing values to JSON null. Preserve profile identity.
records = rows.astype(object).where(rows.notna(), None).to_dict(orient="records")
encoded_rows = json.dumps(records, allow_nan=False)
assert json.loads(encoded_rows)[-1]["percentile"] is None
assert json.loads(encoded_rows)[-1]["profile_id"] == profile.profile_id

# An exported frame is also detached from BinningResult.
rows.loc[103, "raw_value"] = 999.0
assert result.to_frame().loc[103, "raw_value"] == 3.0
```

Result JSON does not carry the original DataFrame index unless the caller adds
it explicitly. The above records retain `ts_ms`, availability and profile ID.
Keep the profile payload/context alongside stored results when interpreting
them later; an ID alone cannot reconstruct a lost reference.

## Tied magnitudes and negative direction

Take 1,900 zeros and 100 values of -1. Magnitude fitting sees 1,900 zeros and
100 ones. At -1, direction remains negative, the magnitude percentile is 97.5,
and the upper-tail frequency is 5%. The result is `high` with an upper label
of `rare`, rather than an invented very-rare distinction among tied ones.

```python
import numpy as np
import pandas as pd
from leonardo.data.market_id import canonicalize_market_id
from leonardo.financial_tools import VariationContext, fit_dynamic_binning, classify_dynamic_binning

step = 4 * 60 * 60 * 1000
reference = pd.DataFrame({
    "ts_ms": np.arange(2000, dtype="int64") * step,
    "x": [0.0] * 1900 + [-1.0] * 100,
})
reference["available_at_ms"] = reference["ts_ms"] + step
context = VariationContext(
    "x", canonicalize_market_id("bybit", "linear", "BTCUSD", "4h"),
    "Synthetic zero-heavy signed percentage values", "example-1", "percent",
)
profile = fit_dynamic_binning(
    reference, context, profile_id="zero-heavy-magnitude-v1",
    calibration_as_of_ms=2000 * step, provenance=("synthetic-zero-heavy",),
    measurement="magnitude",
)
query = pd.DataFrame({
    "ts_ms": np.arange(2000, 2003, dtype="int64") * step,
    "x": [0.0, -1.0, -2.0],
})
query["available_at_ms"] = query["ts_ms"] + step
rows = classify_dynamic_binning(query, profile, context=context, mode="forward").to_frame()
assert profile.analysis.status == "ready"
assert profile.analysis.band_counts == (0, 0, 0, 1900, 0, 100, 0)
assert rows.loc[1, "direction"] == -1
assert rows.loc[1, "percentile"] == 97.5
assert rows.loc[1, "band"] == "high"
assert rows.loc[1, "upper_tail_frequency"] == 0.05
assert rows.loc[1, "upper_tail_label"] == "rare"
assert rows.loc[0, "lower_tail_label"] == "common"
assert rows.loc[2, "status"] == "outside_reference_range"
assert pd.isna(rows.loc[2, "upper_tail_label"])
```

The new -2 measurement is wider than every observed magnitude. Its upper count
is zero, but the engine withholds a tail label instead of estimating how rare
a never-observed magnitude should be.

## A constant reference

A large count cannot compensate for having only one distinct measurement.
A constant reference can compare equality and range, but supplies no meaningful
spread for the implemented band classification.

```python
import pandas as pd
from leonardo.data.market_id import canonicalize_market_id
from leonardo.financial_tools import VariationContext, fit_dynamic_binning, classify_dynamic_binning

context = VariationContext(
    "x", canonicalize_market_id("bybit", "linear", "BTCUSD", "4h"),
    "Synthetic constant values", "example-1", "percent",
)
reference = pd.DataFrame({"ts_ms": [0, 1, 2], "available_at_ms": [1, 2, 3], "x": [7, 7, 7]})
profile = fit_dynamic_binning(
    reference, context, profile_id="constant-v1", calibration_as_of_ms=3,
    provenance=("synthetic-constant",),
)
query = pd.DataFrame({"ts_ms": [3, 4, 5], "available_at_ms": [4, 5, 6], "x": [6, 7, 8]})
rows = classify_dynamic_binning(query, profile, context=context, mode="forward").to_frame()
assert rows["range_position"].tolist() == ["below", "equal", "above"]
assert rows["outside_reference_range"].tolist() == [True, False, True]
assert rows["status"].eq("degenerate_reference").all()
assert rows[["percentile", "band", "upper_tail_count"]].isna().all().all()
```

The tiny integer timestamps here are synthetic ordering markers. The engine
does not check that their spacing matches the context timeframe. Real callers
must supply meaningful epoch milliseconds and correct source identity.

## EMA percentage deltas over a full history and a forward split

This standalone example builds 6,000 synthetic close prices, calculates EMA20
and EMA50 through Leonardo's existing public calculator, then computes:

```text
D1 = 100 × (EMA20 - EMA50) / max(abs(EMA50), resolved epsilon)
D2 = 100 × (close - EMA50) / max(abs(EMA50), resolved epsilon)
```

The settings are demonstration choices, not optimized trading parameters.
Leonardo's EMA uses its existing span, warm-up and recursive convention. With
these complete synthetic inputs, the first 49 rows have no EMA50-derived delta.
The full reference has 5,951 valid values. The first 4,200 rows form the 70%
calibration portion with 4,151 valid values; all 1,800 later rows are available
for forward classification.

Eight separate profiles demonstrate two deltas, two measurement modes, and two
reference scopes. Full-history results are explicitly retrospective. Forward
profiles see only calibration rows, even though the example computes causal
features once over the whole frame to preserve their continuous history.

```python
import json
import numpy as np
import pandas as pd
from leonardo.data.market_id import canonicalize_market_id
from leonardo.financial_tools import (
    VariationContext, calculate_financial_tool, resolve_parameters,
    classify_dynamic_binning, fit_dynamic_binning,
)

n = 6000
step = 4 * 60 * 60 * 1000
axis = np.arange(n)
prices = pd.DataFrame({
    "ts_ms": 1_600_000_000_000 + axis * step,
    "close": 100 + 0.01 * axis + 5 * np.sin(axis / 20),
})

def prepare_features(data):
    prepared = data.copy()
    prepared["available_at_ms"] = prepared["ts_ms"] + step
    for period in (20, 50):
        prepared[f"ema{period}"] = calculate_financial_tool(
            "ema", prepared, {"period": period}
        ).to_frame().iloc[:, 1]
    for source, fast in (("d1", "ema20"), ("d2", "close")):
        prepared[source] = calculate_financial_tool(
            "delta", prepared, {"fast": fast, "slow": "ema50", "mode": "pct"}
        ).to_frame().iloc[:, 1]
    return prepared

features = prepare_features(prices)
assert features[["d1", "d2"]].iloc[:49].isna().all().all()
assert features[["d1", "d2"]].iloc[49:].notna().all().all()
# Prefix-only feature calculation must match what was available then.
for stop in (50, 100, 4200, 4201, 5999):
    pd.testing.assert_frame_equal(
        prepare_features(prices.iloc[:stop]), features.iloc[:stop], check_exact=True
    )

split = 4200
market = canonicalize_market_id("bybit", "linear", "BTCUSD", "4h")
contexts, profiles, results = {}, {}, {}
for source, fast in (("d1", "ema20"), ("d2", "close")):
    definition = {
        "ema20": dict(resolve_parameters("ema", {"period": 20})),
        "ema50": dict(resolve_parameters("ema", {"period": 50})),
        "delta": dict(resolve_parameters("delta", {"fast": fast, "slow": "ema50", "mode": "pct"})),
    }
    contexts[source] = VariationContext(
        source, market, json.dumps(definition, sort_keys=True),
        "canonical-financial-tools-1.0", "percent",
    )
    for measurement in ("value", "magnitude"):
        for mode in ("retrospective", "forward"):
            reference = features if mode == "retrospective" else features.iloc[:split]
            observations = features if mode == "retrospective" else features.iloc[split:]
            key = (source, measurement, mode)
            profiles[key] = fit_dynamic_binning(
                reference, contexts[source],
                profile_id="synthetic-" + "-".join(key) + "-v1",
                calibration_as_of_ms=int(reference["available_at_ms"].iloc[-1]),
                provenance=("synthetic-6000-close-values",), measurement=measurement,
            )
            results[key] = classify_dynamic_binning(
                observations, profiles[key], context=contexts[source], mode=mode
            ).to_frame()
            assert profiles[key].analysis.valid_count == (5951 if mode == "retrospective" else 4151)
            assert len(results[key]) == (6000 if mode == "retrospective" else 1800)
assert len(profiles) == 8
```

The profile for each source includes its resolved formula settings. An actual
data source must also have the matching market identity and recorded provenance;
using BTCUSD as the demonstration context does not make these synthetic prices
real BTCUSD observations.

## Apply the same profile in chunks and one row at a time

This block continues the EMA example and uses the forward D1 magnitude profile.
It checks all forward rows in chunks of 7 and 64, then the first eight rows as
individual calls. Production can use the same one-row call when a completed
feature becomes available.

```python
key = ("d1", "magnitude", "forward")
profile = profiles[key]
context = contexts["d1"]
held_out = features.iloc[split:]
batch = results[key]
before = profile.to_dict()

for chunk_size in (7, 64):
    chunks = [
        classify_dynamic_binning(
            held_out.iloc[start:start + chunk_size], profile,
            context=context, mode="forward",
        ).to_frame()
        for start in range(0, len(held_out), chunk_size)
    ]
    pd.testing.assert_frame_equal(pd.concat(chunks), batch, check_exact=True)

singles = [
    classify_dynamic_binning(
        held_out.iloc[i:i + 1], profile, context=context, mode="forward"
    ).to_frame()
    for i in range(8)
]
pd.testing.assert_frame_equal(pd.concat(singles), batch.iloc[:8], check_exact=True)

# An artificial future shock cannot change earlier classifications.
future = pd.DataFrame({
    "ts_ms": [int(features["ts_ms"].iloc[-1]) + step],
    "available_at_ms": [int(features["available_at_ms"].iloc[-1]) + step],
    "d1": [1e12],
}, index=[n])
extended = classify_dynamic_binning(
    pd.concat([held_out, future]), profile, context=context, mode="forward"
).to_frame()
pd.testing.assert_frame_equal(extended.iloc[:-1], batch, check_exact=True)
assert profile.to_dict() == before
assert extended.iloc[-1]["status"] == "outside_reference_range"
```

An explicit fit on extended history may change classifications under a new
profile. That is a new reference, not instability of the old one. Retain both
profile identities when comparing the resulting descriptions.

## Timing for delayed indicators

For open-stamped four-hour candles, a close-based feature attached to the 08:00
candle is normally known after that candle closes at 12:00. A centered derivative
or angle attached to 08:00 also requires the following 12:00 candle, whose close
is available at 16:00. This assumes complete candles and no additional latency.

| Feature attached to 08:00 | Earliest availability in this example | Eligible for a 12:00 calibration cutoff? |
|---|---|---|
| Close or causal EMA delta | 12:00 | Yes, equality is allowed during fitting. |
| Centered derivative or angle using the following close | 16:00 | No. It can be classified forward once available. |

The engine uses availability, not merely the timestamp written on a historical
indicator row. A value can have an observation timestamp before the calibration
cutoff and still be a later-arriving forward observation. Correct availability
must propagate through composed indicators, including any angle momentum or
derivative-based feature supplied by the caller.

## Read a result as a description

For an in-range negative delta classified in magnitude mode, a useful rendering
might be: "Negative direction; high historical magnitude; equally large or
larger magnitudes occurred in 100 of 2,000 reference observations (5%, rare)."
Those numbers correspond to the tied example above.

Always retain the parameter definition, units, profile ID, reference coverage
and support status with that statement. If the result is outside the reference,
say that it exceeds the observed range. If support is limited or degenerate,
carry that status into the interpretation instead of inventing a rarity label.

The following conclusions do not follow from these examples: that a rare
observation will reverse, that a central band is safe, that matching percentiles
across assets imply equal risk, or that a full-history description was available
at an earlier live decision. Those require separately defined research.
