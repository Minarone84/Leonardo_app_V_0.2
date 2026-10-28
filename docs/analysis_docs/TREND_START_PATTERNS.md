# Trend Start Patterns

**Status:** Implemented retrospective DAS workflow through accepted GR-06 and
tooltip code/package correction; final integrated validation and native acceptance
remain subsequent GR-07 work.
**Updated:** 2026-10-21

The wider Data Analysis Suite is incomplete and may change substantially.
This first event-study workflow describes historical associations. It does not
create trading signals, train a predictor, evaluate profitability or establish
that a discovered pattern will recur out of sample.

Two modes are available. **Existing patterns** preserves the original single
labels, sequences ending at the event and pairs on the event bar. **Pre-event
combinations** searches multiple columns and multiple bars strictly before the
start, with optional neighboring-bin tolerance. Section 12 defines the new mode;
the original mining/comparison/ranking rules in sections 7–8 apply to Existing
patterns. UTC detection, plotted outputs and the completed binning run are unchanged.

After pre-event discovery, the separate pinned **Pinned refinement**
workspace evaluates the same rules, keeps session History and explains counts
through the combination inspector. Section 13 links its complete reference.
The legacy/simple contracts below remain supported; they do not restrict the
new granular editor to a single measurement basis or require re-mining on Evaluate.

## 1. The question and its inputs

UTC identifies a trend-start event and its exact formation family. The existing
Variation & Binning output describes what each selected construct was doing
around that event. The study asks: **which observed label combinations recur
around this kind of start, and how common are they in a specified comparison?**

All inputs belong to one pinned database revision. DAS reuses one completed
binning run with independently fitted profiles. A study selects one logical UTC
instance and a subset of the already analyzed columns. Shared binning settings
never imply a shared distribution: changing the event selection cannot change
any profile, numerical boundary, observation label or sign.

| Selection | Meaning |
|---|---|
| Trough (T) | Starting trough of an UP episode; role `up_start`, anchor T0 |
| Peak (P) | Starting peak of a DOWN episode; role `down_start`, anchor P0 |
| Trend start | Fixed event role in this release |
| One exact family | Target population for pattern comparisons |
| All families | Original selector: separate family counts/frequencies, no combined target score. Explicit pre-event selected/all-compatible pooled scopes are separate choices (section 13). |
| Origin | All, or an explicit UTC origin filter |

An uptrend can start while a delta has a negative label. A downtrend can start
with a positive label. The study neither flips nor filters construct signs.
**Peak P** names a swing; **P09** is a positive construct bin. They are different
concepts. Binning labels are reused exactly as supplied; they are not renamed
to AB/BL or forced into a zero-centered system.

## 2. GUI workflow

1. Select a saved database and complete **Variation & Binning**. The workspace
   may list several databases; the completed run uses exactly one revision.
2. Open **Trend Start Patterns**. Its source text identifies the inherited
   database and revision. The tooltip includes full IDs, values hash and binning
   run identity. Each selectable column lists its measurement mode and profile.
3. Choose **Load UTC event catalogue**. This reads the copied database sidecar,
   not live Artifacts. Explicitly choose one UTC instance. Aliases, window,
   providers, rule/configuration, coverage and legacy intervals are inspectable.
4. Choose P or T. Then choose an exact compatible family, or All families.
   Family choices show eligible counts; their tooltips include an example
   sequence, exact ranks in the key, origin breakdown and timing counts.
5. Select 1–8 analyzed columns. Set inclusive **anchor dates**, before/after
   stored bars, comparison, sequence lengths and support thresholds.
6. Optionally expand **Refine selected starts** to use saved UTC preceding
   context, movement, duration or internal pullbacks. All groups start off.
   Choose one measurement basis in these simple discovery controls; see §11.
   Pinned granular refinements later support per-condition bases and ALL/ANY.
7. Review the context and choose **Analyze selected events**. Scroll below the
   settings for results. Workspace splitters and table scrollbars remain usable.
8. In Patterns, select a row and inspect its matching starts or comparison
   matches. Select an occurrence to see actual observations and copied UTC
   evidence. **Show all selected events** restores the complete target list.

An event kind is initially unselected. Changing kind or UTC instance clears the
family choice. Changing origin or date filters updates counts but retains a
previously selected exact family even if it now has zero matching starts. It
never substitutes another family. Changing original discovery settings clears
that study output without discarding the completed binning run. Editing an
unsaved pinned-refinement draft instead preserves its completed checkpoint;
see section 13 for Evaluate, History and explicit new-search behavior.

| Control | Default and limits |
|---|---|
| Anchor dates | Entire pinned database; inclusive first/last milliseconds |
| Before / after | 20 / 20 stored bars; each independently 0–100 |
| Columns | Explicit selection; 1–8 unique columns from the parent run |
| Sequence lengths | 2 and 3; any subset of 1–5 that fits `before + 1` |
| Comparison | Other families of the same start event |
| Minimum target sample | 20 verified-timing, ready-reference assessable events |
| Minimum comparison | 20 verified-timing, ready-reference assessable observations |
| Minimum matches | 5 verified-timing, ready-reference target matches |

