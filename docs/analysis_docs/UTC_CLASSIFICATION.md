# UTC nonvisual trend classification

Updated: 2026-10-15. Payload schema 1.0; detector rule `utc-historical-1`.

UTC now describes how each confirmed uptrend or downtrend formed. This information
belongs to UTC and travels with its calculated result, Artifact and database
snapshot. The existing 27 UTC output columns, range calculations, chart styles,
markers, legends and plotting controls keep their existing behavior.

UTC also publishes a separate `utc_episode_metrics` report for movement,
duration, preceding context and internal pullbacks. Its evolving values do not
enter the frozen classification dictionaries described here. See
[UTC episode measurements](UTC_EPISODE_MEASUREMENTS.md) for exact formulas,
availability, incomplete outcomes and the unchanged-detector boundary.

The wider Data Analysis Suite remains incomplete and may change substantially.
This backend provides context for later investigations. It does not implement a
pattern-search GUI, trading signals, an exclusive up/down/range state, or a live
feed service. It does not change Variation & Binning labels or fit their bins.

## 1. Ownership and route

`calculate_financial_tool("UTC", ...)` calls the existing historical scanner.
An observer captures the transitions that scanner actually takes. It does not
infer formations from plotted flags or run a competing detector.

The route is:

1. UTC produces `result.analysis["utc_classification"]`.
2. Artifact storage serializes that analysis into its existing `analysis.json`.
3. A database import copies the exact contributing physical Artifact reports
   into its revision-owned `utc_classification.json` sidecar.
4. `AnalysisService.load_utc_classification(reference)` reads the exact pinned
   database revision and exposes detached report/table views.

Financial Tools performs no filesystem access. Artifacts owns Artifact bytes and
identity. Data Manager owns database transactions, copied metadata and coverage.
Analysis consumes saved evidence. The GUI remains a presentation layer.

## 2. Exact formation types

P denotes a peak and T a trough from the selected **trend** P/T dependency.
An uptrend starts at its retained trough T0; a downtrend starts at its retained
peak P0. T0 means the starting trough, not the first pullback after a rise.

A formation contains every eligible P/T event from the retained anchor through
first activation, including repeated kinds and ignored/non-confirming events
inside that span. It ends at first activation and never grows into a different
type because the trend continues.

Its key is `DIRECTION/WORD/RANKS`. Rank 0 is the lowest distinct formation price;
equal prices have the same rank. Ranks preserve all pairwise price relationships,
including those between different P/T kinds. Equality uses the scanner's exact
comparisons, with no added rounding or tolerance.

| Evidence | Key |
|---|---|
| T100, P110, P115 | `UP/TPP/0,1,2` |
| T100, P110, T105, P115 | `UP/TPTP/0,2,1,3` |
| T100, P110, T100, P115 | `UP/TPTP/0,1,0,2` |
| P120, T110, P115, T105 | `DOWN/PTPT/3,1,2,0` |
| T100, P110, T102, P108, T105, P115 | `UP/TPTPTP/0,4,1,3,2,5` |

The type excludes absolute scale, duration and distances. Those remain available
through event prices and times. There is no three-type limit, encounter-order
numbering or fixed maximum word length. Compare configurations explicitly: equal
keys from different P/T windows or assets need not have interchangeable meaning.

The twenty audited example formations remain covered, including these ten upward
forms and their downward mirrors:

| # | Upward formation |
|---|---|
| 1 | T100, P110, P115 |
| 2 | T100, P110, T105, P115 |
| 3 | T100, P110, T100, P115 |
| 4 | T100, T103, P110, P115 |
| 5 | T100, P110, P108, P115 |
| 6 | T100, P110, P110, P115 |
| 7 | T100, P110, P108, T105, P115 |
| 8 | T100, P110, T103, T105, P115 |
| 9 | T100, P110, T102, P108, T105, P115 |
| 10 | T100, P110, T105, P108, T106, P109, T107, P115 |

