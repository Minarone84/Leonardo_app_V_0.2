# Post-discovery refinement

**Status:** Implemented historical research workflow through GR-06; final integrated validation and native acceptance remain subsequent GR-07 work.
**Updated:** 2026-10-21

This manual explains how to keep a discovered label combination fixed while changing the historical question asked of it. It covers the **Pinned refinement** workspace inside **Trend Start Patterns**, including granular conditions, fixed horizons, family and date restrictions, inspection and sensitivity. The wider DAS is incomplete and may change substantially.

Read [Trend Start Patterns](TREND_START_PATTERNS.md) for event identity, discovery, tolerance and chronology; [Variation Analyzer and Dynamic Binning](VARIATION_AND_DYNAMIC_BINNING.md) for independent column profiles; and [UTC episode measurements](UTC_EPISODE_MEASUREMENTS.md) for formation, continuation and pullback definitions. Those mathematical authorities are unchanged.

## A. Position and quickstart

UTC identifies the event. Binning labels describe the other constructs around it. Discovery proposes combinations; refinement asks whether those **same combinations** recur in a differently defined population. Inspection connects each reported count to its actual observations. These are historical descriptions, not forecasting probabilities.

The starting point is one pinned database revision, one completed binning run with independent profiles for each column, and one saved UTC instance. Choose a starting trough for UP or a starting peak for DOWN. The saved UTC configuration determines the event; DAS does not find replacement swings with a different P/T window. UP and DOWN stay separate. RANGE can supply context, but this workflow does not create range-start events.

### Three actions with different meanings

| Action | What changes | What stays fixed |
|---|---|---|
| Filter or sort a view | Which retained rows are displayed and their presentation order | Populations, counts, pinned rules, checkpoints and original rank |
| **Evaluate pinned combinations** | The population definition and counts of the existing rules; a completed evaluation becomes a checkpoint | Source revision, profiles, rule terms, offsets, allowed sets, original order and comparison question |
| **Search new combinations with these conditions** | Explicit new discovery under the draft conditions | The current pinned workspace and its selected checkpoint until an explicit replacement pin |

Changing terms, offsets, tolerance or allowed label sets is not a view filter and is not supported as an edit of a pinned rule. A new discovery is the route to different rules. Evaluate and ordinary inspection do not mine combinations or fit profiles.

### A practical pass through the workspace

1. Select a database, choose its construct columns, and complete **Variation & Binning**. Inspect distributions, bins and missing/support diagnostics before treating labels as useful inputs.
2. In **Trend Start Patterns**, load the UTC catalogue and choose the instance, T or P, direction-compatible family scope, columns and **Pre-event combinations**. Set history/lead and the comparison question before discovery. The root comparison question cannot be switched later inside that pin.
3. Run **Analyze selected events**. Review combinations and single-condition baselines. Select rules across result pages, then choose **Pin combinations for refinement**. With no checkmarks, that action uses the current row; otherwise it uses the checked selection. Merely highlighting a row does not pin it. Selection is retained across pages; the pin is bounded to 500 rules. Empty discovery has nothing to pin.
4. In **Pinned refinement**, retain **Simple filters** for the original one-basis inclusive-AND behavior, or choose **Convert current simple filters** before editing **Granular filters**. Conversion prepares a draft; it does not silently evaluate it.
5. Define common restrictions and outcomes, then choose **Evaluate pinned combinations**. Until it succeeds, the visible counts belong to the last completed checkpoint, not to the edited draft.
6. Use **Compare with parent**, **Population changes**, **Occurrences** and **Population evidence** to see what changed and why. Select a retained rule and choose **Inspect selected combination** for linked counts and distributions.
7. Remove or disable a condition and evaluate again to see whether observations return. Use **Reset to parent**, **Reset to discovery** or the History selector to restore saved settings and counts without evaluation.
8. If a genuinely different search is needed, use the explicit new-search action. Review its new discovery and explicitly pin its rules. **Start new pinned workspace** clears the current workspace after confirmation; it does not delete a database.

A replacement pin establishes a new root/set. It is not another evaluation in the old history. The original search completion flag and search-limit reason remain part of provenance: pinning rows from an incomplete discovery does not make that discovery exhaustive or ranking-complete.