Thresholds are positive integers and are separate from the binning profile's
reference-support policy. Reducing them shows more candidates; it does not make
a small sample statistically reliable. Oversized column selections disable the
run with an explanation. Impossible sequence lengths are unchecked when the
lookback is shortened.

Dates use Leonardo's display-time preference while retaining integer UTC
milliseconds internally. Changing display timezone preserves the request and
results. A date span filters event anchors; windows can extend beyond it inside
the same database. Profiles retain the original full-history calibration span.

## 3. Exact event and family identity

The anchor is precisely `episode.formation[0].ts_ms`, after any UTC anchor
reselection. It is not a newly found minimum/maximum, the first pullback or the
confirming pivot. One event is one selected starting relationship of a confirmed
UTC episode. Open, ended and interrupted episodes can supply valid starts.
Unconfirmed candidates are not invented as classified events.

Examples of distinct families are `UP/TPTP/0,2,1,3` and
`UP/TPTP/0,1,0,2`. The complete P/T word and exact price ranks are authoritative.
The second key retains equal starting/intermediate trough prices. Long words,
repeated P/T events and tied prices are not shortened or clustered into a fixed
Type 1/2/3 taxonomy. The DOWN counterpart has its own actual sequence and ranks.

Optional origins are `initial_candidate`, `candidate_restart`,
`post_break_restart`, `direct_reversal`, and `unknown` if supplied. Origins are
independent of formation family. A reversal's shared pivot may end a prior trend
and start the selected one: it is counted once for its selected starting role,
with the predecessor and shared pivot retained in evidence.

Generic peaks/troughs, first pullbacks, supporting swings, endpoints and trend
termination events are outside this release. Not every P/T starts or ends a
trend. Range flags can coexist with directional episodes and do not silently
remove them. Formation and continuation stay separate; continuation extensions
or replacements neither change the frozen family nor add another start.

## 4. Copied evidence, coverage and reconciliation

The database reference binds database ID, revision ID and values SHA-256. The
validated store loads that exact snapshot. Analysis additionally verifies that
every parent observation axis agrees exactly with the database. Removed or
corrupt revisions fail instead of falling back to the current head.

The catalogue groups copied associations by logical UTC instance. Different
parameters or rule versions within that instance cause an explicit conflict.
Aliases of one physical report count as one provider; all alias references stay
visible. Multiple physical versions can contribute different saved intervals.

Eligibility is evaluated against those intervals:

1. Only associations with actual classification reports establish coverage.
   Empty legacy reports remain visible as unavailable metadata.
2. Every referenced formation/restart swing and the decision frontier must exist
   exactly in the database and within the instance's classification coverage.
3. For known confirmation/close timing, find the first actual report row whose
   verified close is at or after `confirmed_at_ms`. That recognition row must
   be in the database and within an association of the carrying provider.
4. For unknown timing, use the structural decision-frontier row for coverage
   only, mark `structural_coverage_only`, and keep unknown times unknown. Retain
   these starts descriptively; they supply no ranking support in either cohort.
5. Reconcile witnesses by logical instance, rule/configuration, segment,
   direction and retained anchor. Frozen formation, origin, restart and timing
   facts must agree. Input-local episode IDs may differ; all are retained.
6. Conflicting frozen facts fail. There is no arbitrary report-order or latest
   wins rule. Evolving episode status and continuation stay with their original
   witnesses and are excluded from the frozen-fact comparison.

An appended provider can confirm an earlier anchor using prior covered pivots.
It cannot borrow a recognition row from a provider which did not carry that
episode. Repeated witnesses never multiply the event count. Context outside the
saved selection remains an excluded event with its reason. The catalogue reports
inspected episodes, duplicates, unique starts, usable/excluded counts and timing.

A completely missing sidecar disables study execution. An available sidecar
with legacy intervals is not complete coverage. No live Artifact lookup repairs
either case; any persistent import/update remains an explicit Data Manager task.

## 5. Time fields and alignment

| Field | Meaning |
|---|---|
| `anchor_ts_ms` | Retained starting swing, displayed as T0 or P0 |
| `starting_available_at_ms` | When that swing was observable as a P/T event, if known |
| `confirming_pivot_ms` | Structural last swing of the frozen formation |
| `confirmed_at_ms` | Availability of all evidence required for first activation |
| `decision_frontier_ms` | Latest pivot consumed, including later restart triggers |
| `confirmation_delay_ms` | Known confirmation time minus starting pivot time |
| `confirmation_delay_bars` | Difference in actual stored row positions from anchor to recognition |

Each observation joins by exact `ts_ms`. Offset -1 means the previous stored
row, +1 the next stored row, and 0 the actual anchor. There is no nearest-time
join, forward fill, interpolation, resampling or synthetic candle. Event details
retain each row's elapsed milliseconds as well as its stored-bar offset.