The test mirror exchanges P and T and maps each price to `220 - price`. These
examples demonstrate coverage; they are not permanent type IDs or a closed list.

## 3. Candidate rules and origins

For an upward candidate, before its first peak, a lower trough reselects the
anchor. Higher/equal troughs remain eligible events but do not raise that initial
floor. After the first peak, supporting troughs can hold or raise the running
floor. A later strictly higher peak activates the trend. Non-confirming peaks
at or above the running floor can remain in the formation; a swing below that
floor fails the candidate. The downward rules mirror these comparisons.

The scanner accepts the first opposite swing without an extra geometric test
and checks confirmation before the non-confirming guard. The observer preserves
that order. It imposes no additional requirement that every peak exceed every
trough in a formation. TPP and PTT are valid; an intervening pullback is optional.

| `origin` | Meaning |
|---|---|
| `initial_candidate` | Seeded in the available valid segment; makes no claim about unseen earlier history. |
| `candidate_restart` | An unconfirmed candidate failed; scanning restarted from a retained swing. |
| `post_break_restart` | A confirmed trend broke its guard; the later formation arose through a restart. |
| `direct_reversal` | The scanner's opposite activation branch switched an active trend directly. |
| `unknown` | Reserved explicit category for unavailable origin evidence; ordinary complete scans do not emit it. Legacy readers emit no episodes. |

`restart_chain` retains ordered reasons, triggering swings, restart timestamps
and the previous anchor. Reasons are `candidate_restart`, `post_break_restart`
and `anchor_reselection`. Reselecting an anchor does not reset the lineage origin.

Direct reversal examples:

- T100, P110, T105, P115 forms an uptrend. Subsequent T108, P112, T104
  directly activates `DOWN/PTPT/3,1,2,0` from the shared P115.
- P120, T110, P115, T105 forms a downtrend. Subsequent P112, T108, P116
  directly activates an uptrend from shared T105.

By contrast, T100, P110, T105, T103 first fails an upward candidate and then
forms a downtrend from P110. There was no active uptrend to reverse. Similarly,
T100, P110, T105, P115, T104, T103 uses an active-break restart, not direct reversal.

## 4. Formation versus continuation

Each episode freezes its formation, type, origin, decision frontier and first
confirmation. Separate continuation records reference its `episode_id`.

| Event `kind` | Meaning |
|---|---|
| `endpoint_extension` | The retained endpoint becomes more extreme in the trend direction. |
| `endpoint_replacement` | It moves to an equal or less extreme same-kind pivot, as allowed by the scanner. |
| `supporting_swing` | The retained structural guard changes. |
| `ignored` | The consumed event does not change endpoint or guard; it may still affect the scanner's pending reversal. |
| `guard_failure` | An active guard fails through the restart branch. |
| `termination` | The active episode ends structurally. |
| `reversal_activation` | The active episode switches through direct opposite activation. |

Each record contains its swing, actual known-at time, decision frontier and
`before`/`after` endpoint and guard. Direct reversal and guard failure also create
a termination record. The opposite formation belongs to its new episode; its
events can overlap the earlier episode's continuation history.

Episode status is `open` at the available history tail, `ended` after a structural
termination, or `interrupted` when a required-price gap ends the valid segment.
The old plotted end flag at a historical tail is not proof of structural closure.
Candidates that never activate have no confirmed episode/type.

## 5. Time and availability

All timestamps in classification are exact integer milliseconds, with null for
unknown times. They are never encoded as float32 signal columns. Keep these
distinct:

| Field | Meaning |
|---|---|
| `formation[0].ts_ms` | Retained starting pivot time. |
| `formation[0].available_at_ms` | Time that pivot could first be known as P/T. |
| `formation[-1].ts_ms` | First confirming pivot time. |
| `confirmed_at_ms` | Time all scanner evidence needed for first activation was available. |
| `decision_frontier_ms` | Latest pivot timestamp consumed to reach that decision, including restart triggers. |

