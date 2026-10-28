# Variation Analyzer and Dynamic Binning API Reference

**Status:** Directional and combined-reference backend contract reference
**Updated:** 2026-10-13

This reference specifies the Python operations, internal models, result columns
and validation boundaries of the variation engine. Read the
[mathematical guide](VARIATION_AND_DYNAMIC_BINNING.md) for interpretation and
[worked examples](VARIATION_EXAMPLES.md) for complete calls. The wider
[Data Analysis Suite](DATA_ANALYSIS_SUITE.md) remains incomplete; this API has no
GUI, feed, database discovery or application persistence side effects.

## Contents

- [Directional API](#directional-api)
- [Imports and operations](#imports-and-operations)
- [Input frame requirements](#input-frame-requirements)
- [Context and policy](#context-and-policy)
- [Analysis fields](#analysis-fields)
- [Profile fields and conversion](#profile-fields-and-conversion)
- [Classification result](#classification-result)
- [Validation and error handling](#validation-and-error-handling)
- [Legacy calculator reference](#legacy-calculator-reference)
- [Source and test map](#source-and-test-map)

## Directional API

Import `analyze_directional_variation`, `fit_directional_binning`,
`classify_directional_binning`, `DirectionalBinningPolicy`,
`DirectionalVariationAnalysis`, `DirectionalBinningProfile` and
`DirectionalBinningResult` from `leonardo.financial_tools`. Reuse
`VariationContext`. These are additive APIs; the original operations below
retain their version-1 meanings.

```text
analyze_directional_variation(data, source, *, policy=DirectionalBinningPolicy())
    -> DirectionalVariationAnalysis
fit_directional_binning(data, context, *, profile_id, calibration_as_of_ms,
                        provenance, policy=DirectionalBinningPolicy())
    -> DirectionalBinningProfile
classify_directional_binning(data, profile, *, context, mode)
    -> DirectionalBinningResult
```

DataFrame, source, timestamp, availability, context and mode requirements are
the same as documented below. Directional calls always analyze the magnitude
within the original sign; they have no `measurement` argument. Fit rejects
empty/all-missing references but accepts one-sign, zero-only, limited and
degenerate references with explicit per-side diagnostics. Analyze does not
require availability; fit/classify do. No sorting, differencing or imputation
occurs.

### Directional policy and analysis

The frozen policy contains `positive_bins=10`, `negative_bins=10`, and
`min_reference_count=2000`. Bin counts must be integers 1-1000; booleans,
fractional values and strings are invalid. Minimum count is a positive int64
integer. `to_dict()` also includes fixed `tail_frequency_cutoffs=[0.01,0.05]`;
`from_dict()` validates exactly those fields and thresholds.

`DirectionalVariationAnalysis` stores `source`, `policy`, `row_count`,
`missing_count`, `zero_count`, `reference_start_ms`, `reference_end_ms`,
`positive` and `negative`. Its `valid_count` is derived from both side counts
plus zeros. `reference_kind` is mixed, positive_only, negative_only, zero_only
or empty. Overall `status` is available or insufficient_reference; available
does not imply either side has adequate support.

Each side is an internal immutable reference with direction (-1/+1),
`bin_count`, `min_reference_count`, ascending strictly positive magnitude
`values`, corresponding positive integer `counts`, and `reference_count`.
Its `status` is absent_reference, degenerate_reference, limited_support or
ready. Empty references are valid. Count totals must fit int64.

The analysis dictionary adds positive/negative counts and positive/negative/zero
frequencies over the finite reference (null frequencies when empty). Side
dictionaries add `distinct_count`, `magnitude_statistics` (minimum, maximum,
mean, population std, q1, median, q3), `occupied_bins`, `empty_bins`, and `bins`.
Each bin dictionary contains bin_index, label, description, percentile_start,
percentile_end, count, observed_signed_minimum and observed_signed_maximum.
Empty/degenerate references have no occupied intensity bins. Stats are null
only for an absent side; observed bin spans are null when unoccupied.

Analysis and side diagnostics are recomputed from the distributions during
restoration. Their canonical JSON types and values must match; malformed counts,
signs, policy links, statistics, spans, frequencies or occupancies are rejected.
These dictionaries are defensive projections, not application persistence.

### Directional profiles

`DirectionalBinningProfile` contains `profile_id`, `context`,
`calibration_as_of_ms`, `provenance` and `analysis`. Its `policy` property returns
the analysis policy. Profile source must match the context; at least one finite
observation is required, and the reference end cannot follow the cutoff.
Provenance is a nonempty sequence of unique nonempty identifiers.

`to_dict()` emits exactly schema_version, algorithm_version, profile_id, context,
calibration_as_of_ms, provenance and analysis. Versions are integer 2 and
"directional_empirical_midrank_v1". `from_dict()` validates the exact keys and
version, reconstructs readonly lookup arrays and validates the analysis.
Version-1 profiles remain readable by their original reader; neither reader
silently converts the other format. No profile files are automatically written.

### Directional classification columns

The result object stores `profile_id`, `context`, `mode` and a defensive frame.
`to_frame()` returns a fresh copy preserving the input index and row order.
Empty inputs with required columns return the same typed, empty result schema.

| Columns | Type and meaning |
|---|---|
| ts_ms, available_at_ms | int64 input observation and availability timestamps |
| source, profile_id, measurement, mode | string metadata; measurement is directional_intensity |
| raw_value, magnitude | Nullable Float64 original value and absolute size |
| direction | Nullable Int64 -1, 0 or +1; missing for missing input |
| whole_reference_count, zero_reference_count | Nullable Int64 finite total including zeros, and exact zero count |
| zero_reference_frequency | Nullable Float64 zero count / finite total |
| directional_reference_count | Nullable Int64 count for the observation's sign; 0 for an absent sign, missing for zero/missing rows |
| direction_frequency | Nullable Float64 side count / finite total; zero frequency for zero rows, missing for missing rows |
| directional_percentile, tie_lower_percentile, tie_upper_percentile | Nullable Float64 empirical rank and tie endpoints within the side |
| small_magnitude_tail_count, large_magnitude_tail_count | Nullable Int64 inclusive counts within the side |
| conditional_small_tail_frequency, conditional_large_tail_frequency | Nullable Float64 tail count / side count |
| whole_small_tail_frequency, whole_large_tail_frequency | Nullable Float64 same directional tail count / finite total |
| bin_index, bin_count | Nullable Int64 one-based classification and configured side count; count remains available for an absent/degenerate side but index does not |
| bin_label, bin_description | Nullable string P01/N01/... and generated direction/bin/percentile description |
| bin_percentile_start, bin_percentile_end | Nullable Float64 configured percentile interval; final upper endpoint includes 100 |
| conditional_small_tail_label, conditional_large_tail_label | Nullable string common, rare or very_rare, when eligible |
| range_position | Nullable string below, inside, above; equal replaces inside for a degenerate reference; always compares magnitudes |
| outside_reference_range | Nullable boolean; undefined for absent signs, zero and missing values |
| support_status | Nullable string per-side status; not_applicable for zero, missing for missing input |
| status | string missing_value, zero_value, uncalibrated_direction, degenerate_reference, limited_support, ready or outside_reference_range |

Missing and zero rows have no directional rank, bin or tails. Absent sides have
no ranks/bins/tails; zero observed frequency is not an estimated impossibility.
Degenerate sides expose only range relations. Limited sides retain descriptive
bins/ranks/tails but no categorical rarity. Outside nonconstant references,
numeric ranks/tails and the outer bin remain, with rarity labels withheld.
Whole-reference frequencies never acquire categorical rarity labels in this
version. Support status stays visible when row status reports outside range.

### Directional implementation and verification

Source authority is `directional_variation.py`,
`directional_variation_models.py` and `_calculation/directional_binning.py`
inside Financial Tools. Shared input, availability, empirical-rank and
statistics helpers remain in the existing variation implementation. Tests are
`test_directional_variation_analysis.py`, `test_directional_binning_profiles.py`
and `test_directional_binning_replay.py` under the Financial Tools test directory.
They cover sign/column independence, direct-count oracles, one-sign histories,
exact boundaries, large counts, malformed profiles and causal replay.

The remaining model and result sections specify the preserved combined-reference
version-1 API. Shared input and VariationContext rules apply to both APIs.

## Imports and operations

The public import surface is `leonardo.financial_tools`. It exports the three
functions below and `VariationContext`, `BinningPolicy`, `VariationAnalysis`,
`DynamicBinningProfile` and `BinningResult`. Private helpers are implementation
details, not caller entry points.

Signatures are shown as declarations, not executable examples:

```text
analyze_variation(
    data: pandas.DataFrame,
    source: str,
    *,
    measurement: str = "value",
    policy: BinningPolicy = BinningPolicy(),
) -> VariationAnalysis

fit_dynamic_binning(
    data: pandas.DataFrame,
    context: VariationContext,
    *,
    profile_id: str,
    calibration_as_of_ms: int,
    provenance: tuple[str, ...],
    measurement: str = "value",
    policy: BinningPolicy = BinningPolicy(),
) -> DynamicBinningProfile

classify_dynamic_binning(
    data: pandas.DataFrame,
    profile: DynamicBinningProfile,
    *,
    context: VariationContext,
    mode: str,
) -> BinningResult
```

Arguments following `*` are keyword-only. The default policy is immutable.
`measurement` accepts exactly `value` or `magnitude`. Application gets its
measurement and policy from the profile; there is no application-time override.
`mode` must explicitly be `retrospective` or `forward`.

### Analyze

`analyze_variation` validates the frame, transforms the selected values when
magnitude is requested, counts the finite reference, computes diagnostics and
band occupancy, and returns an immutable report. It neither requires
availability metadata nor creates a reusable profile. Empty and all-missing
inputs produce an `insufficient_reference` report rather than a fitting error.

### Fit

`fit_dynamic_binning` performs the same descriptive analysis, validates each
row's availability against the cutoff, and constructs the fixed profile.
The frame's source is `context.source`. A reference with no finite measurements
is rejected. A constant or limited-support reference is accepted with its
explicit status. Fit does not automatically filter rows after the cutoff;
their presence causes rejection.

### Classify

`classify_dynamic_binning` requires an equal context, explicit mode and valid
availability. It computes classifications in a separate frame and returns a
`BinningResult`. Inputs are not modified. An empty frame with the required
columns is valid and returns an empty result with the defined columns and types.
No previous application call contributes state to a later one.

## Input frame requirements

| Item | Requirement |
|---|---|
| Container | A `pandas.DataFrame`. |
| Columns | Unique column labels; must include `ts_ms` and the selected source. |
| Index | Unique and monotonically increasing according to pandas. It need not be a zero-based range or equal `ts_ms`. |
| `ts_ms` | Signed-int64-range integer values, strictly increasing and unique within a call. Booleans and floating-point timestamps, including `1.0`, are rejected. |
| Source | Real finite numeric values or supported missing values. Accepted numbers are converted to float64. |
| Missing source values | `None`, `pandas.NA`, and numeric NaN. Do not rely on arbitrary strings or timestamp-missing sentinels being treated as missing numeric data. |
| Invalid source values | Infinity, booleans, numeric strings, complex values and nonnumeric objects are rejected with source and row context. |
| `available_at_ms` | Required for fit/classify, with one signed-int64-range integer for every row, including rows with missing source values. |
| Availability relationship | Every availability value must be greater than or equal to that row's `ts_ms`. |
| Fit boundary | Every availability value must be less than or equal to `calibration_as_of_ms`. |
| Forward boundary | Every availability value must be strictly greater than `calibration_as_of_ms`. |
| Retrospective boundary | No additional comparison with the profile cutoff. |

The engine does not sort, deduplicate, resample, impute, check expected candle
spacing or confirm that integer timestamps really use milliseconds. Irregular
gaps are accepted. Availability is not required to increase across rows; observed
timestamps and the DataFrame index are checked independently. Cross-call order
and duplicate delivery are caller responsibilities.

Additional columns are not automatically analyzed. Use a separate context and
profile for each parameter. A parameter name such as `x_lab` is valid for the new
API because result columns are created separately from the input frame.

Rows remain aligned with the input index. Index preservation matters when
comparing chunked output with batch output: avoid resetting individual chunk
indices if the combined result must equal the original batch exactly.

## Context and policy

### VariationContext

`VariationContext` is an immutable identity model. Its fields all participate in
equality, and classification requires equality with `profile.context`.

| Field | Type | Meaning and validation |
|---|---|---|
| `source` | `str` | Nonempty input column name. |
| `market_id` | `MarketId` | Existing canonical Leonardo market identity. It must equal the result of canonicalizing its exchange, market type, symbol and timeframe. |
| `parameter_definition` | `str` | Nonempty complete definition, including formula settings and dependencies. The engine treats it as text and does not execute or semantically compare formulas. |
| `parameter_version` | `str` | Nonempty caller-supplied formula/version identifier. |
| `unit` | `str` | Nonempty unit convention, such as `percent`, `price`, `degrees` or a precisely defined derivative unit. No conversion is performed. |

Text identity is exact; semantically similar descriptions are not automatically
equivalent. Consistent sorted JSON text is one way to record resolved parameter
settings. The engine checks that strings contain non-whitespace content but
does not otherwise normalize their spelling.

`to_dict()` returns five keys. `market_id` becomes a mapping with exactly
`exchange`, `market_type`, `symbol`, and `timeframe`.
`VariationContext.from_dict()` requires these exact key sets and validates the
reconstructed canonical identity. Use
`leonardo.data.market_id.canonicalize_market_id` when creating contexts.

### BinningPolicy

| Constructor field | Default | Constraint |
|---|---|---|
| `cutoffs` | `(1.0, 5.0, 25.0, 75.0, 95.0, 99.0)` | Exactly six finite numeric values, strictly increasing and strictly inside (0, 100). Stored as a tuple of floats. |
| `min_reference_count` | `2000` | Positive integer within signed int64 range; booleans rejected. |

Seven band names remain fixed in order: `very_low`, `low`, `below_typical`,
`typical`, `above_typical`, `high`, `very_high`. Exact-cutoff ranks enter the
higher band.

`to_dict()` has exactly three keys: `cutoffs` as a list,
`min_reference_count`, and `tail_frequency_cutoffs: [0.01, 0.05]`. The last is
versioned policy metadata, not a configurable constructor field.
`from_dict()` rejects a different tail policy or missing/extra keys. Band cutoff
configuration does not alter the fixed tail-label thresholds.

## Analysis fields

`VariationAnalysis` is an immutable report returned by analysis and embedded in
each profile. Its full field set is:

| Field | Type | Meaning |
|---|---|---|
| `source` | `str` | Analyzed input column. |
| `measurement` | `str` | `value` or `magnitude`. |
| `row_count` | `int` | All supplied rows, including missing source rows. |
| `valid_count` | `int` | Finite measured observations; denominator `N`. |
| `missing_count` | `int` | Supplied rows excluded from the measured distribution. |
| `distinct_count` | `int` | Number of distinct measured float64 values. |
| `zero_count` | `int` | Original observations equal to zero. Negative zero is zero. |
| `positive_count` | `int` | Original observations greater than zero, including in magnitude mode. |
| `negative_count` | `int` | Original observations less than zero, including in magnitude mode. |
| `reference_start_ms` | `int` or `None` | First input `ts_ms`; `None` only for an empty frame. |
| `reference_end_ms` | `int` or `None` | Last input `ts_ms`; includes trailing missing measurements. |
| `minimum` | `float` or `None` | Smallest measured value. |
| `maximum` | `float` or `None` | Largest measured value. |
| `mean` | `float` or `None` | Frequency-weighted arithmetic mean of measured values. |
| `std` | `float` or `None` | Population standard deviation, `ddof=0`. |
| `median` | `float` or `None` | Linear 50% quantile. |
| `q1` | `float` or `None` | Linear 25% quantile. |
| `q3` | `float` or `None` | Linear 75% quantile. |
| `status` | `str` | `insufficient_reference`, `degenerate_reference`, `limited_support` or `ready`. |
| `band_counts` | Seven-element tuple of integers | Actual occupancy in band-index order; all zero for empty or constant references. |

When `valid_count=0`, all seven statistical values are `None`. An all-missing
but nonempty frame still has a timestamp span. For nonconstant references,
`sum(band_counts)=valid_count`; for constant references, it is zero because
bands are withheld.

Construction checks nonnegative integer counts, row-count and sign-count sums,
distinct-count bounds, seven valid occupancy counts, timestamp-span shape,
finite statistics, ordered quartiles, nonnegative standard deviation and
structurally compatible status. It cannot check an independently supplied
report against a distribution it does not contain, nor derive `ready` versus
`limited_support` without a policy. The containing profile performs those
additional checks.

`to_dict()` exports all 20 fields, converting `band_counts` to a list.
`from_dict()` requires exactly those fields. There is no separate analysis
schema-version field; profile conversion versions the enclosing representation.

## Profile fields and conversion

### DynamicBinningProfile

| Public field | Type | Meaning |
|---|---|---|
| `profile_id` | `str` | Nonempty caller-assigned identity. No automatic uniqueness service. |
| `context` | `VariationContext` | Exact parameter and market identity. |
| `measurement` | `str` | Fixed transformation used for calibration and application. |
| `policy` | `BinningPolicy` | Fixed band cutoffs and support threshold. |
| `calibration_as_of_ms` | `int` | Explicit availability cutoff, within signed int64 range. |
| `provenance` | Tuple of strings | At least one unique nonempty source identifier. A bare string is rejected. Accepted sequences are copied to a tuple. |
| `analysis` | `VariationAnalysis` | Calibration diagnostics, counts, span, occupancy and support. |
| `values` | Tuple of floats | Nonempty, strictly increasing, finite, distinct measured values. Magnitude values cannot be negative. |
| `counts` | Tuple of integers | One positive frequency per stored value. Their sum equals `analysis.valid_count`. |

Two private fields, `_ordered` and `_cumulative`, are read-only NumPy lookup
arrays. They are reconstructed from the public distribution and are not
serialized. The cumulative lookup includes a leading zero. Callers should not
access them as an API or modify them.

The profile is a frozen dataclass containing immutable public models and
tuples. There is no historical DataFrame, per-row observation sequence, fit
timestamp generated from the wall clock, automatic file path or database
connection attached to it.

### Serialized payload

`to_dict()` emits exactly these 11 top-level keys:

| Key | Representation |
|---|---|
| `schema_version` | Integer `1`. A boolean is not a valid version. |
| `algorithm_version` | String `empirical_midrank_v1`. |
| `profile_id` | String identity. |
| `context` | Context mapping described above. |
| `measurement` | `value` or `magnitude`. |
| `policy` | Policy mapping described above. |
| `calibration_as_of_ms` | Integer cutoff. |
| `provenance` | List of strings. |
| `analysis` | Analysis mapping described above. |
| `values` | List of finite floats. |
| `counts` | List of positive integers. |

The returned payload is detached. Changing its nested values, context, policy,
analysis or provenance does not mutate the profile. It can be passed to
`json.dumps(..., allow_nan=False)` without a custom encoder. Neither method
opens or writes files; storage is the caller's responsibility.

`from_dict()` requires exact keys at every modeled mapping level and rejects
unsupported versions. Restoring a payload runs the same profile validation as
direct construction. No migration or version fallback is performed.

### Distribution consistency checks

The profile checks all of the following against its stored distribution:

1. Value/count lengths match; values are finite, unique and increasing; counts
   are positive integers; a magnitude distribution has no negative value.
2. Count sum, distinct count, extrema, source and measurement agree with analysis.
3. Reference support status agrees with the distribution and policy. The analysis
   end timestamp cannot exceed the calibration cutoff.
4. Zero count agrees. Signed profiles also match both positive and negative
   counts; magnitude profiles retain only the recoverable zero/nonzero check.
5. Mean, population standard deviation and all three quartiles agree with
   recomputed statistics within their documented floating-point tolerances.
6. All seven band occupancies match the shared empirical-rank rule and policy.

For statistical comparisons, `math.isclose` uses relative tolerance `1e-12`.
Absolute tolerance is zero for standard deviation and quartiles. For the mean
it is `64 * numpy.finfo("float64").eps * max(abs(values))`. Extrema and integer
counts are exact comparisons.

The mean allowance is scaled to the largest observation; it accommodates
cancellation and is not a guarantee of accurate tiny residual means beside
extreme values. Quartiles avoid that absolute allowance specifically so tiny
nonzero quantiles cannot silently become zero.

These are consistency checks, not cryptographic verification. The profile has
no row-level data to verify its original signed split in magnitude mode, each
availability timestamp, or the truth of a provenance string. Retain source
selection and timing evidence outside the engine when reproducibility requires it.

## Classification result

### BinningResult object

`BinningResult` contains public metadata `profile_id`, `context`, `measurement`
and `mode`, plus private `_frame`. Construction takes a deep copy of the frame;
`to_frame()` returns another deep copy. Editing an exported frame does not
change the stored result or the profile.

Use results returned by `classify_dynamic_binning`. Direct construction of
`BinningResult` does not independently validate the full frame schema and is not
a profile-restoration pathway. It exposes no `to_dict`/`from_dict` pair.

### All result columns

The 25 columns are emitted in the following order. Capitalized `Float64` and
`Int64` mean pandas nullable extension types. Text uses pandas `string` and the
range flag uses nullable `boolean`. The two timestamp columns use NumPy `int64`.

| Column | Dtype | Meaning |
|---|---|---|
| `ts_ms` | `int64` | Input observation time. |
| `available_at_ms` | `int64` | Input availability time. |
| `source` | `string` | Profile context source. |
| `profile_id` | `string` | Profile applied to this row. |
| `measurement` | `string` | `value` or `magnitude`. |
| `mode` | `string` | Explicit `retrospective` or `forward`. |
| `support_status` | `string` | Profile analysis status, repeated even for missing/outside rows. |
| `raw_value` | `Float64` | Supplied signed numeric value, or missing. |
| `measured_value` | `Float64` | Raw value or its absolute value, or missing. |
| `direction` | `Int64` | Sign of raw value: -1, 0 or 1; missing for missing input. |
| `reference_count` | `Int64` | Finite calibration denominator `N`, repeated on every row. |
| `percentile` | `Float64` | Midpoint empirical position on 0–100 scale. |
| `tie_lower_percentile` | `Float64` | Strict lower position, `100*L/N`. |
| `tie_upper_percentile` | `Float64` | Inclusive lower position, `100*(L+E)/N`. |
| `lower_tail_frequency` | `Float64` | Fraction of reference at or below the measurement. |
| `upper_tail_frequency` | `Float64` | Fraction of reference at or above the measurement. |
| `lower_tail_count` | `Int64` | Inclusive lower numerator, `L+E`. |
| `upper_tail_count` | `Int64` | Inclusive upper numerator, `N-L`. |
| `bin_index` | `Int64` | Zero-based percentile band index, 0 through 6. |
| `band` | `string` | Corresponding fixed band name. |
| `lower_tail_label` | `string` | `very_rare`, `rare` or `common` when eligible; otherwise missing. |
| `upper_tail_label` | `string` | Same policy applied separately to the upper tail. |
| `range_position` | `string` | `below`, `inside`, `above`; for constant references `below`, `equal`, `above`. |
| `outside_reference_range` | `boolean` | Strictly outside the observed minimum/maximum; missing for missing input. |
| `status` | `string` | Per-row interpretation status. |

### Status precedence and missing fields

| Row condition | `status` | Available classification fields |
|---|---|---|
| Missing measurement, any profile | `missing_value` | Metadata, timestamps and reference count only; raw/measured value and all numerical classification/range fields are missing. |
| Finite measurement, constant reference | `degenerate_reference` | Raw/measured value, direction, range relation and flag; percentile, tail counts/frequencies/labels, index and band are missing. |
| Finite measurement outside nonconstant reference | `outside_reference_range` | Rank, tie interval, tails, index, outer band and range information; both labels are missing. |
| Finite in-range measurement, limited reference | `limited_support` | All numeric classification fields and band; both labels missing. |
| Finite in-range measurement, supported reference | `ready` | All classification fields, including both tail labels. |

`insufficient_reference` cannot appear as the support status of a successfully
fitted profile. Constant-reference handling takes precedence over an outside
status; its boolean range flag still identifies a novel value.

For JSON result export, first convert pandas missing values to Python `None`.
The examples demonstrate this. Unlike profile payloads, result frames are not
automatically JSON mappings. They also do not repeat the complete context and
policy on each row; retain those through the profile identity and result object.

## Validation and error handling

| Failure category | Typical exception and response |
|---|---|
| Non-DataFrame input | `TypeError`; supply the required frame. |
| Wrong analysis policy type | `TypeError`; construct a `BinningPolicy`. |
| Wrong fit context or classification profile type | `TypeError`; use the corresponding model. |
| Duplicate/unordered frame structure, bad timestamps or bad source cells | `ValueError`; correct the input before retrying. |
| Empty finite fit reference | `ValueError` containing `insufficient_reference`; choose a usable reference. |
| Fit rows after cutoff | `ValueError`; explicitly select eligible rows or a justified cutoff. |
| Forward rows at/before cutoff | `ValueError`; use eligible later rows or explicitly choose retrospective interpretation. |
| Context mismatch or invalid mode | `ValueError`; correct the identity/mode rather than relabeling incompatible data. |
| Inconsistent/unsupported profile payload | `ValueError`; retain the payload for diagnosis and use a valid supported reference. |

The examples are representative error categories, not a promise that every
arbitrary malformed Python object maps to one exception string. No operation
silently sorts, repairs a payload, recalibrates, substitutes a different profile
or publishes partial row classifications after an invalid request.

## Legacy calculator reference

The entry point `calculate_financial_tool("dynamic_binning", data, parameters)`
uses the earlier heuristic. It remains a nonvisual, analysis-only Financial Tool
with no signal-series output. Its parameters are owned by the existing
[Financial Tools specifications](../../src/leonardo/financial_tools/specifications.py).
These parameters do not configure the new profile API.

| Parameter | Default | Existing purpose |
|---|---|---|
| `source_columns` | `"close"` | Comma-separated selected source names. |
| `window` | `10` | Rolling window for estimating the movement floor; minimum 1. |
| `multiplier` | `1.0` | Multiplies the floor; specification minimum `1e-6`. |
| `floor_quantile` | `0.05` | Quantile of absolute changes or their rolling means; from 0 to 1. |
| `global_min_step` | `1e-12` | Fallback when the derived step is nonfinite or nonpositive. A final nonpositive step is rejected. |
| `quantile_method` | `"nearest"` | Floor/diagnostic quantile method: `nearest`, `lower`, `higher`, `midpoint`, `linear`. |
| `n_bins` | `15` | Number of labels per sign; minimum 1. |
| `boundary_eps` | `1e-12` | Absolute tolerance for scalar threshold comparisons; nonnegative. |

Its variation helper first drops missing observations from each selected series,
then takes successive differences. With at most `window` differences it takes
the requested quantile of absolute differences; with more it takes that quantile
of rolling means of absolute differences. It multiplies the result and uses
the configured fallback when needed. Consequently this legacy diagnostic can
measure a difference across a missing-row gap. The new analyzer never performs
that automatic differencing.

The legacy binner separates positive levels from absolute negative levels.
It creates quantile-based side edges with spacing adjustments, starts each side
at zero, and ends it at the observed maximum magnitude. If only one sign exists,
it mirrors that side's edges for the other sign. With no nonzero values, its
bin fitting raises the legacy "contains only zeros" error. There is no new
degenerate-profile result on this pathway.

Positive values receive `AB0` through `AB(n_bins-1)` and negative values receive
`BL0` through `BL(n_bins-1)`. Values considered near zero by the legacy tolerance
receive `AB0`. Missing values have missing labels. Extremes beyond a side's
thresholds use its last label. These labels have no equivalence contract with
the new seven percentile bands.

The calculator's analysis mapping retains exactly four top-level keys:

| Key | Contents |
|---|---|
| `steps` | Mapping from selected source to suggested step. |
| `variation_diagnostics` | Per-source difference statistics and floor evidence. |
| `binning_artifact` | `n_bins`, `boundary_eps`, and `series`; each source has `min_step`, positive/negative `side_edges`, `label_thresholds`, and `side_sources` indicating fit or mirrored. |
| `labeled_rows` | Input index reset into row records, selected source values, and each `<source>_lab` label. |

Each variation diagnostic contains `series`, `count`, `mean`, `std`, `min`,
`max`, `abs_mean`, `abs_median`, `pctile_95`, `pctile_99`, `abs_pctile_95`,
`abs_pctile_99`, `floor_quantile`, `floor_mean`, and `suggest_step`.
Its `std` is the sample standard deviation of differences (`ddof=1`), unlike
the new population standard deviation of supplied measured levels.

The accepted compatibility guards reject infinity in selected source data and
source selections whose generated label names collide, such as selecting both
`x` and `x_lab`. These guards do not migrate saved analyses or adopt the new
profile algorithm. Keep existing calculator results identified as legacy when
comparing them with newly generated profile classifications.

## Source and test map

| Subject | Source or accepted test |
|---|---|
| Public signatures | [variation.py](../../src/leonardo/financial_tools/variation.py) |
| Models, rank, statistics, conversion | [variation_models.py](../../src/leonardo/financial_tools/variation_models.py) |
| Frame preparation and report construction | [variation_analysis.py](../../src/leonardo/financial_tools/_calculation/variation_analysis.py) |
| Profile application and legacy behavior | [dynamic_binning.py](../../src/leonardo/financial_tools/_calculation/dynamic_binning.py) |
| Context market identity | [market_id.py](../../src/leonardo/data/market_id.py) |
| EMA calculation | [indicators.py](../../src/leonardo/financial_tools/_calculation/indicators.py) and [common.py](../../src/leonardo/financial_tools/_calculation/common.py) |
| Delta, derivative and angle calculation | [constructs.py](../../src/leonardo/financial_tools/_calculation/constructs.py) |
| Statistics, invalid frames, missing/constant cases, extreme quartiles | [test_variation_analysis.py](../../tests/financial_tools_test/test_variation_analysis.py) |
| Ties, cutoffs, support, contexts, payloads, immutable state, mixed scales | [test_dynamic_binning_profiles.py](../../tests/financial_tools_test/test_dynamic_binning_profiles.py) |
| Batch/chunk/single replay, future append, warm-up, delayed availability | [test_dynamic_binning_replay.py](../../tests/financial_tools_test/test_dynamic_binning_replay.py) |
| Architectural restrictions and exports | [test_financial_tools_architecture.py](../../tests/financial_tools_test/test_financial_tools_architecture.py) |
| Legacy calculator guards | [test_financial_tool_construct_calculations.py](../../tests/financial_tools_test/test_financial_tool_construct_calculations.py) |
| Existing calculator contracts | [test_financial_tool_calculation_contract.py](../../tests/financial_tools_test/test_financial_tool_calculation_contract.py) |

Calibration prepares an ordered distribution; classification uses searches over
its distinct values and cumulative frequencies. Lookup storage grows with the
number of distinct values, not a fixed seven-bin approximation. Application
creates a result frame proportional to the supplied row count. No fixed latency
or throughput guarantee is part of this API.