## B. Frozen identity, populations and history

### What the pin binds

| Identity | Meaning |
|---|---|
| Root | The retained source envelope, original request, resolved split, source columns and copied UTC evidence used to evaluate rules |
| Set | The particular pinned selection within that root |
| Source discovery | The discovery from which the selection and its original ranking/provenance came |
| Rule | Its exact column, negative offset, profile identity and allowed-label conjunction; equivalent allowed sets retain center aliases |
| Checkpoint | Source discovery or a completed evaluation with its applied definition and evidence |
| Actual parent | The checkpoint selected when that evaluation was submitted, not simply the previously displayed row or latest evaluation |
| Source and profiles | Database ID, revision, values hash, binning run, column profiles, saved UTC instance and, where needed, canonical price provenance |

These internal identities are exposed for traceability; they are not a promise of a new disk schema or public root-package API. Labels from different profiles are not interchangeable merely because their text matches.

### Re-evaluation starts from the retained root

An evaluation resolves the requested population from the root's retained evidence. It does not intersect the previous evaluation's winning observations. Loosening a bound can therefore restore previously excluded events; changing an outcome can move a known event between target and comparison. **Population changes** distinguishes included, excluded, reassigned, unchanged and status-changed cases and retains the before/after cohort, partition and reason.

Every pinned rule remains in the evaluation, including zero-match and low-support rules. New counts and current support eligibility do not replace its original order or rank criterion. A display-only sort does not rewrite that order. A source discovery can contain additional unpinned rows; an evaluation contains the complete pinned set, not a newly selected shortlist.

### Drafts, restoration and session lifetime

Editing a draft leaves the last completed checkpoint visible with an explicit changed/invalid notice. Failed, cancelled or stale work publishes no partial replacement. Source changes and binning invalidation still invalidate their dependent workspace; retaining a checkpoint does not permit using it with a different database or profile.

| Control | Result |
|---|---|
| History selection | Activates that saved checkpoint and restores its applied editor values and counts |
| Reactivating the current History item | Restores that same saved state, discarding an unsaved draft even though the selected identity does not change |
| **Reset to parent** | Activates the current evaluation's actual saved parent |
| **Reset to discovery** | Activates the source discovery; no re-mining or profile fitting |
| **Discard selected leaf evaluation** | Explicitly removes a childless evaluation; source discovery and ancestors with children cannot be discarded this way |
| **Start new pinned workspace** | Clears the current pinned workspace after confirmation so another pin can establish a new root |

Restoring is not deleting descendants. History is in-session only; closing/reopening DAS does not restore a study from disk. Analysis owns checkpoints and stale-result fencing. Core owns execution, cooperative cancellation and worker draining. The accepted cancellation boundary changes Analysis state under its lock, then releases that lock before invoking Core cancellation. GUI controls and report caches are not a second history owner.

## C. Conditions, family scope, dates and comparisons

### Simple and granular definitions

**Simple filters** preserve the original **Refine selected starts** contract: one measurement basis for movement, duration and pullbacks, inclusive bounds and AND between enabled conditions. Context-only filtering does not require a completed episode. The legacy different-completed-outcomes comparison requires completed measurements and an active numerical condition.

**Granular filters** have two purposes. **Common population restrictions** define which observations may participate. **Desired outcome** describes the selected outcome within that population. These purposes are combined conservatively, not treated as statistically independent evidence. The same predicate used in both purposes is identified explicitly.

Each purpose combines its groups with ALL. Each child group uses ALL or ANY; conditions sit inside those groups, with no arbitrary recursive Boolean tree. Disabled groups/conditions and empty conditions are inactive. An enabled empty group is inert, rather than an ANY expression that automatically admits every observation. Add, remove or move groups/conditions through the editor; their current occurrence paths are retained in evidence.

### Specify the measurement, not just a threshold