Fixed timeframe gaps, calendar-month discontinuities, known UTC segment starts
and classification coverage boundaries are marked. Monthly intervals use the
existing OHLCV calendar rule. Label frequencies may show accessible values
across a discontinuity with explicit flags. Pattern conditions require a
continuous covered path from the anchor to every required offset. Sequence and
pair rankings therefore cannot silently bridge such boundaries.

Near a database edge, missing window slots remain `outside_history`. An event
with one missing construct does not disappear from other constructs' counts.
The event-window table is generated only for the selected occurrence, avoiding
an eager copy of all windows.

## 6. Labels, support and denominators

Directional profiles supply `bin_label`; combined-reference value/magnitude
profiles supply `band`. An observation with `status=zero_value` is represented
as the explicit token `Zero`. NaN and unavailable labels are not zero. Original
raw values, direction, intensity, rarity, support and status fields remain
available in the event-window table.

Limited-reference labels can appear descriptively. Ranking counts require both
verified confirmation timing and ready-reference labels (or the explicit valid
zero state). Structural-only events remain in descriptive frequencies, pattern
counts, windows and witness details, but never enter ranking denominators,
matches or ratios. Mixed cohorts rank using only their qualifying subset.
Degenerate or
unavailable rows are not turned into artificial informative bins. A one-sign
construct keeps its own labels and absent-side status. All-missing columns keep
their missing rows and have no fitted profile.

For each frequency-grid cell, the denominator is the number of selected events
with an available label for that column and offset. Missing slots/values are
reported separately. Counts sum within each family/column/offset; each column
has its own denominator. Grid tooltips show counts, unavailable rows, gap flags
and observation-status counts. Color shows frequency, not profit or direction.

For each pattern template, assessability depends only on its required terms.
If a slope is missing, `delta[0] = N09` can still be assessed, while a condition
requiring both delta and slope cannot. Each event contributes once at its fixed
offsets. Ready-reference assessability and matched counts are recorded
separately from descriptive assessability and matches.

Pattern fields `ready_matched`, `ready_assessable` and their `comparison_`
counterparts are ranking-support counts: both timing and label-reference
requirements apply. `timing_withheld` and `comparison_timing_withheld` count
descriptively assessable observations lacking verified timing, regardless of
their label support. They are not the full difference between descriptive and
ranking counts, because limited reference support can also withhold ranking.
Diagnostics reports each cohort's starts withheld for timing. When timing
withholding leaves a ranking denominator empty, the reason is
`unverified_confirmation_timing`; otherwise the existing comparison and support
threshold reasons apply. Matching lists retain all descriptive matches and show
`ready_reference`, `verified_timing` and their conjunction `ranking_support`.

## 7. Pattern definitions and comparison

The engine counts observed target combinations, without enumerating every
theoretical bin combination:

| Kind | Required terms |
|---|---|
| Label | One selected column at one offset in the requested window |
| Sequence | One column, chosen length 1–5, ending at offset 0 |
| Pair | Two distinct selected columns, both at offset 0 |

Sequences do not search arbitrary offsets in this release. Positive-offset
single-label conditions describe aftermath and remain retrospective. Each
pattern retains its exact column/offset/label terms and deterministic ID.

**Other families of the same start event** compares a selected UP family with
other UP-start troughs, or a selected DOWN family with other DOWN-start peaks.
The same origin and anchor-date filters apply. P and T populations are never
mixed in that comparison.

**Non-start timestamps** uses every remaining eligible stored timestamp in the
same inclusive study dates. Each ordinary anchor requires known classification/
confirmation coverage. A control is excluded whenever its requested window
intersects the requested window around any eligible confirmed UP **or DOWN**
start in the instance, irrespective of the selected family, origin or direction.
With `b` before and `a` after, an event at row `e` excludes control anchors in
`[e-b-a, e+a+b]`, clipped to history. There is no random sampling.

After this neighborhood exclusion, assessability is evaluated separately for
each condition. Only the paths from the anchor to its required offsets must be
present, continuous and inside known control metadata coverage. All required
labels must be available. An unused offset beyond history, across a gap or in
unavailable coverage does not discard the anchor. A condition using that offset
does exclude it. Sequences require their full anchor-to-term paths; pairs at
offset zero require both columns at the anchor. Counting and matching-occurrence
lookup apply the same checks. `comparison_total` counts retained ordinary
anchors; `comparison_assessable` and `comparison_excluded` partition that total
for each condition, and `comparison_matched` counts matching assessable anchors.

Unknown/legacy coverage cannot establish ordinary controls. Near the tail,
unconfirmed possible starts remain unresolved: “non-start” means no confirmed
start in the selected snapshot, not a permanent negative outcome. These controls
are ordinary timestamps, not all other peaks/troughs.

For a candidate, let `m/n` be target matches / assessable events and `c/d` the
same quantities in the comparison:

```text
target frequency = m / n
comparison frequency = c / d
difference in percentage points = 100 * (m/n - c/d)
frequency ratio = (m/n) / (c/d)
```

