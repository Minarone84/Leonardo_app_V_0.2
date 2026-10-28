# UTC episode measurements

Updated: 2026-10-15. Metrics schema `1.0`; measurement rule `utc-episode-metrics-1`.

UTC now adds nonvisual measurements to the UP and DOWN episodes its existing
scanner identifies. Detection, formation families, restart/reversal decisions,
range rules and all 27 plotted outputs retain their existing behavior. This
layer describes an existing episode; it cannot create, prolong or terminate one.

The wider Data Analysis Suite remains incomplete and may change substantially.
These stored facts are available to backend readers and the optional context and
outcome filters in [Trend Start Patterns](TREND_START_PATTERNS.md). The consumer
does not change UTC arithmetic, detection or plotting. Pattern predictors,
multi-timeframe analysis and live feed execution remain separate work.
Ranges remain distinct context; range episode families and
full range lifecycle measurements are outside this version.

## 1. Two reports, separate responsibilities

`result.analysis["utc_classification"]` remains the original schema 1.0 report.
Its formations, IDs, origins, confirmation times and continuation records are
unchanged. `result.analysis["utc_episode_metrics"]` is a separately versioned
sibling. Evolving duration or pullback depth is never added to a frozen formation
dictionary in the original report.

The new report includes:

| Field | Meaning |
|---|---|
| `schema_version`, `measurement_rule_version` | Serialized shape and measurement convention. |
| `classification_sha256` | SHA-256 of the complete original classification, encoded as UTF-8 JSON with sorted keys, compact separators, preserved Unicode and nonfinite numbers rejected. |
| `input_key`, `parameters`, `timestamps_ms`, `identity_scope` | Bindings copied from that classification. |
| `observation_mode`, `as_of_ms` | Retrospective calculation or explicit available-prefix replay. |
| `observation_limit` | Last source row in this report, or null for an empty replay. Individual ended episodes have earlier limits. |
| `evidence` | Detached segment/swing witnesses and per-row high, low and published UP/DOWN/RANGE booleans. Row positions use the bound timeline. These support arithmetic validation on load. |
| `episodes` | Formation measurements, current episode measurements, preceding context and individual pullbacks for each classified episode. |
| `context_at_cutoff` | Available-prefix context for explicit as-of results; null in an ordinary historical result. |

Retained evidence is a report snapshot, not another owner of market data. Its
source authority remains the input revision and dependency provenance. Semantic
validation rejects contradictions and inconsistent arithmetic; a checksum alone
does not prove that a self-consistently altered source witness is authentic.

## 2. Coordinates and completeness

Every pivot carries its original P/T kind, row position, timestamp, value and
availability. Timestamps are integer UTC milliseconds. No interpolated pivot or
assumed intrabar order is introduced.

| Symbol | Definition |
|---|---|
| S | First pivot of the retained, accepted formation. |
| F | Last pivot of that first activating formation. |
| E | Current scanner-retained endpoint. Initially F; later taken from continuation state. On termination it is `before.endpoint`, never the new reversed episode's `after.endpoint`. |
| O | End of the valid source segment for an open/interrupted episode, or the terminating decision frontier for an ended one, within the supplied replay prefix. |
| Q | Termination's trigger pivot. |
| D | Termination decision frontier. A rewind can make D later than Q. |
| K | Verified termination known-at time, or null. |
| d | +1 for UP; -1 for DOWN. |

Formation measurements cover S through F. Structural measurements cover S
through E. Observed progress covers S through O. These intervals can differ.

An endpoint is not necessarily the greatest favorable extreme. For the accepted
UP sequence `T100 P110 P115 P112`, E is P112 while the favorable extreme is P115.
Movement to E is +12 points; favorable excursion is 15 points.

`episode_metrics.observed_structural` describes the retained structure in every
status. `final_structural` is populated only for an existing scanner termination
(`ended`). It remains null for `open` and `interrupted`. A plotted end at the
history tail does not turn an open episode into a completed outcome.

## 3. Movement and price span

The following fields appear in `formation_metrics.movement` for X=F and
`episode_metrics.observed_structural.movement` for X=E:

| Field | Exact arithmetic |
|---|---|
| `signed_move_points` | X.value - S.value. |
| `directional_move_points` | d times signed movement; positive means movement in the episode direction. Negative results are not clamped. |
| `signed_move_pct` | 100 times (X.value / S.value - 1). Requires S.value > 0. |
| `directional_move_pct` | d times signed percentage. |
| `pivot_high`, `pivot_low` | Original pivot references at the maximum/minimum eligible directional P/T price within S..X, inclusive. Earliest exact ties win. |
| `pivot_span_points`, `pivot_span_pct` | High minus low; percentage is 100 times that span / S.value. |
| `pivot_favorable_points` | UP: max(0, high-S). DOWN: max(0, S-low). |
| `pivot_adverse_points` | UP: max(0, S-low). DOWN: max(0, high-S). |
| `pivot_favorable_pct`, `pivot_adverse_pct` | 100 times the corresponding points measurement / S.value. |
| `bar_envelope_high`, `bar_envelope_low` | Highest supplied high and lowest supplied low across stored rows S..X, including both endpoints. Each retains source column, row, timestamp and value. Earliest ties win. |
| `bar_envelope_span_points`, `bar_envelope_span_pct` | Candle envelope width and 100 times width / S.value. |

