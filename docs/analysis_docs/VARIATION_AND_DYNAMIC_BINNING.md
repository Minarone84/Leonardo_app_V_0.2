# Variation Analyzer and Dynamic Binning

**Status:** Directional and combined-reference backend mathematical reference
**Updated:** 2026-10-13

The variation engine describes a supplied parameter relative to a chosen
historical distribution. It answers questions such as: how wide is this delta
compared with previous deltas, where does this signed slope lie in its history,
and how often has the reference contained an equally high or low measurement?

The engine separates description, calibration and application. Once calibrated,
a profile gives the same classification to the same observation whether the
caller supplies a full batch, a chunk or one observation. Applying a profile
never updates its reference.

The [Data Analysis Suite](DATA_ANALYSIS_SUITE.md) remains incomplete and its
broader structure may change. This manual covers its accepted statistical
backend. The [API reference](VARIATION_API_REFERENCE.md) gives exact contracts;
the [worked examples](VARIATION_EXAMPLES.md) provide executable usage.

## Contents

- [Independent directional calibration](#independent-directional-calibration)
- [Purpose and meaning](#purpose-and-meaning)
- [The three operations](#the-three-operations)
- [Choosing the measurement](#choosing-the-measurement)
- [Selecting the historical reference](#selecting-the-historical-reference)
- [Empirical position and inclusive tails](#empirical-position-and-inclusive-tails)
- [Bands and rarity labels](#bands-and-rarity-labels)
- [Exceptional observations and support](#exceptional-observations-and-support)
- [Descriptive statistics and numerical behavior](#descriptive-statistics-and-numerical-behavior)
- [Historical and real time use](#historical-and-real-time-use)
- [Profiles and their lifecycle](#profiles-and-their-lifecycle)
- [Saved database snapshots in the GUI](#saved-database-snapshots-in-the-gui)
- [Architecture and the legacy calculator](#architecture-and-the-legacy-calculator)
- [Verification and interpretation limits](#verification-and-interpretation-limits)

## Independent directional calibration

The directional API describes each selected column using two independent
empirical references. Positive observations contribute their values to the
positive magnitude reference. Negative observations contribute their absolute
sizes to the negative magnitude reference. Original signs remain in results.
Exact zeros, including -0.0, are counted separately. Missing values are excluded
only from that column's reference, while their rows and timestamps are preserved.

Zero distinguishes signs; it is not imposed as a mean, median or center. No
Gaussian, centering, symmetry, balancing or mirrored observations are used.
Positive and negative distributions may differ in frequency, scale, spread and
extremes. A supplied delta is analyzed as a delta level. To describe its timestep
change, supply a separately defined change column; no automatic differencing
occurs. A negative level moving toward zero can have a positive change.

### Directional operations and isolation

`analyze_directional_variation` returns independent diagnostics,
`fit_directional_binning` freezes them with identity and time, and
`classify_directional_binning` applies the fixed profile to each input row.
Every call has one source column. Shared policy settings do not share samples.
Changing another column or its missing-value pattern cannot affect the selected
column. Changing positive observations cannot affect the negative conditional
reference or classification, and vice versa. Whole-reference frequencies may
change because they explicitly use the combined finite count.

### Variable percentile bins

`DirectionalBinningPolicy` defaults to `positive_bins=10`, `negative_bins=10`
and `min_reference_count=2000`. Each bin count accepts integers from 1 to 1000;
the counts can differ. The minimum is applied separately to each populated side.

For a query magnitude, let L count strictly smaller magnitudes on the same side,
E count equal magnitudes, and N count all observations on that side. The midrank
percentile is `100 * (L + E/2) / N`. For B bins, the one-based index is:

```text
min(B, 1 + floor(B * (2*L + E) / (2*N)))
```

The implementation uses integer arithmetic for the bin decision, avoiding
floating-point boundary ambiguity and int64 multiplication overflow. The
percentile itself uses the existing shared empirical-rank authority.

Ten bins use percentile intervals [0,10), [10,20), through [90,100]. An exact
cutoff enters the higher bin, except 100 remains in the final bin. Numerical
widths are learned from the observed distribution and need not match across
signs. Within either sign, bin 1 means smaller magnitude and bin B means larger
magnitude. N10 is the strongest negative magnitude bin with B=10.

Labels are P01/P02/... and N01/N02/..., accompanied by the configured count,
percentile interval and a human-readable description. Compare labels only with
their source, profile identity and bin count. P05 with 10 bins has a different
meaning from P05 with 20 bins. The new directional bins do not use the seven
adjective bands of the preserved combined-reference API.

Ties remain together. Empty bins are allowed, the requested count is never
silently reduced, and observations are not forced into equal occupancy.
Diagnostics report every configured bin, its count and observed signed span.
Those observed spans are not interpolated decision thresholds across gaps. The
frozen empirical reference and rank rule decide classification of new values.

### Directional rarity and whole-reference frequency

The inclusive small-magnitude tail is `(L+E)/N`; the inclusive large-magnitude
tail is `(N-L)/N`. Conditional labels are very_rare at frequency <=1%, rare above
1% through 5%, and common above 5%, subject to support/range guards. Integer
count comparisons make threshold inclusion exact. The highest decile is not
automatically a very-rare event. Narrow magnitude can also be rare, using the
small-magnitude tail.

Let T be all finite reference observations, including zeros. The sign frequency
is `N/T`. Whole-reference directional tails are `(L+E)/T` and `(N-L)/T`.
For a negative query, the latter describes observed negative values at least
that large in magnitude across the whole reference. These frequencies remain
numeric evidence; only conditional tails receive rarity labels. Neither is a
future-event probability or the frequency of exactly that value.

### One-sign histories and exceptional rows

| Reference or observation | Directional behavior |
|---|---|
| Positive only or negative only | Fit the populated side independently; the other has absent_reference status, zero samples and no learned ranges. |
| Opposite sign appears later | uncalibrated_direction; retain raw value/sign, but no percentile, bin or tail label. |
| Zero-only reference | Valid profile with both sides absent; zero rows remain zero_value. |
| Empty/all-missing reference | Analysis is insufficient_reference; fitting rejects it. |
| One distinct magnitude on a populated side | degenerate_reference; only below/equal/above magnitude relation, with no rank/bin/tail label. |
| Populated nonconstant side below minimum count | limited_support; descriptive ranks and bins remain available, all categorical rarity labels are withheld. |
| Outside a populated nonconstant side's range | Outer bin and rank 0/100, observed tail counts, outside_reference_range; no rarity labels. |
| Missing application value | missing_value; retain the input row, no directional bin. |
| Exact zero | zero_value; separate historical zero frequency, no directional bin or directional rarity. |

An absent side does not stop the populated side from being ready. Configured
bins on an absent or degenerate side have zero occupancy and no observed spans;
configuration must not be mistaken for learned thresholds. Observing only one
sign in a reference does not establish that another sign is mathematically
impossible. NaN is never converted to zero. Infinity and nonnumeric selected
values retain the existing rejection rules. No near-zero tolerance is added.

### Directional profile lifecycle

The immutable directional format has schema_version=2 and
algorithm_version="directional_empirical_midrank_v1". It includes source context,
policy, both distributions and diagnostics, zero/missing counts, reference span,
availability cutoff and provenance. Restoration recomputes and validates its
canonical diagnostics. There is no conversion from a pooled magnitude profile:
the original signed observations are needed to reconstruct independent sides.

Retrospective analysis may use the whole selected historical span. Forward use
requires a profile containing only information available by its calibration
cutoff, and arriving observations must be available after that cutoff. Changing
bin counts or recalibrating requires a new profile identity. Applying a profile
never updates it; identical prepared inputs give identical batch, chunk and
single-row classifications. Feature state and delivery order remain caller
responsibilities. The mathematical API does not own a database store or live
feed. The separate Analysis adapter described below supplies saved snapshots
to the GUI's retrospective workflow.

The remaining sections document the preserved version-1 combined-reference
API and the legacy calculator. Their seven-band fields, pooled denominators and
zero behavior must not be substituted for the directional rules above.

## Purpose and meaning

A raw value does not establish its historical intensity. A delta of 2 may be
ordinary for one parameter definition and unusual for another. Expressing a
delta as a percentage resolves a unit question, but still does not tell us how
unusual that percentage is in its own history.

The engine retains the original number and attaches a relative description.
Its output separates four questions:

| Question | Output |
|---|---|
| What was observed and in which direction? | `raw_value`, `measured_value`, `direction` |
| Where does it lie in the selected history? | `percentile`, tie endpoints, `band` |
| How often was history at least this low or high? | Lower and upper tail counts, frequencies and eligible labels |
| How much can this reference support? | Reference count, support status, range flag, row status |

Here, "typical" means a specified central band of historical percentile
positions. It does not mean Gaussian, safe, profitable, or close to the arithmetic
mean. "Rare" describes a specified inclusive historical tail frequency.
"Exceptional" and "normal" are interpretation words, not extra API labels.

The method is objective in the sense that explicit inputs and rules produce
repeatable descriptions. Reference selection, parameter definition, measurement
mode and cutoff policy remain deliberate choices. Using the whole database
removes a short rolling window choice, but does not remove the influence of
which periods and observations the database contains.

## The three operations

| Operation | Responsibility | Result |
|---|---|---|
| `analyze_variation` | Describe the supplied reference, including data quality, statistics and band occupancy. | `VariationAnalysis` |
| `fit_dynamic_binning` | Describe and freeze a compatible reference available through a declared cutoff. | `DynamicBinningProfile` |
| `classify_dynamic_binning` | Compare supplied observations with an existing profile. | `BinningResult` |

The caller first computes the feature and prepares the rows. Analysis is optional
before fitting: fitting performs the same analysis internally and stores its
result. Classification uses the frozen distribution and policy, not the mean or
standard deviation, to rank observations.

```text
Caller prepares parameter values, identity and availability
    |
    +--> analyze_variation --> descriptive report
    |
    +--> fit_dynamic_binning --> immutable profile
                                     |
New or historical observations ------+--> classify_dynamic_binning
                                              |
                                       separate result frame
```

"Dynamic" refers to deriving classifications from the observed distribution.
It does not mean that applying a profile automatically adapts it. Recalibration
is a separate explicit operation with a new caller-assigned profile identity.

## Choosing the measurement

`measurement="value"` uses the signed supplied number. Low percentiles mean low
signed values; high percentiles mean high signed values. A very negative value
can lie in the lowest band while being a large movement in absolute size.

`measurement="magnitude"` uses the absolute supplied number. Low bands describe
small magnitudes, and high bands describe large magnitudes. The output retains
the original signed value and its direction: -1, 0 or 1. No sign is synthesized
when the history contains only one sign.

| Intended question | Input and mode |
|---|---|
| Is the EMA separation unusually wide, in either direction? | Supply the delta and choose `magnitude`. |
| Is this delta unusually negative or positive? | Supply the delta and choose `value`; inspect the relevant tail. |
| Is the one-bar increase in delta unusually large? | Calculate that change as a separate feature, define its units and timing, then choose `value`. |
| Is the change unusually strong regardless of direction? | Supply that separate change feature and choose `magnitude`. |

**The analyzer does not automatically differentiate its input.** A delta level,
its first difference, its percentage change and its derivative are distinct
parameters. They require distinct definitions and profiles. Gaps are not filled
and missing rows are not removed to invent a shorter time interval.

The same mechanism accepts percentages, price units, degrees, radians or other
numeric units. The engine does not convert units. The context records the unit
convention, and classification rejects a different context. Positive rescaling
of both a reference and its observations preserves their relative ranks when
floating-point ordering and ties are preserved; such a rescaled series still
needs its correctly identified profile.

## Selecting the historical reference

Every finite observation in the supplied reference has equal weight. Missing
parameter values do not contribute to its distribution. There is no subsampling,
time decay, volatility adjustment, duration weighting or recency preference.
Repeated values contribute repeatedly through their counts.

Fitting stores sorted distinct measured values and their integer frequencies.
For `[1, 2, 3, 3, 4]`, the stored values are `[1, 2, 3, 4]` and counts are
`[1, 1, 2, 1]`. This is an exact frequency representation of the float64
measurements, rather than an approximate histogram or a fitted normal curve.
The profile does not retain the historical DataFrame or each row's timestamp.

A full-span reference describes the mixture of conditions in that selected
history. A long-lasting regime contributes more observations than a short one.
Old conditions continue to matter because their weight does not decay. A
"typical" observation can therefore be unusual for the current hour or regime;
that is a question for a later contextual analysis.

### Multiple databases and market identities

Each profile belongs to a canonical market identity, a source column, a complete
parameter definition and version, and a unit convention. The market identity
includes exchange, market type, symbol and timeframe. Measurement mode is fixed
separately in the profile.

Several databases may contribute observations only after the caller establishes
compatible identities and prepares one reference. Identical overlapping
observations should count once; conflicts must be resolved or reported before
fitting. The engine rejects duplicate timestamps. It does not discover overlaps,
select a preferred database revision, or reconcile conflicts.

Different assets or timeframes use separate profiles in this release. Their
percentiles can compare relative positions within their own histories. A 99th
percentile for BTCUSD and a 99th percentile for another asset do not imply equal
money at risk, volatility, expected return or event probability. Raw pooling
across these identities has no approved weighting rule in this engine.

`provenance` records caller-supplied source identifiers. Those strings are not
automatically verified database revisions or content hashes. The caller must
retain the information needed to reproduce the selected data.

## Empirical position and inclusive tails

Let `x` be the measured observation, `N` the finite reference count, `L` the
number of reference observations strictly below `x`, and `E` the number equal
to `x`. Equality is equality of the stored float64 values, with no proximity
epsilon, jitter or rounding step added by the engine.

```text
percentile                = 100 × (L + E/2) / N
tie_lower_percentile      = 100 × L / N
tie_upper_percentile      = 100 × (L + E) / N
lower_tail_count          = L + E
upper_tail_count          = N - L
lower_tail_frequency      = (L + E) / N
upper_tail_frequency      = (N - L) / N
```

Percentiles use the 0–100 scale. Frequencies use the 0–1 scale. Multiply a
frequency by 100 only for percentage presentation.

The percentile is the midpoint of the strict and inclusive cumulative positions.
For `[1, 2, 3, 3, 4]` and `x=3`, `L=2`, `E=2`, `N=5`: the percentile is 60,
the tie interval is [40, 80], and the inclusive tails are 4/5 and 3/5.
The tails sum to more than one because both include the equal observations.
In general their sum is `1 + E/N`.

For a value absent from the reference, `E=0`, so the tie interval collapses to
one percentile. Values between the same adjacent distinct reference values
receive the same rank. The engine does not interpolate a new probability density
inside a gap. Below the minimum the rank is 0; above the maximum it is 100.

The tie interval describes the mass occupied by equal reference values. It is
not a confidence interval. Identical values always receive identical ranks;
no occurrence is moved to a different band to make populations look uniform.

## Bands and rarity labels

### Percentile bands

The default policy maps percentile position to seven ordered bands:

| Index | Percentile interval | Band | Magnitude interpretation |
|---|---|---|---|
| 0 | [0, 1) | `very_low` | Very low historical magnitude |
| 1 | [1, 5) | `low` | Low historical magnitude |
| 2 | [5, 25) | `below_typical` | Below the central magnitude band |
| 3 | [25, 75) | `typical` | Central historical magnitude band |
| 4 | [75, 95) | `above_typical` | Above the central magnitude band |
| 5 | [95, 99) | `high` | High historical magnitude |
| 6 | [99, 100] | `very_high` | Very high historical magnitude |

An exact cutoff enters the higher band: percentile 75 is `above_typical`.
`BinningPolicy` accepts six strictly increasing cutoffs inside (0, 100), while
preserving these seven names and indices. Custom cutoffs change their percentile
meaning; consumers must retain the profile's policy when interpreting the labels.

The nominal default widths are 1%, 4%, 20%, 50%, 20%, 4% and 1%. They are not
guaranteed occupancy percentages. `band_counts` reports actual reference
occupancy, including ties. Future observations may have a very different band
distribution; application does not rebalance them.

These are percentile boundaries, not seven equal intervals of the original
units. The profile's distribution and percentile policy are authoritative.
A displayed raw-value range would be a derived summary, not a replacement
classification rule.

### Inclusive tail labels

When support is adequate and the observation is inside the reference range,
each inclusive tail receives its own label:

| Frequency | Label |
|---|---|
| At most 0.01 | `very_rare` |
| Greater than 0.01 and at most 0.05 | `rare` |
| Greater than 0.05 | `common` |

These thresholds are fixed in algorithm version `empirical_midrank_v1`.
Changing band cutoffs does not change them. A high magnitude is interpreted
using the upper tail; a narrow magnitude uses the lower tail. For signed
measurements, the lower tail describes low/negative extremes and the upper
tail describes high/positive extremes.

A band and a tail label answer different questions. Consider 1,900 zeros and
100 ones. At `x=1`, the midpoint rank is 97.5 (`high`), while the inclusive upper
tail is 100/2,000 = 5% (`rare`). Repeated extreme values do not become rarer just
because they share the largest numeric value.

No single combined "two-sided rarity" score is emitted. In particular, callers
should not silently double the smaller tail or replace magnitude analysis with
an undocumented signed-score transformation.

## Exceptional observations and support

The analysis selects reference status in this order:

1. Zero finite observations: `insufficient_reference`.
2. One distinct measured value: `degenerate_reference`.
3. More than one distinct value but fewer than `min_reference_count` finite rows:
   `limited_support`.
4. Otherwise: `ready`.

The default minimum is 2,000 finite observations. It is configurable and recorded
in the profile. This count would put 20 observations in a nominal 1% tail, but
ties and dependence make it an engineering guard, not a confidence guarantee.
`ready` means that the implemented support rule passed, not that the sample is
independent or representative of future markets.

| Situation | Actual behavior |
|---|---|
| Empty or all-missing reference | Analysis reports no finite statistics and zero occupancy; fitting rejects it. |
| Constant reference, including all zero | Fitting succeeds as `degenerate_reference`. Valid application rows retain below/equal/above relation and range flag, but have no percentile, tails, band or rarity labels. |
| Limited reference | Numeric ranks, inclusive counts/frequencies and bands remain available; both tail labels are missing, including a would-be `common` label. |
| Missing application value | Original row/index and profile metadata remain; status is `missing_value`; measurement/rank/tail/band/range outputs are missing. |
| Outside a nonconstant reference | Percentile 0 or 100 and the outer band are emitted with observed tails. Status is `outside_reference_range`; both tail labels are missing. |
| Exact minimum or maximum | Inside the range, including ties; labels may be available if support is `ready`. |

`support_status` always reports the reference's status. The row's `status`
reports its own situation. For example, an outside row from a limited reference
has `support_status="limited_support"` and
`status="outside_reference_range"`. A missing row takes `missing_value` even
with a degenerate profile. A finite outside row from a degenerate profile keeps
`status="degenerate_reference"`, with its range flag showing the difference.

A zero observed tail count beyond the reference does not establish zero future
probability. Withholding its label avoids presenting an unobserved extent as an
estimated rarity category. No extreme-value extrapolation is performed.

## Descriptive statistics and numerical behavior

Analysis reports total, finite, missing, distinct and original sign counts;
first and last input timestamps; minimum, maximum, mean, population standard
deviation, first quartile, median and third quartile; support status; and actual
band occupancy. The span includes rows whose parameter is missing.

In magnitude mode, extrema and moments describe absolute values, and distinct
count refers to distinct magnitudes. Sign counts still describe the original
signed observations. Thus `[-4, -2, 0, 2, 4]` has five signed distinct values
but only three distinct magnitudes; both analyses retain two negatives, one
zero and two positives.

For measured distinct values `v_i` and counts `c_i`, the mathematical conventions
are mean `sum(c_i × v_i)/N` and population variance
`sum(c_i × (v_i - mean)^2)/N`. Standard deviation is the square root of that
variance; its denominator is `N`, not `N-1`.

Quartiles use linear interpolation of order statistics. For quantile fraction
`q` in {0.25, 0.5, 0.75}, let `h=(N-1)q`, `j=floor(h)` and `g=h-j`. The
quantile lies at `(1-g) × y[j] + g × y[j+1]` in the conceptually expanded
sorted reference, using the same value when `g=0`. The implementation finds
these positions from cumulative counts without expanding repeated observations.

These descriptive quantiles do not define the empirical percentile function.
They can fall between observations; the ranking rule continues to use strict
and equal counts. A median statistic and a percentile-band boundary are related
descriptions with different computational definitions.

### Finite arithmetic and the accepted corrections

Mean and population standard deviation use scaled float64 moments to avoid
overflow in sums and squared deviations. They remain floating-point summaries;
the algorithm does not promise arbitrary precision or perfect recovery after
extreme cancellation.

Quartiles interpolate adjacent original values, so globally scaling a reference
cannot erase its tiny values before interpolation. Same-sign endpoints use a
finite difference; opposite-sign endpoints use weighted terms to avoid an
overflowing subtraction. For `[1e-300, 2e-300, 3e-300, 1e308]`, the quartiles
are approximately `1.75e-300`, `2.5e-300`, `2.5e307`.

Profile construction and restoration recompute statistics from the stored
distribution. Contradictory statistics or recoverable sign counts are rejected.
Counts, extrema and occupancy must match exactly. Mean, standard deviation and
quartiles permit relative tolerance `1e-12`; only the mean also permits absolute
tolerance `64 × float64_epsilon × max(abs(reference))` for cancellation.
Quartiles and standard deviation have zero absolute tolerance. These checks do
not change the ranking rule.

Magnitude profiles cannot reconstruct the original positive/negative split
from absolute values. They validate zero count and total nonzero count, while
retaining the supplied original sign split as metadata. A signed profile
validates its positive and negative counts separately.

## Historical and real time use

### Retrospective description

Fit the selected full history and apply that profile with
`mode="retrospective"`. Earlier observations can be described relative to later
history. This is valid historical description; it must not be presented as what
a system would have known at the earlier observation time.

Retrospective classification still validates input structure and availability
not preceding observation time. It imposes no ordering relationship between
application availability and the profile cutoff, and does not require the
application frame to equal the calibration frame.

### Forward evaluation

Fitting requires `available_at_ms <= calibration_as_of_ms` for every reference
row. Forward classification requires
`available_at_ms > calibration_as_of_ms` for every supplied application row.
The boundary is inclusive for calibration and exclusive for forward use.
It applies even to missing parameter rows.

`ts_ms` identifies the observation. `available_at_ms` says when the complete
feature value could be known. Both are integer epoch milliseconds; the caller
must translate source conventions correctly. On open-stamped four-hour candles,
a close-based value is available at opening time plus four hours, assuming the
candle is completed. Provider latency may require later availability.

Current derivative and angle calculations use a following observation. Their
value attached to time `t` therefore becomes available only after the required
following input is known. A composed feature must inherit every dependency's
delay. The engine checks supplied times; it does not inspect the formula or
prove that the availability metadata is truthful.

Keep the feature calculation's historical state continuous across a replay
split. Restarting an EMA at every chunk would change the feature values before
classification. Batch versus single-row equality assumes identical prepared
values, context, profile, mode, timestamps and indices.

### Real time responsibilities

The classifier can evaluate one new row using a historical profile. No full
historical DataFrame is needed at application time. This establishes the backend
mechanism for live use; feed integration remains separate.

The caller owns completed-candle detection, feature state, delivery ordering,
deduplication across calls, retries, output storage and any recalibration policy.
Within each call, observation timestamps must increase strictly. Availability
times need not increase across rows, and the engine stores no last-seen timestamp
between calls. Repeating a valid one-row call is allowed and produces the same
result; exactly-once delivery is not an engine guarantee.

## Profiles and their lifecycle

Create a `VariationContext` for one parameter and use `BinningPolicy` for its
cutoffs and minimum support. Fit with a nonempty profile ID, explicit calibration
cutoff and unique nonempty provenance identifiers. All five models and all three
operations are exported by `leonardo.financial_tools`.

The profile freezes the context, measurement, policy, cutoff, provenance,
analysis, distinct values and counts. Its private lookup arrays are read-only
and reconstructed from that distribution. Neither later changes to the input
frame nor changes to an exported dictionary mutate the profile. Result
`to_frame()` also returns a defensive copy.

`to_dict()` returns a detached finite JSON-compatible payload.
`DynamicBinningProfile.from_dict()` rejects unsupported versions, missing or
extra fields, malformed identities, invalid policies and inconsistent
distribution diagnostics. The accepted representation has `schema_version=1`
and `algorithm_version="empirical_midrank_v1"`.

Validation establishes internal consistency, not authenticity of the original
database. A payload does not contain per-row availability or source data with
which to reconstruct every provenance claim. The caller retains that evidence.
This format is a versioned backend representation, not a new application-owned
Artifact or Database persistence family.

Applying a profile performs no filesystem writes. The caller may serialize it,
retain its identity with results, and restore it later. To recalibrate, fit a
new reference and assign a new ID. ID uniqueness is a caller responsibility;
there is no profile registry or automatic replacement policy. Old results keep
their meaning only when their original profile and context remain identifiable.

## Saved database snapshots in the GUI

The production Variation & Binning tab now calls the public profile APIs through
the Analysis area. The [Suite workflow](DATA_ANALYSIS_SUITE.md#run-an-analysis-from-the-gui)
explains the controls. This adapter does not alter the formulas in this manual.

One run freezes one `(database_id, revision_id, values_sha256)` reference and a
set of column settings. Public Data Manager loading validates the revision;
Analysis then checks CSV shape, column mapping, ordered timestamps, numeric
eligibility and the selected identities. It preserves row order and uses the
whole saved historical span. A newer database head is not substituted during
execution. Refresh/reload are explicit source-selection actions.

Each selected column receives a minimal frame containing its own values,
observation timestamps and snapshot availability timestamps. No joint missing-row
filter, concatenated reference, shared fitted profile or cross-column scaling is
introduced. Shared defaults are policies only. Fits use the full column history;
classification may be chunked against that same fixed profile and concatenated
in original order. Direct-call parity tests cover the same prepared input,
context and policy.

Database snapshots currently lack reliable original per-observation availability
and complete formula/unit metadata. The adapter therefore uses the UTC instant
after validated snapshot loading for all `available_at_ms` values and for
`calibration_as_of_ms`; classification is `retrospective`. This records when the
snapshot was read, not when its historical candles or indicators first became
usable. It rejects candle timestamps later than that instant. These GUI profiles
must not be treated as evidence for causal forward evaluation.

The context definition identifies the stored column, exact revision and content
hash, including saved member/output metadata where present. Its parameter version
is a hash of that definition. Its unit is explicitly
`unspecified_database_native_unit`; numerical values are not rescaled. Source
names are not formula or unit authority. Profile IDs are fresh per fit, while
the same supplied observations and policy retain the same classifications.

Blank values become NaN only for their own column. All-missing columns return
an `insufficient_reference` issue with preserved observation rows and no profile;
other columns can finish. For every fitted directional column, the GUI exposes
all 35 backend result fields. Zero-only and degenerate references remain valid
profiles with the backend's withheld fields. Unexpected exceptions fail the
whole run without publishing partial results.

The Distribution view is an empirical CDF of original signed finite values,
including in magnitude mode; mode-specific statistics are in Diagnostics. Its
display can reduce the drawing to 2000 points, retaining endpoints, but reference
statistics, occupancy and classification always use the complete data. No fitted
Gaussian or symmetric axis changes the interpretation. Bins / Bands displays
backend occupancy plus observed signed spans, not invented decision boundaries.
Observations pages contain 500 rows; every row and field is accessible.

The Analysis application facade uses shared Core blocking jobs. Cancellation
checks occur around loading/fits, between columns and classification chunks,
and before publication. A fit is not interrupted mid-call. The facade retains
the worker until it actually returns, and the GUI suppresses stale callbacks
after changes or disposal. Closing the window releases its in-memory results;
no profile registry, result store or database mutation is added.

## Architecture and the legacy calculator

| Source | Current responsibility |
|---|---|
| [variation.py](../../src/leonardo/financial_tools/variation.py) | Thin public analyze, fit and classify entry points. |
| [variation_models.py](../../src/leonardo/financial_tools/variation_models.py) | Models, shared empirical rank/statistics, immutability and restoration checks. |
| [variation_analysis.py](../../src/leonardo/financial_tools/_calculation/variation_analysis.py) | Input validation, measured distribution preparation, diagnostics and occupancy. |
| [dynamic_binning.py](../../src/leonardo/financial_tools/_calculation/dynamic_binning.py) | New profile calibration/application helpers alongside the retained legacy calculator. |
| [financial_tools exports](../../src/leonardo/financial_tools/__init__.py) | Supported import surface. |

The mathematical tasks are separate even where helpers share a file. Analysis
prepares and describes the distribution; fitting packages it with identity and
time; application reads that fixed profile. Shared rank and statistics helpers
keep one computational authority for each rule.

The pre-existing `calculate_financial_tool("dynamic_binning", ...)` entry point
continues to use its earlier algorithm. Its internal variation helper estimates
spacing from successive changes; its binning helper fits signed bins to the
original levels. They historically belong together because the first supplies
the second's minimum step. That pipeline fits again on every supplied frame.

| Aspect | Accepted profile API | Retained legacy calculator |
|---|---|---|
| Calibration/application | Separate operations with immutable reference | One calculation refits the supplied frame |
| Measurement | Explicit signed value or magnitude | Signed levels, with spacing estimated from changes |
| Reference model | Distinct values and frequencies | Separate positive/negative fitted edges |
| Missing sign | No invented observations | Missing side can mirror the observed side |
| Output classes | Seven percentile bands plus tails/statuses | `AB0...` and `BL0...` threshold labels |
| Near-zero ranking epsilon | None | Legacy `boundary_eps` comparison rule |
| Constant reference | Explicit degenerate profile | Earlier heuristic behavior retained |
| Integration | Explicit backend calls | Existing Financial Tool calculator contract |

The legacy analysis keys remain `steps`, `variation_diagnostics`,
`binning_artifact` and `labeled_rows`. Its accepted update added only rejection
of infinity and selected-source/generated-label collisions. Valid legacy
numerical outputs and defaults remain unchanged. Existing saved analyses are not
migrated, and existing callers do not silently switch to the profile engine.
The [API reference](VARIATION_API_REFERENCE.md#legacy-calculator-reference)
documents its parameters and returned structures.

## Verification and interpretation limits

The accepted implementation covers hand-counted ranks and ties, skewed and
asymmetric distributions, missing/constant data, support guards, unit rescaling,
identity/time rejection, defensive copies, JSON restoration, delayed indicators
and equality between batch, chunk and individual application. See the
[verification map](VARIATION_API_REFERENCE.md#source-and-test-map).

The accepted package audit independently checked the two corrected numerical
boundaries and real BTCUSD EMA percentage deltas. These checks establish
reproducible behavior for the specified method. They do not establish predictive
usefulness, stationary markets, independent samples, calibrated future event
probabilities, or a trading strategy.

The present engine intentionally supplies a historical descriptive layer.
UTC/session conditioning, regime analysis, cross-feature event definitions,
investigation orchestration, automated recalibration and live integration
remain separate work. The GUI integration above is limited to independent
columns from one saved revision in retrospective mode. Preserve raw values and
all interpretation metadata so
that future layers can use these descriptions without losing their origin.
