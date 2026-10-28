# Data Analysis Suite

**Status:** Connected retrospective Variation & Binning and Trend Start Patterns workflows; wider Suite incomplete
**Updated:** 2026-10-21

The Data Analysis Suite is intended to turn calculated market parameters into
information that can be compared and investigated. Its first implemented
statistical foundation is the Variation Analyzer and Dynamic Binning engine:
given a defined historical reference, it describes where a parameter lies in
that reference and how frequently equally extreme observations occurred.

**The Suite is incomplete and remains under development. Its broader structure
may change significantly.** The production Analysis Suite now connects its
Variation & Binning tab to saved databases and the accepted statistical backend.
It can analyze several columns independently from one database revision, using
that revision's entire history. This is retrospective, in-memory analysis.
Broader investigations, cross-database operations and live market integration
remain separate work. Implementation readiness, independent audit and user
visual acceptance are distinct gates.

## Documentation map

| Read order | Manual | Coverage |
|---|---|---|
| 1 | [Variation Analyzer and Dynamic Binning](VARIATION_AND_DYNAMIC_BINNING.md) | Meaning, mathematical rules, historical reference, bands, rarity, exceptional cases, time and architecture. |
| 2 | [API and data reference](VARIATION_API_REFERENCE.md) | Every public operation, model field, output column, validation rule and profile conversion boundary. |
| 3 | [Worked examples](VARIATION_EXAMPLES.md) | Hand calculations, executable examples, EMA percentage deltas, historical versus forward use, replay, restoration and interpretation. |
| 4 | [UTC classification](UTC_CLASSIFICATION.md) | Exact P/T formations, origins, confirmation timing, independent continuation records, Artifact/database carriage and the pinned backend reader. |
| 5 | [Trend Start Patterns](TREND_START_PATTERNS.md) | Selecting T/up_start or P/down_start, exact UTC families, copied-evidence coverage, label windows, pattern counts, comparisons and interpretation. |
| 6 | [UTC episode measurements](UTC_EPISODE_MEASUREMENTS.md) | Nonvisual UP/DOWN movement, duration, preceding context, internal pullbacks, frozen formation, evolving continuation and explicit as-of replay. |
| 7 | [Post-discovery refinement](POST_DISCOVERY_REFINEMENT.md) | Pin discovered rules; evaluate typed common/outcome conditions, horizons and family/date restrictions; restore History; inspect linked evidence and bounded omissions. |

UTC enrichment is now stored alongside its unchanged classification. Backend
readers can access provider-specific measurements using the pinned bundle's
`metrics(artifact_id)`. Trend Start Patterns now offers optional filters for
preceding context, movement, duration and internal pullbacks. They start disabled.
Completed, frozen-formation and observed-progress bases remain distinct; imported
coverage and coherent provider evidence are checked before thresholds. These are
retrospective population filters, not available-at-event predictions.