A missing comparison denominator or zero comparison frequency makes the ratio
not estimable, displayed as an em dash. No infinity or smoothing is introduced.
Counts remain visible. Verified-timing, ready-reference counts produce the
separate `rank_ratio`, using their own matches and denominators in both cohorts.
Ranking also requires the selected minimum target/comparison/match counts.
Eligible candidates sort first, then descending ready-reference ratio,
descending descriptive matched count, and deterministic pattern identity.
Low-support candidates stay accessible when “Show ranked candidates only” is off.

In the original overview/Existing patterns route, All families has separate
summaries and frequency grids but no pooled comparison or candidate scores. Double-click a family row, then explicitly rerun to compare
that exact family.

## 8. Worked counting example

The deterministic test fixture contains two target starts and two other-family
starts. For one observed label, sequence and pair, respectively, both target
starts match and one comparison start matches:

| Quantity | Count/value |
|---|---|
| Target | 2 / 2 = 100% |
| Other-family comparison | 1 / 2 = 50% |
| Difference | 50 percentage points |
| Ratio | 2 times as common in this history |

With the normal 20/20/5 thresholds, that tiny sample is not rank eligible. The
hand-count test sets thresholds to 1/1/1 to check the calculation, not to suggest
reliable research defaults. If one target slope is missing, a pair requiring
slope has one assessable target while delta-only remains at two. If the pattern
occurs zero times in comparison, the ratio is not estimable even with target
matches. Both mirrored swing directions use the same original signed construct
values; mirroring the event fixture does not mirror the labels.

The timing regression fixture scales this example to 20 target and 20 comparison
starts, with 20 and 10 matches. With verified timing, the ratio and `rank_ratio`
are both 2 and the default 20/20/5 thresholds are met. With unknown timing, the
descriptive ratio remains 2, both ranking denominators are zero, and every
candidate is withheld from ranking. A mixed fixture has descriptive counts 4/4
versus 2/4 (ratio 2), but verified support 2/2 versus 1/3 (`rank_ratio` 3). Its
small support is tested with 1/1/1 thresholds; it does not meet normal defaults.

The ordinary-control edge fixture has 14 stored rows, a start at row 1 and a
requested window from offset 0 to +2. Window intersection excludes ordinary
anchors 0–3. For `delta[0]`, anchors 4–13 all remain assessable, including the
last two rows. If only rows 12 and 13 match, the comparison is 2/10; a target
frequency of 1/1 gives a descriptive ratio of 5. A condition requiring +2 has
only eight assessable controls, with two explicitly excluded and a total of ten.

The ratio answers how common a label pattern is **given** the retrospectively
selected event group. It does not answer the probability of that trend starting
when a label pattern appears. Overlapping windows also do not represent
independent trials. Diagnostics counts overlapping target-window groups and
examined candidates; no significance, confidence interval or forecasting
probability is attached to the raw counts.

## 9. Result views and lifecycle

| View | Contents |
|---|---|
| Trend families | Exact keys, examples, unique usable starts, exclusions, origins and timing counts |
| Labels around event | One column/family frequency grid, T0/P0, counts and missing/support flags |
| Patterns | Conditions, descriptive and ready-reference counts, comparison, differences, ratios and ranking reason |
| Events | Included/excluded selected starts; anchor/confirmation fields; lazy raw label window; original provider evidence |
| Diagnostics | Identities, profile modes, UTC configuration, coverage/legacy intervals, duplicates, exclusions, thresholds and overlap |
| Refinement funnel | Ordered incoming, passed, mismatched and unavailable counts; shows where selected starts leave the population |

Legacy study tables use 500-row pages; horizontal scrolling exposes every field.
Pre-event candidates, inspector tables and linked ledgers use 50-row pages, as do
refinement Results/Compare and Population evidence member/condition tables. Other
unchanged detail tables retain their own paging. Selectors filter the complete
linked ledger before pagination. Full context is above the views and in its tooltip and
Diagnostics. Matching-occurrence lookup uses the shared background runtime.
Selecting an occurrence computes only its bounded window for inspection.

One operation runs per DAS session. Catalogue, study and matching-occurrence
operations use the existing Analysis application service/CoreRunner. Operation
shows the active task; Cancel requests cooperative cancellation and replacement
work waits for worker exit. Failed/cancelled work publishes no partial result.

Changing source, unchecking/removing it, reloading, observing a changed revision,
rerunning binning or changing binning settings clears dependent study state.
An unchanged catalogue refresh can preserve valid results. Original discovery
filter changes invalidate that study output. A pinned-refinement draft does not
erase its completed checkpoint: Evaluate applies it only after successful
completion, while History/reset restores saved settings without mining. Late
callbacks are rejected by session/generation.
Closing and reopening DAS creates a fresh session; no study is inherited.

No study, label enrichment, schema migration, export, Artifact update or database
write is performed. All report models are disposable. Source files and protected
user persistence retain their original owners.

## 10. Backend route and later work