The candle envelope describes whole included candles. It does not prove whether
a high occurred after the starting low within the same candle. Pivot extrema
and candle extrema therefore have different fields.

Points remain usable when percentage references are zero or negative.
`percentage_reason="nonpositive_reference_price"` explains missing percentages.
Optional arithmetic that overflows is null and is listed under
`unavailable_measurements` with reason `nonfinite_result`; it must not reject a
previously accepted detector input. No new rounding, tolerance or clipping is
applied. Invalid retained evidence still fails validation.

## 4. Durations, rows and availability

Duration objects contain `bars` and `ms`. Bars are the difference between stored
row positions, while milliseconds are the difference between actual timestamps.
Inclusive row count is bar intervals plus one. We never replace actual time
differences with an assumed timeframe multiplier.

| Path | Endpoints |
|---|---|
| `formation_metrics.duration` | S to F. |
| `formation_metrics.confirmation_delay_ms` | Existing confirmed_at_ms minus S.ts_ms; null if unknown. |
| `episode_metrics.observed_structural.duration` | S to E. |
| `episode_metrics.endpoint_extension` | F to E; this is structural extent after F, not elapsed time after confirmation became known. |
| `episode_metrics.observed_elapsed` | S to O. |
| `episode_metrics.termination_frontier_delay_ms` | D minus E.ts_ms. |
| `episode_metrics.termination_recognition_delay_ms` | K minus E.ts_ms; null if K is unknown. |

The termination trigger pivot, frontier and known-at time are separately stored.
Each row interval retains its own spacing summary beside its duration. These
summaries contain `row_count`, `min_delta_ms`, `max_delta_ms` and `uniform`:

| Spacing path | Interval |
|---|---|
| `formation_metrics.movement.spacing` | S to F. |
| `episode_metrics.observed_structural.movement.spacing` | S to E; also retained in `final_structural` when ended. |
| `episode_metrics.endpoint_extension_spacing` | F to E. |
| `episode_metrics.observation_spacing` | S to O. |
| Each pullback's `descent_spacing` | Launch to worst. |
| Each pullback's `recovery_spacing` | Worst to recovery; null before recovery. |
| Each pullback's `total_spacing` | Launch to recovery; null before recovery. |
| Each pullback's `observed_spacing` | Launch to observation limit while unresolved; null after recovery. Formation snapshots use F as their limit. |

For example, a descent spanning two stored row intervals with adjacent gaps of
60,000 and 3,660,000 ms has `row_count=3`, `min_delta_ms=60000`,
`max_delta_ms=3660000` and `uniform=false`. Its existing duration remains
`bars=2, ms=3720000`. A one-row interval, such as F=E, has `row_count=1` and
null minimum, maximum and uniformity. An unavailable interval has a null
spacing summary, distinct from a present interval containing only one row.
UTC has no authoritative expected spacing here, so these fields do not invent
a missing-bar count. Enriched reports must retain these summaries; missing or
altered values fail semantic validation.

Availability is distinct from pivot time. Formation measurements include the
original `confirmed_at_ms`, including any later restart/frontier evidence.
Movement records retain `pivot_available_at_ms`, `bar_envelope_available_at_ms`
and their combined `available_at_ms`; candle envelopes also require verified
bar close times. Episode summary availability additionally covers the observed
limit and its required evidence. Any unknown required availability propagates
to null. Historical facts with unknown availability cannot establish a live
prediction time.

## 5. Preceding context

`preceding_context` records three different questions:

1. **How did UTC reach this formation?** `origin` and
   `scanner_predecessor_episode_id` preserve existing scanner lineage.
2. **Which confirmed episode came before it in scanner activation order?**
   `previous_confirmed_episode_id`, `previous_direction` and
   `previous_formation_key` answer this within the same valid segment. That
   episode need not already have been known before S.
3. **What does the historical result publish immediately before S?**
   `preceding_bar` and `preceding_membership` copy the preceding stored row.
   At a segment start they are unavailable; context never bridges invalid data.

UP, DOWN and RANGE remain separate booleans. Existing UTC can publish both a
directional and range membership at a row. Preserve that overlap. All false
means no classified membership, not RANGE. The configuration includes the
directional/range windows and the selected directional P/T columns.