Trend Start Patterns also offers **Pre-event combinations**: bounded searches
across multiple columns and bars strictly before a selected start. History and
lead define the offsets; optional neighboring-bin tolerance stays within each
column's own sign distribution. Named comparisons distinguish formation
families, measured outcomes within a selected family scope, ordinary historical
timestamps, or recurrence without comparison. Exact and tolerant counts, occurrence ledgers and optional
retrospective temporal stability are inspectable. See
[the complete workflow](TREND_START_PATTERNS.md#12-pre-event-combinations).

After the first pattern check, explicitly pin selected pre-event rules and use
**Pinned refinement**. **Evaluate pinned combinations** recomputes the
requested populations from the retained root without mining or refitting.
Completed checkpoints survive unsaved/invalid refinement drafts; History, reset
and parent comparison restore or explain saved results. The combination inspector
links counts and distributions to supporting observations, and sensitivity compares
explicit omissions from the same saved definition. See the [detailed manual](POST_DISCOVERY_REFINEMENT.md).

The original discovery controls and pattern mode remain available: editing those
settings and rerunning still rebuilds populations and mines rules. The pinned
workspace also offers an explicit **Search new combinations with these conditions**
action; its new discovery does not replace the pin until explicit repinning.
Display filters only change presentation. No UTC detection, plotting, binning,
persisted schema or user database is changed by an event study.

These manuals describe the directional extension and the preserved version-1
combined-reference implementation. They distinguish the backend's historical
and forward APIs from the GUI's retrospective snapshot workflow.

UTC now supplies nonvisual trend classification through its own result, Artifacts
and V6 database revisions. The Analysis backend can read the pinned copied
reports, separated by UTC instance and physical provider coverage. The
**Trend Start Patterns** tab now combines these starts with a completed binning
run from the same revision. It describes historical label combinations around
the selected starting swing and exact formation family. Existing
Variation & Binning operations and all 27 plotted UTC outputs are unchanged.
Old database revisions do not acquire classification automatically. See the UTC
manual for missing metadata, exact confirmation times and causal replay limits.

## Position in Leonardo

The intended research flow begins with accepted OHLCV and calculated Financial
Tools. The [Data Manager](../data_manager_docs/DATA_MANAGER.md) owns database
construction and explicitly reviewed membership. Analysis consumes the selected
data and derived parameters; it does not take over those storage authorities.

For direct backend calls, the caller supplies an already prepared DataFrame.
The Analysis area now prepares that frame from a validated saved revision when
the GUI runs an analysis. The statistical engine itself neither opens a database
nor computes the supplied indicator. It
accepts a delta, percentage delta, angle, slope, derivative or other finite
numeric parameter with a precise definition and unit convention.

| Capability | Current boundary |
|---|---|
| Describe positive and negative intensity independently | Implemented with `analyze_directional_variation`; no symmetry or recentering around zero. |
| Freeze and apply independent directional references | `fit_directional_binning` and `classify_directional_binning`; default 10 positive and 10 negative percentile bins, independently configurable from 1 to 1000. |
| Analyze a positive-only or negative-only column | Supported; absent directions remain uncalibrated, and zero is a separate state. |
| Describe a parameter history | Implemented with `analyze_variation`. |
| Freeze a reference distribution | Implemented with `fit_dynamic_binning`. |
| Classify historical or newly available observations | Implemented with `classify_dynamic_binning`, including individual observations. |
| Reuse a profile after JSON conversion | Implemented through validated dictionary conversion; storage is caller owned. |
| Select databases for DAS | The catalogue reads saved databases through the existing Data Manager store. The workspace can hold several checked entries; a run accepts exactly one active database revision and columns from that revision. |
| Run Variation & Binning from the GUI | Implemented: validated loading, shared defaults and per-column overrides, background execution, cancellation, distribution/bins/diagnostics/observations. Full-history retrospective mode only. |
| Compare different assets or timeframes | Separate profiles describe relative historical positions. Raw pooling and equivalence of risk are not established. |
| Condition on UTC hour, session, volatility or regime | Future contextual layer. Timestamps currently support identity, ordering and availability checks. |
| Describe labels around a selected UTC trend start | Implemented: T/up_start or P/down_start, exact formation family, independent origin/date filters, label frequencies, short sequences and paired columns. |
| Find combinations strictly before a start | Implemented in Pre-event combinations: 1–8 columns, history/lead windows, primary multicolumn/multibar conjunctions of up to 4 conditions, exact or same-sign neighboring-bin tolerance and named comparison populations. |
| Refine after inspecting initial patterns | Pin rules, edit a simple/granular draft and Evaluate the same rules; compare actual parent, restore session History, inspect linked evidence and bounded sensitivity. Explicit new search is separate. Full-history labels and adaptive later-period reuse remain retrospective. |
| Refine starts by saved UTC context/outcome | Simple route: one basis, inclusive AND and original funnel. Granular route: per-row basis, common/outcome purposes, ALL/ANY, fixed-horizon outcomes, family/date scope and coherent source/availability evidence. |
| Predict outcomes or evaluate a strategy | Separate future analysis. Event-pattern ratios and rarity labels are historical descriptions. |
| Connect feeds, schedule recalibration, publish Artifacts or save/export analysis results | Separate integration work. |

## What an observation can say

A useful result retains its original value while adding its profile identity,
direction, historical percentile, band, observed tail frequencies and support
status. A negative percentage delta can therefore be described as unusually wide
in magnitude without losing the fact that its direction is negative.

The reference makes the description repeatable. The definition, selected history,
measurement mode and policy make its meaning explicit. Later contextual analysis
can investigate when such observations occur and what follows them; the present
engine supplies the reproducible descriptive foundation.

## Directional configuration

Directional intensity is the default in the central Variation & Binning tab.
Shared defaults start at 10 positive bins, 10 negative bins and 2000 minimum
observations per populated direction. A selected column can override those
settings independently. A one-sign history does not need an artificial opposite
side. Neither equal bin counts nor percentile spacing implies symmetry in
numerical boundaries or equal sign frequencies.

The user can also select the existing Signed value (full reference) and Absolute
magnitude (full reference) modes. Their six configurable boundaries still define
seven bands; those controls are hidden in directional mode. Bin resolution and
the fixed 1%/5% rarity thresholds are separate choices.

## Run an analysis from the GUI

1. Open **Analysis Suite** from the main application. The saved-database catalogue
   loads in the shared Core runtime. **Select Databases** opens the filterable
   exchange, market type, asset and timeframe list; each filter also supports All.
2. Check one or more databases and choose **Add Selected**. These are workspace
   entries. The Use checkbox controls whether an entry is available in the tab's
   active-database selector; Remove removes only that workspace entry.
3. In **Variation & Binning**, choose exactly one **Active database**. Its pinned
   saved revision is validated and its actual columns load. Timestamps and known
   categorical/boolean outputs are excluded. Other exclusions, such as nonnumeric
   or infinite values, are explained beside the column list. An untyped but
   numeric stored column is explicitly identified as untyped.
4. Check the columns to analyze. Set **Shared Defaults**, then use **Column
   Overrides** for exceptions. Shared settings never combine the columns'
   samples. Every selected column receives its own reference and profile.
5. Choose **Analyze & Bin**. Source/configuration controls are disabled during
   work. Operation shows actual loading, fitting and classification stages;
   each indivisible fit has an indeterminate progress indicator, with the current
   column position in its stage text. Completed-column counts remain available
   between fits. Cancel requests
   cooperative cancellation and waits for the current calculation to finish.
6. Scroll to the results below the settings. Choose a result column and switch
   between the four views below. Switching result columns does not recalculate.
   Use the workspace splitters, vertical scroll area and table scrollbars when
   working in a smaller window.

| Result view | Reading the result |
|---|---|
| Distribution | Empirical cumulative share of the original signed finite values. Axes follow the observed range; no Gaussian or symmetry is imposed. Directional mode also shows each side's support and median magnitude. At most 2000 points are drawn, with a notice when detail is reduced; all observations still contribute to fitting and counts. |
| Bins / Bands | Positive and negative bins, or the seven combined-reference bands, with percentile intervals, counts, observed signed ranges and support. Requested empty bins remain present. Observed ranges are not continuous decision thresholds. |
| Diagnostics | Source and profile identities, effective settings, reference span, snapshot availability convention, unit/definition limitations, total/finite/missing/zero/sign counts, support and occupancy. |
| Observations | Every original timestep, 500 rows per page. Previous, Next and the page selector reach every row. Scroll horizontally for additional fields; header tooltips expose the backend field names. All 35 directional fields remain available when a directional profile was fitted. Missing values display as an em dash. |

A completely missing selected column has an `insufficient_reference` outcome
and no fitted profile. Its observation rows still show `missing_value` and
`insufficient_reference`; other selected columns can complete. These issue rows
have only the applicable identity/value/status fields, not fabricated backend
bins or tail labels. Zero-only, one-sign, constant and limited-support histories
use the accepted backend's explicit statuses. A completed column is not a claim
that its support is ready: inspect Diagnostics and row-level support/status.

Within-direction tail frequencies use only that sign's reference. Whole-reference
frequencies use all finite reference observations, including zeros. Neither
is a forecast probability. Changing bin count does not change the fixed 1%/5%
rarity thresholds, and low support can withhold rarity labels while retaining
descriptive bins.

## Describe a selected trend start

After completing Variation & Binning, open **Trend Start Patterns** and choose
**Load UTC event catalogue**. Select one copied UTC instance, then **Trough (T)**
for an uptrend start or **Peak (P)** for a downtrend start. Choose an exact
compatible formation family, or **All families** for the original separate family
overview. Pre-event combinations additionally offers **Selected families (pooled)**
and **All compatible families (pooled)**; these are explicit analysis scopes, not
a reinterpretation of the old overview. The fixed comparison question constrains
valid scopes; all compatible families cannot be compared with other families.
Select up to eight of the analyzed columns and set the event-anchor dates,
relative-bar window, comparison and support thresholds. Optionally expand
**Refine selected starts**, choose a measurement basis and set context/outcome
conditions in the simple discovery controls. Their bounds are inclusive; blank
means unrestricted and zero is a real value. Granular pinned refinements also
support exclusive endpoints and per-condition bases. Choose **Analyze selected events**. The same completed column profiles
are reused without refitting.

The six result views contain family counts, an offset/label frequency grid,
observed patterns, included/excluded events with lazy observation/evidence
details, diagnostics and the refinement funnel. Family counts show original and
refined starts; event details retain measurement support and exclusion reasons.
A pattern can open its exact target or comparison
matches. Legacy study tables use 500-row pages; pre-event combination and inspector
views use 50, as do refinement Results/Compare and Population evidence member/condition
views. Unchanged detail tables retain their own paging. Results state their event, role, family,
origin, pinned source, UTC configuration and window; full provenance is retained
in tooltips and Diagnostics. The detailed [manual](TREND_START_PATTERNS.md)
defines eligibility, denominators, missing/support states and a worked count.

This release studies confirmed **trend-start relationships**. It does not
enumerate all generic P/T swings or assume every peak/trough is a trend boundary.
Starting-swing time, swing availability and later UTC confirmation remain
separate. Neither a future-confirmed family nor a whole-history profile is a
contemporaneous predictor. Formation and continuation remain separate.

## Source identity, availability and result lifetime

The catalogue captures a database ID, revision ID and values SHA-256. Column
loading and Analyze & Bin load that exact revision through the public validated
Data Manager store path. A later database head update cannot silently change an
already selected reference. The Inspector identifies the active analysis database
and shows its full pinned revision and values SHA-256, including full-value
tooltips. These details survive unchanged catalogue refreshes, workspace-row
selection and display-time redraws. A highlighted workspace row can differ from
the explicitly labelled active analysis database. Invalidating the active source
clears its pinned details until a source is successfully loaded again; failed
loads do not retain the previous pin. Result details also expose provenance.

**Refresh Databases** rescans the catalogue. An unchanged revision preserves
the selection; a changed or unavailable revision clears affected columns/results.
**Reload Database** explicitly refreshes and reloads the active source, clearing
its column selection even if the revision is unchanged. Choose columns again.
Changing configuration, switching source, removing/unchecking the active source
or closing DAS invalidates the displayed result. Reopening DAS creates an empty
session. Profiles and rows are not saved or exported by this workflow.
Invalidating or rerunning binning also clears its dependent event catalogue and
study. Changing original discovery settings invalidates that discovery output
while retaining parent profiles. Editing a pinned-refinement draft instead keeps
the completed checkpoint visible until a successful Evaluate; invalid, failed,
cancelled or stale work publishes no replacement. Session History and report
caches are not persistent studies. Both workflows use the same shared
operation/cancellation path.

Saved database rows do not establish when each indicator originally became
available. For this GUI workflow, the adapter assigns every row the same UTC
snapshot-read timestamp, captured after the store validates the revision, and
uses it as the calibration cutoff. Candle timestamps retain their original
meaning and ordering. Future timestamps relative to that read instant fail.
This convention is explicitly retrospective; it must not be used as evidence
of causal historical availability or as a live/forward profile. Direct backend
forward examples require separately established availability metadata.

Formula and unit metadata may be absent from the saved snapshot. The adapter
does not infer units from names, recompute an indicator or convert percentages.
It records a stored-column definition with revision provenance and uses
`unspecified_database_native_unit`. A name containing `pct` is still insufficient
to infer a unit. Timestamps display using Leonardo's existing display-time
preference; changing that preference does not refit or reclassify results.

## Failures and cancellation

| Situation | Meaning and next action |
|---|---|
| Empty catalogue | No saved databases were discovered. Create a database through Data Manager, then refresh. |
| Catalogue load failed | Discovery failed; inspect Log and refresh after the cause is corrected. This is distinct from an empty catalogue. Individual unavailable database entries also produce Log warnings. |
| Analyze & Bin disabled | Select an active checked database, wait for column loading, check eligible columns and provide valid settings. |
| Revision removed, invalid identity, hash/shape/timestamp failure | The run fails without substituting a newer revision. Inspect Log; refresh/reload explicitly after resolving the source problem. Analysis never repairs the database. |
| Missing observations | Blank saved values become NaN for that column. They remain in the observation table and never become zero. Literal nonfinite numeric tokens are excluded from analysis eligibility. |
| Cancelling | The task awaiter may already be cancelled while a blocking fit still runs. Replacement work remains disabled until that worker exits; late results are discarded. |
| Catalogue load cancelled | After cancellation finishes, both the workspace and Select Databases show that the first load was cancelled or that the previous catalogue was retained. Refresh Databases retries discovery. Cancelling an ordinary refresh preserves the existing source, configuration and results. |
| Reopened while an old worker drains | The new session waits before loading its catalogue. It cannot inherit the previous session's result. |
| Unexpected analysis failure | The run fails without publishing partially completed columns. Correct the reported problem before retrying. |

The calculation and result tables remain in memory. Paging bounds the visible
table size; it does not provide out-of-core fitting or unlimited database size.
This workflow does not join databases, condition by session/regime, construct new
indicators, recalibrate automatically or connect live feeds.

## Implementation authorities

The directional public backend is in
[directional_variation.py](../../src/leonardo/financial_tools/directional_variation.py),
with models in
[directional_variation_models.py](../../src/leonardo/financial_tools/directional_variation_models.py)
and calculations in
[directional_binning.py](../../src/leonardo/financial_tools/_calculation/directional_binning.py).
The preserved combined-reference backend is in [variation.py](../../src/leonardo/financial_tools/variation.py).
Its models and statistical invariants are in
[variation_models.py](../../src/leonardo/financial_tools/variation_models.py).
The [Analysis service](../../src/leonardo/analysis/service.py) owns read-only
snapshot preparation and delegates financial decisions to those public APIs.
Its [application facade](../../src/leonardo/analysis/application.py) uses shared
Core tasks and tracks cancellation until the blocking worker exits. The
[presenter](../../src/leonardo/gui/analysis/presenter.py) queues GUI callbacks and
rejects stale session/configuration results. The
[Analysis Suite window](../../src/leonardo/gui/windows/analysis_suite_window.py)
and result widgets own presentation. A standalone window without a presenter
remains inert; production composition injects the service explicitly. The
[event-study engine](../../src/leonardo/analysis/trend_start_patterns.py) owns UTC
evidence reconciliation, alignment, cohorts and descriptive counting; its
[internal models](../../src/leonardo/analysis/pattern_models.py) are disposable
in-memory reports, not new persisted schemas. The
[documentation authority map](../README.md) identifies related current manuals.