```python
catalogue = analysis_service.load_pattern_catalogue(completed_binning_result)
# Construct a validated PatternRequest from explicit event and context choices.
study = analysis_service.run_patterns(completed_binning_result, request)
patterns = study.frame("patterns")        # detached table
events = study.frame("events")
window = study.event_window(event_id)      # detached, bounded on-demand detail
evidence = study.evidence(event_id)        # detached copied witnesses
matches = study.pattern_matches(pattern_id, "target")
```

The GUI routes these longer operations through `submit_pattern_catalogue`,
`submit_patterns` and `submit_pattern_matches`. Financial Tools remains the
binning/UTC mathematical authority; Analysis owns reconciliation, event context,
alignment, cohorts and counting; GUI owns controls and presentation. No new
Core authority, database schema or plotting field is introduced.

The parent GUI run uses full-history distributions and snapshot-read
availability. Neither guarantees historical availability of constructs at T0/P0.
Family and origin are outcomes established by later UTC evidence. They are never
fed into profile fitting. A later causal phase must establish construct identity
and availability, fit on prior calibration data, freeze candidates before a
chronological test, separate overlapping discovery/test windows, include false
positives and unconfirmed outcomes, and replay actual availability. Live mode,
generic swing populations, strategy evaluation and cross-database/asset pooling
remain separate approved work.

## 11. Refine selected starts using saved UTC measurements

Refinement selects a historical population. It does not identify new events,
recalculate UTC, refit bins or change the meaning of a label. Each event remains
the original T/up_start or P/down_start. Its later movement and pullbacks describe
the outcome associated with that start. UP and DOWN populations stay separate.
Ranges can describe preceding context; range-start lifecycle studies are not
implemented here.

This section describes the preserved simple **Refine selected starts** controls.
The granular pinned editor described in section 13 adds per-row bases, purposes,
ALL/ANY and exclusive endpoints without changing these simple semantics.

The controls start collapsed, with every filter off and every numeric bound
blank. A blank bound is unrestricted; **zero is a real inclusive bound**. Enable
a group and enter one or more conditions. Conditions combine with AND, including
conditions on different measures or units. Empty enabled groups remain inert.
**Clear refinements** resets these controls without discarding the binning run
or substituting a different event/family. Invalid, reversed, nonfinite or
incompatible bounds disable Analyze with an explanation.

### One measurement basis

| Basis | What its measurements describe |
|---|---|
| Completed trend | Default for active measurement filters: an ended episode's `final_structural` outcome. Open or interrupted progress cannot stand in for completion. |
| Frozen formation | First activation only: `formation_metrics`, its S–F structure and frozen pullback snapshot. Later continuation cannot change it. |
| Observed progress | Saved `observed_structural` progress and its observation limit. Status remains explicit: open, ended or interrupted. This is not a promise of a final outcome. |

S is the starting swing; F is the final formation pivot; E is UTC's retained
structural endpoint; O is the saved observation limit. A single basis applies
to movement, duration and pullbacks together. Context-only refinement does not
silently require completion. There is no fallback from missing completed data
to observed or formation measurements.

### Preceding context

UP, DOWN and RANGE each have independent **Any / True / False** selectors for
the stored row immediately before S in its valid segment. DOWN=True with
RANGE=Any includes overlaps; DOWN only requires DOWN=True, UP=False, RANGE=False.
Three false flags mean no membership, not RANGE. A segment-start absence is
unavailable, not three false flags.

**Previous confirmed direction** selects Any, UP, DOWN or no previous confirmed
episode. An explicit UP/DOWN selection can also choose an exact previous family.
This is UTC's scanner activation order, not proof that the preceding episode
was known before S. The existing Origin selector remains independent. Details
retain scanner predecessor and previous-confirmed lineage separately.
Preceding memberships are retrospective; these controls do not manufacture
per-event causal availability.

### Movement and duration

Movement conditions read net directional movement, signed endpoint movement,
favorable/adverse pivot excursion or pivot span, in points or percent. They map
respectively to `directional_move`, `signed_move`, `pivot_favorable`,
`pivot_adverse` and `pivot_span` fields of the chosen movement object. For a
favorable DOWN move the directional value is positive and the signed value is
negative. No absolute value or sign normalization is applied. Missing percentage
references do not invalidate an otherwise usable points condition.

| Duration | Meaning and allowed basis |
|---|---|
| Structural | S–F for formation; S–E for completed/observed |
| Endpoint extension | F–E; completed/observed only |
| Observed elapsed | S–O; completed/observed only |
| Formation confirmation delay | Stored `confirmation_delay_ms`; any basis, elapsed time only |

Bars are stored row intervals, not inclusive row count or a conversion from the
nominal timeframe. Time accepts milliseconds, seconds, minutes, hours or days,
converted exactly to integer milliseconds. Sub-millisecond bounds are rejected.
Bounds are not rounded before comparison. Nonuniform valid timestamps remain
usable for measurements; existing pattern-window continuity rules still apply.
Details include spacing evidence, and durations display as durations rather than
calendar dates. Changing display timezone changes instants only.

### Internal pullbacks