With a canonical centered window `w`, a pivot at row `i` requires `w // 2`
subsequent closed bars. For a five-bar window, pivots at rows 2, 6, 10 and 14
become available at the actual closing times of rows 4, 8, 12 and 16. The trend
type first becomes knowable at row 16's close, not at T0 or T0's availability.

Scanner rewinds never rewind the decision clock. A later failure can trigger
reprocessing of earlier pivots; the resulting formation cannot be backdated
before that failure became known. Unknown evidence propagates conservatively
through the segment instead of inventing a confirmation time.

`availability_status` is `known` when a timing basis was supplied, otherwise
`unknown`; individual supplied swing times may still be null.
`availability_reason` distinguishes `canonical_centered_window`,
`explicit_swing_availability`, `no_verified_availability_context`, and the legacy
reader's `legacy_payload_absent`.

Data Manager and Research know that accepted OHLCV timestamps denote bar opens.
They derive closing times from the canonical market timeframe: fixed duration
for fixed intervals, calendar month arithmetic for monthly intervals. Fractal
availability then indexes the **actual** later bars; gaps are not treated as
imaginary regularly spaced rows. Standalone callers supply their own verified
close times, including close-stamped or externally delayed sources.

## 6. Context and replay API

`UtcClassificationContext` is frozen and accepts:

| Field | Contract |
|---|---|
| `stream_id` | Optional nonempty stable stream/configuration namespace. |
| `input_revision` | Optional nonempty source revision identifier. |
| `dependency_ids` | Tuple of unique nonempty provenance identifiers. |
| `bar_closed_at_ms` | Optional strictly increasing integer tuple, one per input row, not before its timestamp. |
| `swing_available_at_ms` | Optional integer/null tuple, one per row, not before the pivot's bar close. |
| `canonical_window` | Optional 3/5/7/9/11; requires close times and excludes custom swing availability. |

Canonical timing verifies selected P/T values against the canonical calculation
and selected trend window. Names alone do not establish provenance. Explicit
custom availability is caller-supplied evidence; known eligible swing delivery
must be chronological. Out-of-order delivery requires a new reviewed revision.

```python
from leonardo.financial_tools import (
    UtcClassificationContext, calculate_financial_tool,
    get_utc_classification, classify_utc_as_of,
)

# data contains OHLCV, the trend P/T columns, and the range P/T columns.
parameters = {"peak_column": "peak_fractal_5",
              "trough_column": "trough_fractal_5"}
context = UtcClassificationContext(
    stream_id="bybit/linear/BTCUSDT/1m/my_utc",
    input_revision="reviewed-source-revision",
    bar_closed_at_ms=tuple(int(t) + 60_000 for t in data.ts_ms),
    canonical_window=5,
)
result = calculate_financial_tool("UTC", data, parameters, utc_context=context)
report = get_utc_classification(result)
episodes = report.to_episode_frame()
events = report.to_event_frame()
causal = classify_utc_as_of(data, parameters, context=context, as_of_ms=cutoff_ms)
```

Only use the example's 60,000-ms close conversion for verified one-minute
open-stamped bars. `utc_context` is rejected for other Financial Tools.

Replay keeps closed rows through the cutoff and masks unknown/future P/T events
before invoking the same historical rules. Independent range P/T dependencies
are verified and masked with their own window. Replay returns a classification
report, not a streaming engine or a newly plotted chart. An empty closed prefix
has empty episode/event lists. Unknown timing cannot support an as-of request.

## 7. Result fields and identity

The root has exactly `schema_version`, `rule_version`, `status`, `context`,
`parameters`, `timestamps_ms`, `input_key`, `identity_scope`, `as_of_ms`,
`availability_status`, `availability_reason`, `episodes`, and `continuations`.
Status is `retrospective`, `as_of`, or the reader-only `legacy_unavailable`.