| Selector | Interpretation |
|---|---|
| Domain and field | Context membership/lineage; UTC movement, duration or pullbacks; pre-event column raw value/label; fixed horizon |
| Basis | Per UTC measurement row: completed trend, frozen formation or observed progress |
| Cohort and statistic | For pullbacks, the precise stored cohort and count or mean/maximum supported statistic |
| Unit | Native raw units, points, percent, bars or supported duration units; never inferred from a displayed number |
| Column, profile and offset | A column from the frozen run, its exact profile metadata and an offset in the original negative feature window |
| Horizon N | Only for fixed-horizon fields: an integer number of subsequent bars |
| Bounds or allowed members | Numeric lower/upper endpoints or selected categorical/Boolean/label members |

For UTC definitions and valid field/basis/cohort combinations, use [UTC episode measurements](UTC_EPISODE_MEASUREMENTS.md). Frozen formation cannot acquire continuation-only duration/cohort fields. Completed data cannot silently fall back to observed progress. Previous direction/family is UTC lineage, not proof of knowledge before the start.

A blank numeric bound means no restriction; zero is an actual bound. Finite decimal and scientific notation are accepted. **Include lower endpoint** and **Include upper endpoint** choose inclusive or exclusive comparisons. Reversed/nonfinite/unsupported values are rejected; values are not rounded to display precision before filtering. Duration inputs are converted to their canonical units, including exact millisecond representability. A decimal mean pullback duration is not an individual integer bar count.

Column predicates must match the supplied column, offset and profile metadata. The literal profile ID string `"None"` is an identity, not absent metadata `None`. It must not be collapsed into an empty choice. Conditions using the same measurement but different bounds remain distinct predicates and may occupy separate rows in one group, such as `common/0/0` and `common/0/1`. Exact duplicate predicates within one group are rejected after canonical normalization. An identical predicate may occur in different groups or purposes, for example `common/0/0` and `common/1/0`; those occurrences keep separate paths for evidence and omission selection.

### Availability comes before Boolean success

Every active requested measurement must be available and coherently resolved. ANY does not bypass that requirement: a known passing branch plus an unavailable branch remains unavailable. A known failing bound plus an unavailable outcome is not a valid comparison case. Missing values, partial pullback statistics and provider ambiguity remain explicit exclusions rather than zero, false or nonmatches.

Analysis resolves compatible source projections for the complete request, including different requested bases, before applying bounds. It does not cherry-pick a favorable scalar from one provider and another scalar from an incompatible report. Copied evidence, imported coverage, immutable-prefix support and observation frontiers remain part of the decision. Original provider evidence is retained even where equivalent copies can be normalized for reconciliation.

### Four comparison questions

The question is fixed in the pinned root. Changing it requires an explicit new root/discovery route, not a refinement dropdown mutation.

| Question | Target | Comparison and restrictions |
|---|---|---|
| Other same-direction formation families | Selected family/families satisfying the requested definition | Other compatible families satisfying the same definition; selecting all compatible families is invalid because it leaves no other-family universe |
| Other measured outcomes | Selected family/families passing common restrictions and the active outcome definition | The same selected family/context, all requested facts known, common restrictions passing, outcome definition failing; requires an active outcome definition |
| Eligible ordinary timestamps | Selected trend starts passing their requested definition | Covered non-start anchors with common column restrictions; no fabricated UTC episode/context or horizon outcome for those controls |
| Recurrence only | Selected starts passing the definition | No comparison contrast or desired-outcome share; frequency describes recurrence in that selected population |

Granular other-outcomes can use valid per-row UTC bases and fixed horizons; it is not confined to completed-episode numeric filters. With ordinary controls, common restrictions must be supported pre-event column predicates; supported UTC measurement and horizon predicates may describe target outcomes. Active context predicates in either purpose and any non-All origin are rejected. Controls evaluate common restrictions only; unsupported ordinary-time lineage is not invented. Other recorded UP/DOWN starts are excluded from ordinary controls. Controls are not labelled failed troughs or deployment false alarms.

### Separate overview and pooled families

The original **All families** choice, through **Use existing family selector (exact / separate overview)**, preserves separate family overviews. It does not retrospectively become a pooled candidate search. For pre-event discovery, **Selected families (pooled)** and **All compatible families (pooled)** explicitly request pooling. Within refinement, **Use original request selection**, **One exact family**, selected pooled and all-compatible pooled choices remain source-bound.