These preceding-row memberships are explicitly retrospective, with no invented
known-at time. To ask what was available before an event, replay at an earlier
cutoff. Do not select a backfilled historical flag and call it causal.

## 6. Internal pullbacks

One pullback means one unrecovered countertrend excursion at the parent's
existing **directional** P/T resolution. If directional n=5 and range n=3, this
measurement uses n=5. It neither substitutes range pivots nor counts every
countertrend candle. Classifying complete smaller trends would require a
separately configured finer UTC stream in later work.

Start with S as the favorable watermark. A strictly more favorable pivot moves
the watermark; equal values retain the earliest one. The first adverse pivot
opens an excursion at that watermark. Track the worst price, retaining the
earliest worst tie. A partial recovery followed by another adverse leg stays in
the same excursion. The first eligible pivot reaching or passing the launch
price in the parent direction recovers it; equality is sufficient. That
recovery pivot becomes the new watermark.

All actual eligible pivot kinds are preserved, including repeated P or T.
P115 followed by P112 can describe an adverse movement without inventing an
intervening trough. Ambiguous simultaneous P/T rows skipped by the detector
remain skipped, and scanner rewinds never duplicate a source pivot.

| Pullback field | Definition |
|---|---|
| `launch`, `first_adverse`, `worst`, `recovery` | Original pivot references; recovery is null while unresolved. |
| `depth_points` | d times (launch.value - worst.value). |
| `depth_pct` | 100 times depth / launch.value, only for a positive launch reference. |
| `retracement_of_prior_gain_pct` | 100 times depth / (d times (launch.value-S.value)), only for a positive finite denominator. Values above 100 are not clipped. |
| `descent_duration` | Launch to worst, including for DOWN's upward countertrend excursion. |
| `recovery_duration`, `total_duration` | Worst to recovery and launch to recovery; null until recovered. |
| `observed_duration` | Launch to O for unresolved excursions; null for recovered ones. Formation snapshots use F instead of O. |
| `adverse_leg_count` | Count of strictly adverse adjacent pivot transitions inside the excursion. Equal transitions add zero. |
| `status` | `recovered`, `pending`, `ended_unrecovered` or `interrupted`. |
| `opened_at_ms`, `worst_known_at_ms`, `recovered_at_ms` | Required pivot/scanner evidence availability; unknown propagates. Recovery known-at is null before recovery. |
| `pivot_extent_end` | Recovery pivot, or latest inspected pivot while unresolved. It does not advance merely because new no-pivot bars arrive. |

Phase is `formation` when the observed pivot extent ends at/before F;
`continuation` when it extends after F and launches at/after F; otherwise
`crosses_formation_boundary`. A launch exactly at F belongs to continuation.

Interval membership is `inside_structural` when the observed pivot extent ends
at/before E; `crosses_endpoint` when it extends after E but launches at/before E;
otherwise `after_endpoint`. `launch_inside_structural` is retained separately.
These are evidence-location fields, not a claim that an unresolved movement has
finished. Advancing O alone changes pending duration, not pivot extent or phase.

A recovered internal pullback must have both launch and recovery within S..E.
The final breaking movement cannot recover using prices beyond the parent's
termination frontier. Its later prices belong to another observation/episode.

## 7. Formation freeze, identity and aggregates

`formation_metrics` uses S..F plus the fixed original confirmation evidence.
It does not contain current episode status, growing O or later recovery dates.
Appending unchanged history therefore cannot change its measurement facts.
Revised historical prices or availability constitute a source revision.

The current `pullbacks` list describes progress through O. An excursion launched
before F and recovered after F keeps one ID and crosses the boundary. Its
formation snapshot remains pending-at-F. IDs derive from parent episode,
measurement rule and launch identity. Persistent IDs across append require UTC's
existing stable stream identity. `input_local` IDs can change with the input;
the existing classification identity rules are not replaced.

`pullback_summary` names these cohorts: `all_observed`, `internal_recovered`,
`formation_recovered`, `formation_pending_at_boundary`, `continuation_started`,
`recovered_during_continuation`, `currently_pending`, `pending_internal_launch`,
`endpoint_context`, `ended_unrecovered` and `interrupted`. The pending-at-boundary
cohort always comes from the frozen formation snapshot. Other cohorts filter
the observed current records. Cohorts can overlap and must not be summed as
disjoint categories.

Each cohort has member count; mean/maximum depth in points and percent; and
mean/maximum completed duration in bars and milliseconds. Every statistic has
its own `eligible_count`. Missing percentages do not remove valid points from
their own statistics. Means are unweighted. Empty eligible cohorts have count
zero and null mean/maximum. Pending elapsed time is never averaged with completed
recovery duration.