Select one UTC cohort. Completed/observed defaults to `internal_recovered`;
formation defaults to `formation_recovered`. A cohort can be restricted by member
count, mean/maximum depth in points or percent, and mean/maximum total recovered
duration in bars or time. **Total recovered duration is launch to recovery**,
including descent; it is not the separate worst-to-recovery duration.

Formation exposes `all_observed`, `internal_recovered`, `formation_recovered`
and `formation_pending_at_boundary`. Completed/observed also expose
`continuation_started`, `recovered_during_continuation`, `currently_pending`,
`pending_internal_launch`, `endpoint_context`, `ended_unrecovered` and
`interrupted`. The controls give readable descriptions; exact definitions remain
in [UTC episode measurements](UTC_EPISODE_MEASUREMENTS.md).

Recovered internal pullbacks have launch and recovery inside S–E. Endpoint or
all-observed cohorts can contain incomplete/outside-structural movements. Cohorts
overlap and must not be summed as disjoint categories. Formation-pending status
stays frozen even if a later report records recovery.

Zero members can satisfy a count bound. An empty or partially supported depth or
duration statistic is unavailable, not zero. Percentage depth must have support
for every applicable cohort member; recovered-duration support applies to
recovered members. Mean recovered duration in bars may be fractional. Event
details preserve counts, eligible support, units and unavailable reasons.

### Copied evidence and trustworthy exclusions

The catalogue reads validated enrichment already copied into the pinned database.
Classification-only providers still support the unrefined workflow. They cannot
provide invented movement or pullback values. Corrupt enrichment fails validation
instead of being silently treated as legacy data.

Before applying thresholds, Analysis resolves one coherent measurement projection.
It never combines a duration from one report with pullbacks from another. Equivalent
copies may agree after input-local identifiers are normalized for comparison;
original evidence retains those identifiers. An older open report does not block
an otherwise valid completed report. Conflicting completed outcomes or differing
observed snapshots are unavailable/ambiguous; there is no latest-provider override.

The required source rows, timestamps and high/low evidence must be covered by the
pinned database and compatible copied associations. A full report alone does not
prove that its outcome was imported. Append may provide later termination evidence
while the earlier prefix owns formation. Such borrowing requires an immutable
prefix match and supported later pivot confirmation; retrospective membership or
continuation changes are not themselves prefix corruption. Missing middle rows,
changed established evidence and unverifiable legacy prefixes are excluded with
specific reasons. Unused optional measurement domains do not demand extra coverage.

### Counts, comparisons and interpretation

The family selector shows **refined / original** eligible starts and retains an
exact selected family even at zero. Both target and other same-direction families
receive the identical refinements. Ordinary non-start timestamps have no matching
episode outcomes: in Existing patterns, selecting that comparison with an active predicate disables
Analyze and retains the user's selection. The original All-families overview
continues to give separate summaries, not a pooled target score. Explicit
pre-event pooled scopes and granular common/outcome comparisons are separate
routes described in section 13.

The backend funnel proceeds through selection, original coverage, measurement
availability/resolution, context, movement, duration, pullbacks and inclusion.
Each stage's incoming count equals passed + mismatch + unavailable; the first
failing stage accounts for exclusions, while event evidence retains all applicable
reasons. Events keeps excluded starts visible. Pattern match lists use the same
included population as their counts. Original timing/support/ranking rules remain.

For example, select T and an exact UP family; choose completed outcomes; require
DOWN=True, UP=False and RANGE=False before S; enter directional movement >=3%,
structural duration 12–60 stored bars and internal-recovered count 1–3. These are
user-selected research thresholds, not recommended trading thresholds. The study
describes labels around starts whose later outcomes met those conditions. It does
not establish that those labels predicted a 3% outcome in real time.

Applied settings, pinned source and binning run remain attached to immutable result
context. Changing these original discovery refinements invalidates the dependent
study/matches through the existing background-session lifecycle. An unsaved
pinned-refinement draft instead retains its completed checkpoint until Evaluate;
restoration and population changes are covered in section 13. Decoded coverage/projections are prepared
in the background; family-count refreshes reuse their cached facts. No study
presets, exports, source migrations or database writes are added.

## 12. Pre-event combinations

Select **Study mode → Pre-event combinations** after selecting a database, a
completed binning run, its columns and a UTC event/family. A primary combination
contains conditions from at least two columns and two distinct negative offsets.
Single conditions remain available as explanatory baselines. The original
All-families selector remains a separate overview. An exact family or an explicit
**Selected families (pooled)** / **All compatible families (pooled)** scope can
be used for pre-event search with a compatible comparison question. These new
scopes count canonical events once and preserve separate family evidence.

### Window and inputs

With start position S, history length W and lead h, the permitted offsets are
`-(h+W-1), …, -h`. Defaults W=6 and h=1 mean -6 through -1. W=6 and h=3 mean -8
through -3. Each is configurable from 1 to 100. Lead is positive: the event bar
and future bars never enter candidate construction, pruning, counting or ranking.
The legacy Before/Sequence controls are disabled in this mode, with their values
retained. After is inspection-only. Changing it cannot change pre-event results.