The compatible universe is fixed by the pinned UTC instance, event direction and root. Family search text only hides list rows. Canonical events are counted once; aliases/providers cannot contribute duplicate votes. A pooled frequency is pooled matches divided by pooled assessable observations, not the mean of family percentages. Per-family evidence preserves rare and zero-count families so changes in family mix remain visible. Selecting an unavailable family or an invalid all-compatible/other-family comparison is an error, not an automatic substitute. Clearing a family override inherits the original selection; it does not necessarily choose all families.

### Inclusive anchor dates and exact UTC tooltips

In granular mode, **Limit anchor dates** applies an optional inclusive subinterval using **From (inclusive)** and **Through (inclusive)**. It filters event/control anchor timestamps inside the original pinned outer interval. It does not crop source rows, re-fit profiles, redefine the compatible-family universe or recalculate the original discovery/later split. Inputs and outcome evidence can extend outside this subinterval where the frozen source permits them.

Disable the restriction to use the full original envelope. History/reset restoration reapplies the saved interval or saved absence of a restriction. An out-of-envelope, reversed, incomplete or GUI-unrepresentable draft is invalid; it does not replace completed counts. The calendar must round-trip exact nonnegative integer UTC milliseconds. The visible format is `yyyy-MM-dd HH:mm:ss.zzz` in Leonardo's display timezone: `.123` means **123 milliseconds**.

Both the endpoint widget and its editable child carry the tooltip. A complete valid current draft shows **Exact UTC milliseconds**, whether or not that draft has been evaluated. Hover text does not apply the draft or change the completed checkpoint. Invalid or disabled state must not suggest that a retained value is applied: tooltips distinguish retained draft milliseconds, unavailable text/calendar state and **Date restriction not applied**. Display-time changes preserve the instant. Programmatic restoration refreshes the same properties without creating a user edit. Native text clearing can refresh tooltip properties on hover; that refresh is presentation-only, not a semantic filter change.

The tooltip correction is independently closed at code/package level. The native hover walkthrough remains subsequent GR-07 acceptance work; it is not an unresolved implementation finding.

## D. Fixed horizons and evidence timing

### Event-close formulas

Let S be the event row, `p0 = Close[S]`, and N an integer from 1 through 1000. The measurement uses closes through `Close[S+N]` and the N subsequent high/low observations at S+1 through S+N. **The event candle's high and low are excluded.** Define `H = max(High[S+1:S+N])` and `L = min(Low[S+1:S+N])`, with those endpoints inclusive.

| Field in points | UP | DOWN |
|---|---|---|
| `terminal_signed` | `Close[S+N] - p0` | `Close[S+N] - p0` |
| `terminal_directional` | `Close[S+N] - p0` | `p0 - Close[S+N]` |
| `favorable_excursion` | `max(0, H - p0)` | `max(0, p0 - L)` |
| `adverse_excursion` | `max(0, p0 - L)` | `max(0, H - p0)` |

Percent is the corresponding points value multiplied by 100 and divided by the positive event close `p0`. A favorable DOWN terminal move has negative signed return and positive directional return. These are close-referenced candle excursions, not UTC pivot excursions or trading returns including costs.

Financial Tools owns this arithmetic in `measure_event_window`: an isolated 50-significant-digit decimal context with round-half-even, independently of the caller's decimal settings. Filtering uses the actual canonical values, not the shortened display text. Analysis owns source selection, continuity, timing and population assignment, not an alternative formula.

### What N does and does not mean

N is an outcome horizon after S. **After** controls the displayed event window and cannot change pre-event mining or the requested horizon. History W and lead h specify the negative feature offsets `-(h+W-1)` through `-h`. UTC episode duration measures the selected structural/observed interval and need not equal N. An episode can be open while all N subsequent bars are present and the requested horizon is usable. Adding a completed-UTC predicate still requires its own ended-episode evidence.

### Prices, continuity and unavailable measurements

The reader binds canonical Close/High/Low roles to exact pinned-price provenance in the revision. It does not choose a similarly named construct column or reopen a newer database head. Missing/ambiguous role metadata prevents a supported horizon; the evidence identifies the required roles and snapshot.