## 8. Worked examples

`T100 P110 T105 P115 T108 P116` activates UP at P115. Formation contains the
110-to-105-to-115 excursion: depth5, 4.54545% of launch and 50% of prior gain.
Continuation contains 115-to-108-to-116: depth7, 6.08696% of launch and 46.66667%
of prior gain. The second recovery does not alter formation counts.

For an already active UP, `P120 T115 P118 P117 P121` describes one excursion:
depth5, two adverse adjacent legs, recovery at P121. The repeated P is retained.
By contrast, a lower second trough in `P120 T115 P118 T112 P121` can activate
DOWN under the existing UTC rules. Then the old UP observation stops at its
termination frontier, and P121 cannot recover that old pullback. Arithmetic
examples never override detector ownership.

## 9. Reading and replay API

```python
from leonardo.financial_tools import get_utc_episode_metrics, measure_utc_as_of

metrics = get_utc_episode_metrics(utc_result)
if metrics is not None:
    episodes = metrics.to_episode_frame()
    pullbacks = metrics.to_pullback_frame()

available = measure_utc_as_of(
    data, utc_parameters, context=verified_context, as_of_ms=cutoff_ms
)
context_now = available.context_at_cutoff
```

The accessor returns None for legacy empty analysis and V1-only classification.
It does not calculate missing metrics. `UtcEpisodeMetricsResult.from_dict`
requires the bound `classification=` report. Dictionary, episode and table views
are detached, including nested cells.

Explicit replay uses the existing closed-prefix preparation, directional swing
availability and separate range-window masking. `classify_utc_as_of` retains its
existing signature/result. The metrics replay binds the final as-of
classification, not an intermediate retrospective report.

Loading an as-of report applies the same cutoff requirement to every retained
directional swing, including swings outside the classified formation and
continuation records. Its availability must be known and no later than
`as_of_ms`; equality is accepted. Unknown or future availability is rejected
even if all derived measurements and content hashes have been recomputed.
Historical reports may still retain unknown swing availability, which propagates
to the corresponding known-at measurements instead of claiming causal use.

`context_at_cutoff` contains the last available row and its published membership,
plus confirmed directional episodes still open in that prefix. These are
separate facts: a plotted directional interval need not extend through every
current row. Empty prefixes have no last row or membership and an empty episode
list. A caller can request the cutoff before S to investigate preceding causal
context. Ordinary historical calculation does not batch-replay each anchor.

## 10. Artifacts, databases and validation

Artifacts carry the complete analysis mapping in `analysis.json`. New enrichment
changes the analysis hash and therefore physical Artifact ID, even with identical
numeric values. Recipe/logical identity remains unchanged for the same
configuration/dependencies. Existing objects are not rewritten or migrated.

Database V6 keeps its existing `utc_classification.json` envelope and copies
provider-specific reports. Append preserves old provider bytes and associates
the suffix with its new provider. It does not merge evolving totals across
physical snapshots. Removing a selected provider removes only its owned
associations/report when no references remain. Reading retained V1-only evidence
does not fetch current source Artifacts to fill missing measurements.

`AnalysisService.load_utc_classification(reference)` returns the pinned bundle.
Its existing `report(artifact_id)` reads core classification;
`metrics(artifact_id)` reads enrichment or returns None for an associated legacy
provider. Missing providers raise KeyError. Always inspect `associations_frame()`:
a full copied provider report may extend beyond rows imported into this database.
Its presence does not establish complete outcome coverage in the selected data.

Trend Start Patterns resolves one coherent copied projection before using active
filters. Completed mode requires an ended final structural outcome; formation
uses the frozen activation snapshot; observed mode retains the saved observation
limit and incomplete status. A context-only filter does not require completion.
It checks the required source-row slices against pinned data and logical provider
coverage, including terminal/recognition ownership. An appended suffix may borrow
unchanged prefix formation only with compatible immutable history and supported
later confirmation. Conflicting outcomes, missing required middle rows or
unverifiable prefixes cannot be repaired by choosing a newer provider.

The consumer keeps missing enrichment distinct from a valid no-predecessor value,
an empty cohort and partial aggregate support. Disabled filters preserve the old
classification-only workflow. These filters select retrospective event populations;
they do not establish that memberships or completed outcomes were known at the
starting swing. No provider report, database or UTC measurement is rewritten.

Validation checks the core report first, then metrics versions/binding, original
pivot/restart witnesses, segment bounds, timestamps, arithmetic, phases, states,
cohorts and availability. Calculation results also cross-check membership
witnesses against the unchanged numeric output. Corrupt metrics cannot fall back
to legacy. Updated readers accept old data; older binaries are not promised to
accept the new sibling section. Research retains strict stored-analysis equality.