One rule might require `delta[-4] in {N02,N03,N04}` AND
`volume_change[-2] in {P06,P07,P08}` AND `momentum[-1] = P01`. All terms must
match; a column may recur at different bars, but the same column/bar cell cannot
occur twice. No mean of label indexes, cross-column bin pooling, gap filling or
time warping occurs. Each label refers to its original column and profile.

At a decision bar t=S-h, a condition with offset o reads t+(o+h), never after t.
This algebra does not establish real-time availability. S, family and outcomes
are retrospective anchors; current profiles use full history. Preceding context
at S-1 can also be later than the cutoff when h>1.

### Tolerance

Shared tolerance defaults to **Exact labels**. Optional radius one includes
the immediately neighboring stored bins, with per-column overrides. N03 permits
N02/N03/N04; P01 permits P01/P02. Expansion is clamped within the original sign
side. Zero is exact and NaN/unavailable observations never become wildcards.
Empty bins retain their original positions; they are not skipped. Counts above
99 use stored numeric indexes, not text sorting. Positive/negative counts and
distributions remain independent. Non-directional named bands support exact
matching only; their controls explain why tolerance is unavailable.

Selected rule details show centers, actual allowed sets, percentile spans,
reference counts and recorded observed value ranges. Those ranges are not exact
decision boundaries, and ordinal neighbors need not be equally distant in raw
values. Logically identical allowed sets share one rule with center aliases
retained in backend detail. Exact center diagnostics are supplied for each alias.

### Choose the comparison question

| Question | Target | Comparison |
|---|---|---|
| Different formation families | Selected exact family passing the filters | Other families of the same direction passing the identical filters |
| Different completed outcomes in the selected family scope | Simple route: selected family scope/context passing all active movement/duration/pullback bounds | Same scope/context with every requested measurement available, failing at least one numerical bound |
| Ordinary historical timestamps | Selected family scope passing its numerical outcome bounds | Every covered timestamp with no recorded UP/DOWN start at that anchor |
| Recurrence only (no comparison) | Selected starts passing the definition | No comparison population or contrast |

In the simple discovery route, different outcomes requires completed-trend basis
and at least one numerical condition. The pinned granular route instead requires
an active outcome definition and supports valid per-row bases/fixed horizons;
its complete comparison rules are in section 13. Open, interrupted, partial, ambiguous or missing requested outcomes
belong to neither group—even when another known condition already fails. The
assignment table lists actual failed bounds; comparisons are not collectively
renamed “small trends.” One coherent provider resolution supplies all conditions.

Ordinary timestamps are snapshot controls, not failed troughs or a deployment
false-alarm population. Nearby ordinary rows are retained, and other recorded
starts are excluded and counted separately by direction. Numerical outcome bounds
apply only to targets. Origin must be All and preceding-context restrictions must
be inactive: arbitrary timestamps do not yet have equivalent authoritative
lineage. Incompatible selections remain visible and disable Analyze. No control
is given fabricated UTC S/F/E/O values.

### Search, denominators and ranking

The Analysis backend expands frequent conjunctions with occurrence masks. It
prunes using absolute tolerant target-match support, never individual contrast
or a frequency with a changing denominator. This can recover a joint pattern
whose individual terms show no contrast, and a tolerant pattern whose exact
centers do not occur at those cells. Each canonical start votes once.

| Setting | Default / boundary |
|---|---|
| Columns | Existing 1–8; primary combinations require at least 2 |
| History / lead | 6 / 1; each 1–100 bars |
| Maximum terms | 3; configurable 2–4 |
| Primary combinations | At least 2 columns and 2 distinct offsets |
| Tolerance | 0 or 1; shared default and per-column overrides |
| Support gates | Existing 20 target / 20 comparison / 5 target matches |
| Candidate limit | 100,000; may be lowered explicitly |
| Match-state memory | Conservative estimated limit 128 MiB; may be lowered |
| Presentation | 50 candidates per page, with separate single-baseline view |

Every atom and evaluated conjunction counts toward the candidate limit. Reaching
a bound produces **INCOMPLETE SEARCH**, the reason, stage and count examined.
Partial rows can be inspected but have no completed-ranking eligibility. A
canceled worker publishes no completed study. One column or one history bar
disables primary combinations while retaining baseline inspection.

For each rule, each cohort and each discovery/later partition, results retain
total, assessable, excluded, matched, frequency, exact matched/frequency,
additional tolerant matches, ready/timing-supported matches and timing exclusions.
Frequency is matched/assessable. Exact and tolerant rules share the same required
cells and hence the same assessability denominator. Limited support may contribute
to descriptive counts, but cannot qualify a rule for the supported shortlist.

Difference is target frequency minus comparison frequency, in percentage points.
Ratio is unavailable when comparison frequency is zero or missing. Supported
primary rules sort by descending discovery difference, then target matches,
fewer terms, fewer extra allowed bins, then stable identity. Zero comparison
matches can still support a finite frequency difference when the comparison
sample itself is adequate. No probability, p-value or forecast-reliability badge
is attached. With no adequate comparison, recurrence remains inspectable.