Required observations must be finite and cover the requested continuous horizon. A missing tail, missing middle bar, unsupported continuity/timeframe, invalid high/low relationship or unavailable required price is recorded as unavailable with a reason. Unused price roles are not demanded for an unrelated scalar. Nonpositive event close makes percentage measures unavailable without automatically invalidating an otherwise supported points measure. There is no interpolation, shortened-N substitute or zero-fill.

### Four clocks and chronological partitions

Keep anchor/candle time, UTC confirmation time, evidence-availability frontier and snapshot-read knowledge separate. S is the starting swing, F the final formation pivot, E the structural endpoint and O the observation limit; they are not interchangeable confirmation clocks. A database snapshot proves what was stored when read, not when an indicator was known historically.

Chronological assignment checks the full feature interval plus all context/outcome evidence required by the request. Unknown or split-crossing evidence excludes the observation from both discovery and later evaluation. Horizon evidence extends through its required future bar; context can require a later report frontier. Neither an early anchor nor a narrow anchor-date restriction makes that evidence earlier.

Profiles in this GUI are calibrated on full history. Repeatedly inspecting the later partition while adjusting filters also reuses information. The result is retrospective temporal stability, not untouched predictive validation, live availability reconstruction, significance or calibrated forecast accuracy.

## E. The combination inspector

### Which result is being explained

**Inspect selected combination** describes a completed checkpoint using saved inspection options, even while the editor contains a different unsaved draft. The report binds root, set, source discovery, checkpoint, actual parent, selected rule, definition, options and source/profile provenance. **Current**, **Source** and **Actual parent** refer to those bound results, not whichever table happened to be open last.

Changing checkpoint, rule or report options can make a cached report stale. The GUI explains the completed binding and requires explicit inspection for the newly requested report. A sensitivity variant is labelled as a variant of its saved base; it is not silently installed as the active checkpoint. Failed/cancelled/stale reports do not replace completed state.

### Seven pages

| Page | How to use it |
|---|---|
| **Overview** | Select/filter retained rules; read counts, comparison and retention. View sorts are not new ranking policies. |
| **Examples and evidence** | Choose side, period, cohort, match class, family, fixed time block and readiness; open exact supporting rows and inspect a row's evidence. |
| **Distributions** | Inspect active numeric measurements and optional inspection-only metrics, with their own support and timing denominators. |
| **Families and time** | Inspect separate family counts and four fixed blocks of the original root envelope. |
| **Simpler and centers** | Compare single/drop-one versions on the full rule's same assessable rows and inspect exact-center aliases. |
| **Filter effects** | Read condition occurrence states, population changes and source/actual-parent retention. |
| **Sensitivity** | Plan explicit independent omissions, compare valid variants and inspect a chosen variant. |

### Population and matching denominators

Read the stages separately. Root records include retained candidate starts/controls and exclusions. Scope and mandatory source coverage are checked before common/outcome assignment. Common restrictions define participation; outcomes define target/comparison according to the fixed question. Chronology then determines discovery/later eligibility. **Assessable** means the complete rule's required label cells can be evaluated; a missing cell is not a failed match. Tolerant matches satisfy every original allowed set. Exact-center matches satisfy the representative centers; alias alternatives are reported separately. Additional tolerance matches are tolerant minus exact. Ready/timing-supported counts further require valid reference readiness and supported event timing.

These are different masks and ledgers, not interchangeable totals. Chronology-excluded observations remain diagnostic, not eligible successes. A scalar unavailable for a filter and a label unavailable for a rule also have different reasons. Root/common/outcome/source exclusions must be read from population evidence alongside the per-rule counts.

For other measured outcomes, the four-way table uses the **same eligible, assessable** population and matching mode:

| Cell | Meaning |
|---|---|
| a | Target outcome, rule matches |
| b | Target outcome, rule does not match |
| c | Comparison outcome, rule matches |
| d | Comparison outcome, rule does not match |

Target frequency is `a/(a+b)`; comparison frequency is `c/(c+d)`; difference is `100 × (target frequency - comparison frequency)` percentage points. Historical desired-outcome share among matches is `a/(a+c)` **only for the selected other-outcomes universe**. Other-family/ordinary questions use descriptive cohort labels, not that outcome-share claim. Recurrence has no comparison/share. An empty denominator is unavailable, not zero. Unknown observations are not silently added to b or d. A zero numerator with a nonempty denominator is a real zero.