Each swing has `kind`, `position`, `ts_ms`, `value`, `available_at_ms`.
Each episode has `episode_id`, `direction`, `segment_start_ms`, `formation_key`,
`formation`, `origin`, `restart_chain`, `predecessor_episode_id`, `shared_pivot`,
`confirmed_at_ms`, `decision_frontier_ms`, `status`.
Each continuation has `event_id`, `episode_id`, `kind`, `swing`, `known_at_ms`,
`decision_frontier_ms`, `before`, `after`.

Episode identity hashes the stream namespace (or input-local key), canonical
parameters, rule version, segment start, direction and retained anchor timestamp.
Appending evidence to the same identified stream preserves existing episode IDs.
`input_key` also binds the supplied frame, its columns, context and parameters.
It changes with input revisions; it is not a market identity or a security proof.
Without a stream namespace, IDs are intentionally local to that input.

Tables use object-typed cells to preserve integers/nulls. The episode table adds
`starting_pivot_ms`, `starting_available_at_ms`, `confirming_pivot_ms`, and
`interpretation="retrospective_membership"`; the full formation remains available
through `report.episodes`. All returned containers are defensive copies.

Models reject unknown versions/fields, invalid timelines, conflicting rank keys,
invalid predecessor/shared-pivot relations and times before required evidence.
Every referenced swing's availability must agree with its declared timing basis:
the actual later bar close for a canonical window, the explicit custom value,
or null when no verified basis exists. This includes restart triggers and anchors,
shared pivots, and continuation endpoint/guard states. The canonical window must
match the selected trend dependency. Confirmation and continuation availability
also include the actual decision frontier's availability; its pivot timestamp
alone is insufficient. Required unknown evidence cannot support a known time.
Current result validation also binds report parameters and timeline to the
actual Financial Tool frame. Empty legacy analysis is a separate accepted state;
a malformed current payload cannot fall back to it.

Standalone UTC retains its existing numeric-or-null input policy. Coercible
numeric strings in sparse P/T columns use the same numeric validation as other
UTC inputs, without changing the caller's frame or the detector's price precision.

## 8. Artifact and database persistence

Artifacts use the existing analysis checksum and identity mechanism. Adding
classification can create a new physical Artifact ID even when all 27 values are
identical. Old empty-analysis Artifacts keep their original bytes and identities.
Research restores their stored result directly and retains strict linked-result
comparison; it does not strip current analysis to make a comparison pass.

On an explicit managed update, the new UTC report records the reviewed current
physical dependency references used for the calculation. These agree with the
new Artifact recipe, including when the P/T Artifact has just been replaced.
Previously saved Artifacts and copied database reports retain their own evidence;
they are not rewritten to follow the current dependency head.

Database V6 retains V4/V5 physical-value provenance and incomplete legacy forms,
adding this descriptor to the identity-bearing manifest:

```json
{"utc_classification": {
  "schema_version": "1.0",
  "filename": "utc_classification.json",
  "sha256": "<64 lowercase hexadecimal characters>"
}}
```

The sidecar is canonical JSON with `schema_version`, `reports`, `associations`.
Reports are deduplicated by the Artifact analysis serialization hash and contain
the exact analysis mapping. `{}` means a legacy provider has no classification.
Every association has `artifact_id`, `logical_artifact_id`, `column_name`,
`output_name`, `first_timestamp_ms`, `last_timestamp_ms`, `report_sha256`.
Associations must match the actual UTC output-provider segments exactly. A single
physical provider cannot claim conflicting reports. Its full report can include
formation anchors before the segment it supplied; that is context, not additional
value coverage.

Only selected UTC outputs carry a UTC context. A UTC Artifact used solely as a
dependency of another selected construct does not become an implicitly selected
UTC instance. Different instances, aliases and physical versions remain separate.

Manifest, values and sidecar are validated, staged and flushed in one existing
publication transaction. Reviewed evidence/cancellation is checked again before
publication; head failure rolls back newly owned files. Loads enforce the exact
schema-specific file set and checksums and never consult source Artifacts.