Rules with the same observed discovery match set receive an empirical group ID;
they remain distinct definitions, not a claim of logical equivalence. Inspecting
a rule loads each single term and each drop-one-term version counted on that
combination's same assessable rows. Extra terms may be redundant; these counts
are not causal feature importance.

### Reading results and refining the analysis

The Patterns page separates primary combinations, single baselines and all
retained rows. Select a rule for allowed-bin details. **Inspect target
observations** / **Inspect comparison observations** loads a background-computed
ledger, initially displaying tolerant discovery matches. Switch its controls to
exact matches, additions from tolerance, all assessable, unavailable or all
observations; choose discovery, later, timing-excluded or all partitions. Counts
and this ledger use the same predicate. Occurrences include actual tokens,
ordinal deviations, source times and profile IDs. Simpler-rule counts load into
the selected pattern details on the Patterns page.

The existing Events detail keeps readable S/F/E/O and copied evidence. The label
grid distinguishes mined offsets from inspection-only bars. The Refinement page
shows partition counts plus per-event target/comparison/excluded assignments and
failed conditions. Family counts and the grid describe the complete refined
cohort; pattern columns explicitly separate discovery and later observations.

**The first pattern check is not the end of the workflow.** Pin selected rules
and use **Pinned refinement** to change the population while preserving
their definitions. Evaluate does not mine or refit; unsaved drafts retain the
completed checkpoint. Granular conditions, horizons, family/date restrictions,
History and linked inspection are described in section 13.

The original discovery route is also retained: changing its context/outcome or
tolerance/window/comparison settings and rerunning recomputes populations and
mines new patterns. These discovery changes clear their dependent output through
the existing cancellation/stale-result path while retaining the database and
completed binning run. Within a pinned workspace, the explicit new-search action
creates a separate discovery; replacing the pin requires an explicit choice.
View filtering only changes displayed rows. No persisted study history is added.

### Chronological inspection

**Discover earlier, inspect later** defaults to a 70/30 split by selected axis
rows; a display-time date can override it. Candidate definitions, tolerance and
rank order use discovery observations only. Later observations cannot create or
rank candidates, including through content-dependent memory-limit estimates.

Each observation carries its full feature interval and the evidence interval
needed to resolve its cohort. Both must be wholly on the appropriate side of the
split. Unknown or crossing intervals exclude the sample from both discovery and
evaluation. An early anchor with a later-resolved outcome cannot teach discovery.
Retrospective preceding context and ordinary-time classification require their
supporting report's observation frontier. A full-snapshot witness can make an
earlier partition unavailable; an earlier availability is never invented.

Results show chronological block counts and overlapping-window groups without
claiming independence. Their label profiles were fitted on the whole database,
so this is **retrospective temporal stability**, not untouched forecasting
validation. Repeatedly changing filters after inspecting the later period is
exploratory. Prior-only profile fitting, true construct availability, live context,
natural-prevalence false alarms and predictive validation remain separate work.

### Internal route

`PatternRequest.pre_event` is an optional immutable `PreEventSpec`. Absence keeps
the legacy route. `pre_event_cohorts.py` owns the new populations and partitions;
`pre_event_patterns.py` owns predicates, bounded mining, counts and ledgers.
The existing Analysis service, application, presenter and shared Core transport
are reused. `PatternStudy.frame()` returns detached scalar/JSON table cells.
For the new mode only, `pattern_matches()` returns the complete selected cohort
ledger with matched/assessable/partition flags; its `pattern_detail` frame
attribute contains detached JSON diagnostics computed on the worker. Legacy
mode continues to return matching occurrences only.

## 13. Pin, refine, compare and inspect discovered combinations

Use [Post-discovery refinement](POST_DISCOVERY_REFINEMENT.md) after the first
pre-event search. **Pin combinations for refinement** uses checked rules across
pages (or the current row when no rules are checked). It freezes source/profile
identity, terms, offsets, allowed sets and original order. **Evaluate pinned
combinations** resolves a new population from the retained root, so relaxing
filters can restore observations rather than intersecting previous winners.

The new manual distinguishes simple discovery semantics from granular common
restrictions and outcome definitions; explains all four comparison questions,
explicit pooled family scope, inclusive anchor-date subintervals and N-bar
event-close outcomes; and defines completed checkpoints, actual parents, History,
explicit new search/repinning and stale/cancelled work. Zero/low-support rules
remain visible. No UTC detection, plotting, profile fitting or ranking policy is
changed by refinement.

The seven inspector pages link counts to exact observations, unavailable reasons,
term values and measurement distributions. Bounded sensitivity removes each
selected restriction independently from the same saved granular base without
inserting History or silently optimizing a threshold. All results remain
retrospective and in-session. GR-06 and the exact-UTC tooltip correction have
independent code/package acceptance; final-source integrated validation and
native acceptance, including endpoint/child tooltip hover, remain later GR-07
work. Neither these manuals nor their examples establish predictive validity.