### From a count to its exact supporting rows

Select a count/support link and choose **Open exact supporting rows**. The linked ledger applies the complete selectors before taking a page; it does not filter only the visible page. `visible` is the rows on this page, `support_set_total` is all matching rows after selection, and `retained_total` is all retained records on that report side. These totals answer different questions. Inspector tables and the linked ledger page at 50. The pre-event combinations, refinement Results/Compare and Population evidence member/condition tables also use 50; legacy study tables and other unchanged detail tables retain their own 500-row paging.

A row retains canonical event/control identity, cohort, partition and reasons; each term's raw value, actual label, allowed set, representative center, negative offset, profile and source timestamp; reference readiness; condition occurrence reports; measurement availability and genuine UTC witnesses. Ordinary controls do not acquire fabricated S/F/E/O or episode measurements. Labels remain column/profile-local. The min/max observed values recorded for a bin describe occupancy in that sample, not exact numerical decision boundaries.

### Distributions and supplementary metrics

Active numerical common/outcome measurements are supplied by the completed checkpoint. **Add inspection-only metric (maximum eight)** requests an additional numeric descriptor without bounds, categorical membership or a new cohort filter. It cannot duplicate an active measurement or another extra metric. It uses supported fields, source/coherence checks and horizon limits. It neither changes the checkpoint's cohorts nor adds history.

For each distribution, distinguish base selected observations, known values, source/coherence-unavailable values, metric-timing-withheld values and values actually summarized. An extra metric can be unavailable on a base observation that is perfectly usable for the rule. Additional evidence can cross the split and be withheld for that metric without reassigning the base cohort. The **Ready and timing-supported observations only** selector is another explicit denominator restriction.

`numeric_summary` sorts finite supported values. For n sorted values, the Q1/median/Q3 positions are `(n-1)/4`, `(n-1)/2` and `3(n-1)/4`. At an integer position it takes that value. Otherwise it uses the adjacent values with weights 0.25, 0.5 or 0.75 in stagewise convex interpolation under an isolated decimal context of precision 50 and round-half-even. Min/max are the finite endpoints. Empty support gives an unavailable summary; nonfinite interpolation has an explicit numerical reason. This is the implemented summary rule, not a substitution of another library's quantile convention.

### Simpler rules, time blocks and filter effects

Single-term and drop-one-term diagnostics keep the **full combination's assessability denominator**. Removing a term here does not admit observations that were missing that term in the original rule. Exact-center alternatives enumerate the retained center aliases, bounded as described below; they do not mine a better rule.

The four time blocks divide the original inclusive root interval, rather than making four equal-event-count groups or recomputing boundaries after a date restriction. Family and time evidence expose changing composition and empty groups; overlapping events are not independent samples.

Condition states are linked by occurrence path. Their exclusions can overlap and must not be added as if they were disjoint causal contributions. Retention against source or actual parent is `intersection(current eligible IDs, reference eligible IDs) / reference eligible IDs`. The population-size ratio is `current eligible count / reference eligible count`: it can exceed 100% after loosening restrictions. Retention and that ratio are not the same statistic; both are unavailable with an empty reference denominator.

**Conditioning on a rule's own input:** a pre-event column restriction studies the frozen rule R within a selected population Q; it does not add that restriction to R. If Q uses a column and offset already required by R, selecting that population can mechanically increase the observed frequency of R. A higher frequency in that subset is not independent confirmation that the unchanged rule improved across the original population, and is not calibrated forecast accuracy. Keep the population restriction explicit and compare its supporting rows and denominators with source and actual parent.

## F. Bounded sensitivity and resources

### Omit one restriction from the same saved base

On **Sensitivity**, explicitly select one through eight active condition occurrences or explicit anchor-date/family overrides, then choose **Compare selected omissions (no re-mining)**. Each variant removes only its selected occurrence/override from the **same saved granular definition**. Variants are not chained. Other conditions, ALL/ANY structure, pinned rule set, source, profiles and comparison remain fixed.