| Operation | Result |
|---|---|
| Direct/Collection import | Copy exact reviewed UTC provider reports. |
| Seed-only/non-UTC build | No fabricated metadata or forced V6 migration. |
| Partial output removal | Retain reports used by surviving UTC outputs. |
| Last UTC output removal | New revision has no UTC sidecar; older revision remains intact. |
| Append | Preserve old bytes/reports and associate the suffix with its new physical provider. |
| Replacement | Use existing reviewed removal/import or a new database build; values and metadata publish together. |
| Read/delete | Read copied evidence independently; database deletion owns its declared sidecar. |

The existing database rebuild command is retired and remains rejected. This
patch does not revive it. Conflicting already-confirmed formation facts reject
append and require an explicit replacement/new-build review. A newly confirmed
formation may begin earlier than the suffix; open episodes may later end without
changing their frozen formation. No API silently merges provider reports.

V1–V5 database loading writes nothing and reports no copied classification.
Retaining an old physically attributed UTC segment during an explicit edit does
not enrich it from a live Artifact: its missing report remains `{}`. Unknown
legacy provider identities remain unknown. Recalculation/import is explicit.

## 9. DAS consumption and research interpretation

```python
bundle = analysis_service.load_utc_classification(database_reference)
coverage = bundle.associations_frame()
report = bundle.report(physical_artifact_id)  # None for a legacy empty report
```

The reference binds database ID, revision ID and values hash. `bundle.status`
states whether a copied sidecar is available (`available`) or absent
(`legacy_unavailable`); inspect each report for its actual classification and
timing availability. An available sidecar can still contain legacy empty reports.

To study construct labels at T0, count episode starts and join each episode's
starting-pivot timestamp to the chosen database values. A future-confirmed type
is a retrospective outcome. It is not an input known at T0. Causal use also
requires availability-aware construct values and bin profiles fitted before the
decision cutoff; a whole-database descriptive fit alone does not establish this.

DAS now exposes this retrospective workflow in **Trend Start Patterns**. Select
one completed binning run and one logical copied UTC instance. T/up_start uses
UP formations; P/down_start uses DOWN formations. The retained `formation[0]`
provides T0/P0. Exact `formation_key` values remain separate, including repeated
P/T events and equal-price rank distinctions. Optional origin and anchor-date
filters do not refit or mirror the construct labels.

The Analysis consumer checks classification-bearing provider intervals and
exact database timestamps before counting an event. Known confirmation is owned
by the first actual report close at or after `confirmed_at_ms`; unknown timing
uses the structural frontier for coverage only. Repeated physical-provider
witnesses are reconciled by frozen formation facts, with conflicts rejected.
Continuation and status remain attached to their original witnesses. Generic
P/T populations and endpoint/termination roles are not included implicitly.

See [Trend Start Patterns](TREND_START_PATTERNS.md) for coverage rules, ordinary
timestamp controls, per-pattern denominators, the five GUI views and worked
counts. UTC remains the classification authority: this consumer adds no UTC
output, persisted field or plotting change.

Classification strings, IDs and times remain outside numeric binning selection.
Range flags can coexist with directional episodes. Sparse NaN P/T cells do not
split a segment; ambiguous simultaneous finite P/T rows are skipped; invalid
required-price rows split it. No missing pivots are invented or interpolated.

## 10. Verification and maintenance

Focused coverage is in the `test_utc_classification*` Financial Tools, Artifact,
Data Manager, Analysis and GUI tests, plus
`test_research_utc_classification_compatibility.py`. It covers exact formations,
origins, reselection, continuation, windows 3–11, replay, legacy/current storage,
aliases, append, independent copies, corruption, rollback and unchanged rendering.
The implementation audit package also compares the preserved original scanner
against deterministic and randomized inputs and includes native before/after
chart captures. Independent package audit and user acceptance remain distinct.