Removing an ALL member can broaden a population; removing an ANY alternative can narrow it. Neither change is guaranteed, because conditions can be redundant and source/chronology requirements can also change. Removing the last active outcome under other-outcomes is invalid: the plan retains a reasoned **not_evaluated_invalid_definition** row without executing it. Clearing a family override inherits the original source selection, not automatically all families. Empty groups stay inert under the predicate contract.

Simple checkpoints require explicit conversion and a completed granular Evaluate before sensitivity. **Inspect variant** explains a valid returned variant and its base binding. Sensitivity does not mine, fit, optimize thresholds, install a preferred result, replace only some rules or insert checkpoints into History. **Clear report cache** releases inspection/sensitivity reports; it does not delete checkpoints. To adopt a different definition, edit it explicitly and Evaluate.

### Implemented bounds

| Resource | Limit and consequence |
|---|---|
| Pinned rules | 1–500; empty/oversized selections rejected |
| Granular definitions | 32 active condition occurrences; eight stored groups; purpose ALL → group ALL/ANY → condition structure, not arbitrary nesting |
| Active fixed horizons | Eight distinct N values; each N is an integer 1–1000 |
| History | 20 retained evaluations in addition to source discovery; discard a permitted leaf or replace the workspace explicitly |
| Retained accounting | 128 MiB (134,217,728 bytes) across the accounted match state, granular population payloads and retained report/sensitivity payloads |
| Supplementary metrics | At most eight extra descriptors and at most 40 distinct active-plus-extra numeric measurements per inspected side; supported horizon limits still apply |
| Sensitivity | 1–8 unique explicit omissions per request |
| Exact-center alternatives | At most 4096 products of the retained terms' center alternatives |
| Linked ledger page | 1–50 rows; pagination does not remove retained observations |

Unsupported or over-budget inspection/evaluation is explicitly refused; it is not a truncated successful result. Retained accounting is not process RSS and does not claim an unlimited source-memory guarantee. Its match-state estimate covers atom/rule masks; population/report charges are additional. Frozen source/discovery data and other runtime overhead are not made free by that estimate. Clearing stale reports can release their accounted cost without deleting History.

These refusals differ from discovery's candidate/match-state bounds, which can produce an explicitly **INCOMPLETE SEARCH** with its reason and examined count. They also differ from a table page size. A small page is not a small population, and a retained incomplete discovery is not proof of exhaustive search.

## G. Examples, troubleshooting and boundaries

### A source-backed synthetic walkthrough

The accepted GR-06 capture fixture uses a synthetic pinned database with `signal` and `slow_signal`, completed profiles and one saved UTC instance. It selects T/UP, all compatible families pooled, other outcomes, history 3, lead 1, maximum 2 terms and exact labels. Its support thresholds are 1/1/1 for verification, not research recommendations. It pins six rules. Chronological splitting is disabled in this particular fixture; it is not a later-period validation example.

After explicit conversion, the saved granular definition uses a common ANY group over `signal[-1]`: raw value at least 900 **or** at most 850. Its outcome is N=6 terminal directional percent at least zero. The earlier evaluation is its actual parent. One retained rule is:

```text
signal[-2] in {P05} AND slow_signal[-3] in {P06}
```

In the completed current checkpoint, choose **Inspect selected combination**, **Overview**, eligible combined, original allowed sets, and the ordinary descriptive counts (ready-only off). The recorded result is:

| Cell | Count |
|---|---|
| a | 0 |
| b | 9 |
| c | 0 |
| d | 1 |

Thus target frequency is 0/9 = 0%, comparison frequency is 0/1 = 0%, and the difference is zero percentage points. Desired-outcome share is **unavailable** because a+c=0. It is not 0% accuracy. The zero-match rule is still retained. Open b's supporting rows to inspect the nine genuine target nonmatches; missing cases have not been relabelled as failures. This is useful evidence against the rule in this selected population, not a software error to hide.

### Additional support is not the base denominator

In a subsequent inspection of that same checkpoint, the fixture requests inspection-only N=1000 terminal signed percent. For current, eligible combined, target nonmatches, ready-only off, without a family/block restriction, the distribution has **9 base selected, 3 known/summarized, 6 source/coherence-unavailable, 0 metric-timing-withheld**. The summary describes three values, not nine zero-filled values. History and the base cohort remain unchanged. The N=1000 descriptor is an inspection request, not a change from the checkpoint's N=6 outcome.

### Why removing an ANY branch can reduce the population

The same fixture's saved common ANY group admits ten events: three satisfy the high branch and seven the low branch. Omitting the high `signal[-1] >= 900` occurrence leaves the low branch and **seven** events. This is 10→7, not automatic broadening. The independently planned omission of the only outcome is not executed: `other_outcomes requires an active outcome definition`. Both variants derive from the same saved base, all six pinned rule identities remain, and History is unchanged.

These examples refer to the original accepted `attempt_03` typed receipts, not a new documentation-time run or market-performance sample. Their exact file paths, receipt identities and source-function traceability are recorded in the task's external `DOC_COVERAGE.md`; counts from other fixtures are not combined into them.

### Troubleshooting without hiding evidence

| Observation | Interpretation and next action |
|---|---|
| No source/profile/UTC metadata | Verify the selected saved revision and completed binning/catalogue. Do not substitute another database, profile or live Artifact. |
| No supported canonical prices | Horizon role/provenance is unavailable. Inspect the reason; choosing a similarly named column is not a repair. |
| Missing/ambiguous UTC outcome or incomplete horizon | Read source, coverage and timing evidence. No zero-fill, partial outcome or latest-provider override. |
| Invalid comparison or all-compatible/other-family choice | Choose a definition valid for the root question; a different question needs a new root. |
| Invalid date or unavailable saved calendar value | Complete a representable in-envelope UTC-millisecond interval or disable the restriction; completed state remains visible. |
| Zero matches | A valid result can be zero. Inspect nonmatches, exact/tolerant support and population changes rather than hiding the rule. |
| Insufficient support or empty comparison | Descriptive evidence remains visible; an empty denominator is unavailable and low support does not earn new ranking eligibility. |
| Draft differs from visible counts | Evaluate to apply it, or activate History/reset to restore saved values. Inspection describes the completed checkpoint. |
| Cancelled/stale operation | No partial replacement is published. Let the existing runtime finish draining; then make the next explicit request. |
| Disabled action | Check that a pin, valid draft, selected rule/completed granular checkpoint or actual parent exists as required, and that incompatible work is not busy. |
| Budget/limit refusal | Read the requested/allowed bound. Clear report cache, explicitly discard an allowed leaf or choose a smaller new request; do not interpret refusal as partial success. |

### Accepted scope and deferred work

GR-06 and the UTC-tooltip correction have independent code/package acceptance. This manual does not declare native acceptance, the whole DAS or GR-07 complete. Final-source integrated selection/validation and Jack's native walkthrough remain subsequent work. Full-history profiles, adaptive analysis and overlapping events constrain every interpretation above.

Deferred work includes multi-database and multi-timeframe conditioning; new range-start, continuation and endpoint detectors; trained agents, clustering and decision trees; threshold sweeps and automatic optimization; significance, causal attribution and calibrated forecasts; prior-only GUI profiles and historical live-availability reconstruction; trading simulation; general rule editing; persistent studies/export; and ranking-policy redesign. Current inspection is not a substitute for any of them.

### Ownership and further reading

| Owner | Responsibility |
|---|---|
| Financial Tools / UTC | Independent variation/binning mathematics; unchanged trend detection, formations, continuation and episode metrics; fixed-horizon arithmetic |
| Data Manager | Validated pinned database revisions, canonical price provenance and copied UTC evidence; see [Data Manager](../data_manager_docs/DATA_MANAGER.md) |
| Analysis | Coherent evidence resolution, identity, populations, chronology, fixed-rule evaluation, counts, histories and linked reports |
| Core | Shared worker execution, cancellation and draining; see [Light V2 runtime](../core_docs/LIGHT_V2_RUNTIME.md) |
| GUI | Typed drafts, explicit actions, display time, paging, linked inspection and status; no independent numerical engine or persistent history authority |

The Research GUI is unchanged. Internal source symbols named here are implementation pointers, not newly stable public exports. See [Data Analysis Suite](DATA_ANALYSIS_SUITE.md) for the wider documentation map and [UTC classification](UTC_CLASSIFICATION.md) for exact event/family identity.
