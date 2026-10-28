# Research Suite data and interface contracts

**Updated:** 2026-10-08. Companion to [scope](RESEARCH_SUITE.md),
[architecture](RESEARCH_ARCHITECTURE.md) and [lifecycles](RESEARCH_LIFECYCLES.md).

This document specifies the data required at each Research boundary, the
algorithms needed to reproduce behavior, and observable acceptance criteria.
Runtime records below are internal models, not new durable schemas or public
service APIs. Persisted formats retain their existing versions and owners.

## 1. Common identity, time and value rules

`MarketId` consists of `exchange`, `market_type`, `symbol`, `timeframe`. Use the
canonical MarketId implementation and timeframe/storage-segment conversion.
Different timeframes are different markets even if exchange/symbol match.
Do not substitute a chart title, CSV path, display name or tuple missing timeframe.

Persisted Research IDs match `^[a-z0-9][a-z0-9_.-]*$`; hashes are exactly 64
lowercase hexadecimal characters. Research pool IDs normally have prefixes
`env_`, `snapshot_`, `notebook_` followed by a generated UUID hex value.
Their content hashes change with saved content; the pool ID remains stable on
Update. Display names are nonempty, already trimmed text. Descriptions may be
empty. Store duplicate-name checks use case folding against other valid objects.

Created/updated times are timezone-aware UTC; update must not precede creation.
JSON output uses their ISO-8601 representation. Dataset and annotation positions
are integer UTC milliseconds; never local wall time. Notebook row timestamps
must be nonnegative; an untimed Note uses null. A Snapshot viewport timestamp is
an integer and may describe a historical axis outside that Notebook restriction.
An integer field does not accept a boolean as an integer.

Finite numerical values retain full internal precision. Research comparison
tests normally use absolute tolerance 0.00005 and relative tolerance zero for
continuous calculations. Identity, output names/order, NaN placement, categorical
values, booleans, dependency edges and durable schemas remain exact. Tolerance
does not permit altered source fingerprints or rounded persisted values.

## 2. Accepted dataset and immutable projections

Canonical source files are:

```text
historical_data/<exchange>/<market_type>/<symbol>/<timeframe-segment>/ohlcv/
  candles.csv
  candles.meta.json
```

The normal Research catalog verifies canonical storage identity; both files
exist; sidecar parses and agrees with MarketId; persistence status is `committed`
or `repaired`; validation status is `ok`; row count is positive; current CSV
SHA-256 matches accepted evidence; the file does not change while inspected.
Rejections carry a code and reason and never become selectable accepted rows.
Shared metadata-only catalog helpers exist for DMS checks; they do not replace
the strict Research catalog/load path.

An `AcceptedDatasetSummary` describes market, source paths and accepted evidence.
`HistoricalDataset` adds immutable tuples `ts_ms`, `open`, `high`, `low`, `close`,
`volume`, plus `csv_path`, `file_sha256`, `row_count`, `first_timestamp_ms`,
`last_timestamp_ms`. All arrays have `row_count` elements on the same axis.

Load rechecks admission before cache reuse. On parsing it requires the canonical
CSV header, nonempty complete rows, strictly increasing timestamps, finite OHLCV,
`high >= low`, `high >= max(open, close)`, `low <= min(open, close)` and nonnegative
volume. It checks the full file hash, row count and first/last timestamps against
the accepted summary and detects CSV/sidecar changes during loading. It does not
invent candles to fill gaps or rewrite the source. The canonical validator owns
acceptance; these loader checks defend the read boundary.

The loader's default cache holds four immutable datasets and serializes loads
per MarketId. It reuses only matching current accepted evidence. Progress is
reported at the configured row interval (default 10,000). A chart holding a
previous dataset is not mutated when a cache entry is evicted or invalidated.

`ResidentOHLCVSlice` has `market_id`, `dataset_fingerprint`, `base_index`,
`end_index_exclusive`, six column tuples, `has_more_left`, `has_more_right`,
`first_timestamp_ms`, `last_timestamp_ms`. Its range is half-open and nonempty;
every tuple length equals end minus base. Local index `j` maps to global index
`base_index + j`. Full calculation results remain outside this disposable slice.

Resident defaults: visible maximum 2,000, left buffer 1,500, right buffer 1,500,
target size 5,000, LRU capacity 128 slices. The cache key is MarketId + full-data
SHA-256 + start/end. Observing a new fingerprint drops cached slices for the old
fingerprint of that market.

For a real-data center `c`, use `left = buffer_left + floor(visible_max/2)` and
`right = buffer_right + visible_max - floor(visible_max/2)`. Start with
`[c-left, c+right)`, clamp center to a real row, and shift any overflow at either
dataset boundary to the opposite side before clamping to `[0, row_count)`.
Smaller datasets produce smaller slices, not synthetic rows. Timestamp lookup
uses binary search for the nearest candle, chooses the earlier one on equal
distance, and clamps outside coverage to the first/last candle.

## 3. Session publication and Study records

Dataset opening, refill, Apply, Edit and Save have correlated attempt records.
Session ID identifies the owner; generation identifies the loaded dataset epoch;
request/task IDs identify an attempt; Study attempts additionally carry Study ID,
MarketId and dataset fingerprint. A result is publishable only into that exact
current context. Cancellation/disposal/supersession removes its acceptance right
even if the worker later finishes. Do not key acceptance only by slot number.

`StudyExecutionRequest` contains `tool_key`, parameter mapping, ordered
`input_sources`, optional `display_name`, and `user_metadata`.
`StudyArtifactRequest` contains `kind`, `tool_key`, exact `artifact_id`, optional
display name and metadata. `PreparedStudy` wraps a fully prepared `ChartStudy`.

| `StudyInputSource.source_kind` | Required identity in addition to `role` | Other kind-specific fields |
|---|---|---|
| `ohlcv` | `column_name`: open/high/low/close/volume | Null |
| `study` | `study_id`, `output_name` | Null |
| `artifact` | `artifact_kind`, `artifact_tool_key`, `artifact_id`, `output_name` | Null |

The general OHLCV enum is not permission to use raw Volume in a Construct: the
tool's source eligibility imposes the narrower rule. Source Study identity must
belong to the same session/generation, MarketId, full fingerprint and timestamp
axis. Artifact input must pass current-lineage and output-semantic validation.
Private binding aliases used by calculation are derived from roles, not user
columns or another persisted identity.

Role schemas are fixed by the tool: derivative/angle use `source`; delta uses
`fast, slow`; braids/braid_instability use `fast, mid, slow`; trap_area permits
`fast, slow` or `fast, mid, slow`; multi-source constructs use contiguous ordered
`source_1..source_n`. Universal Trend Classifier uses `trend_peak`, `trend_trough`,
`range_peak`, `range_trough` referencing exact Peaks & Troughs outputs for its
resolved windows. Family compatibility and analysis-usable flags are checked;
arbitrary visually similar lines are not interchangeable sources.

`ChartStudy` contains:

| Fields | Meaning |
|---|---|
| `study_id`, `session_id`, `generation`, `market_id`, `dataset_fingerprint` | Exact runtime ownership and source epoch |
| `source_kind` | `calculation` or `artifact` |
| `display_name`, `user_metadata` | User-facing metadata, not formula identity |
| `result` | Complete `FinancialToolCalculationResult` with tool, resolved parameters/bindings, output schema, full timestamp axis, values and optional analysis |
| `setup_request` | Definition used for Environment capture; calculation request or Artifact request |
| `edit_request` | Calculation request usable for parameter editing, including reconstruction of Artifact-backed inputs |
| `source_studies` | Ordered `(role, study_id, output_name)` runtime dependency references |
| `source_artifacts` | Canonical durable Artifact source references |
| `saved_link` | Null or `(kind, tool_key, recipe_id, artifact_id)` |
| `pane_role`, `renderable_output_names`, `style_driver_output_names`, `analysis_usable_output_names` | Derived presentation/use roles, distinct from numerical result identity |

Save returns `StudySaveOutcome(study_id, saved_link, created)`. The link records
what was saved, not permission to mutate that Artifact later. Edit creates an
unsaved replacement result under the existing Study ID and clears that link.

Metadata fields are `important` (boolean, default false), `dataset_role` (default
`unspecified`), and `description` (default empty). Allowed roles are
`unspecified`, `core_geography`, `volume`, `braid`, `peaks_troughs`, `utc`,
`supporting_indicator`, `supporting_oscillator`, `supporting_construct`,
`helper_dependency`, `experimental`, `visual_only`. They describe use, not a
different formula or a new Database ownership relationship.

## 4. Study presentation and pane contracts

Runtime `StudyPresentation` is keyed by Study ID, with visibility, pane ID,
signal/fill/guide style mappings, revision and tool key. Background-region styles
also exist as runtime presentation. A revision invalidates rendering, not the
financial result. Durable Environment presentation saves visibility, line/fill
styles and optional guides; it does not serialize all runtime renderer fields
or the background-region mapping as a separate durable field.

| Saved style | Fields and constraints |
|---|---|
| Line | `output_name`, `color`, `line_width`, `line_pattern`, `visible`, `render_mode`, `marker_shape`, `marker_size`, `conditional_driver_name`, `conditional_colors` |
| Fill | `fill_id`, `upper_output_name`, `lower_output_name`, `color`, `opacity`, `visible`, `conditional_driver_name`, `conditional_colors` |
| Guide | `guide_id`, `kind`, `value`, `color`, `line_width`, `line_pattern`, `visible` |

Colors are uppercase `#RRGGBB`. Width is finite 0.5..5.0. Patterns are `solid`,
`dashed`, `dotted`. Render mode is `line` or `marker`. Marker shapes are `none`,
`circle`, `square`, `triangle_up`, `triangle_down`, with integer size 4..24.
Opacity is finite 0..1. Guide kinds are `overbought`, `oversold`, `center`, `zero`;
value must be finite. Conditional colors map exact driver states to colors.
Line outputs and fill boundaries must refer to declared outputs. A nonempty guide
list must exactly match the tool's canonical guide IDs/kinds/order. Missing legacy
guide lists remain readable and receive applicable defaults during presentation.

The price pane is always first. The base volume pane is distinct from an applied
Volume Study. Oscillator Studies own separate panes; their order is view state.
All panes share the same horizontal camera, with the bottom eligible pane owning
the time axis. Price overlays, oscillator ranges, guides, conditional HCK rendering
and Peaks & Troughs markers follow the Financial Tool visual specification and
Research presentation defaults. NaN regions create gaps, not connecting fabricated
values. Crosshair and Notebook annotations remain dynamic overlays.

Fill upper and lower output names must differ. Styles do not belong in Artifact
numerical identity. A Snapshot preserves pane
order/sizes using references to embedded Environment entries, not runtime pane IDs.

## 5. Persisted Research stores

| Pool | File | Schema/object type |
|---|---|---|
| Study Environment | `study_environments/<environment_id>.json` | `1.0` / `study_environment` |
| Workspace Snapshot | `workspace_snapshots/<snapshot_id>.json` | Current `1.1`, reads `1.0` / `research_workspace_snapshot` |
| Notebook | `research_notebooks/<notebook_id>.json` | `1.0` / `research_notebook` |

All three stores use locks and safe contained paths; links/junctions and unsafe
paths are refused. Create refuses existing identity/name. Update retains identity
and created time and writes a new update time/hash. Write a unique temporary file
in the same root, flush and fsync, then atomically replace the destination; clean
up the temporary file on failure. This protects each file replacement and does
not make several pool mutations one crash-atomic database transaction.

JSON is UTF-8, sorted keys, compact separators `,` and `:`, `ensure_ascii=False`,
and `allow_nan=False`. Content hash is SHA-256 of that compact payload **without
the `content_hash` member and without a trailing newline**. Environment files
contain compact JSON without a newline. Snapshot and Notebook canonical files
include one trailing newline. Pretty-printed examples below are for reading;
use each model's canonical serializer for store bytes. The stores compare bytes
to canonical serialization on load, so arbitrary pretty-printing of real saved
files is not a harmless edit.

Lists return summaries sorted by case-folded display name and identity. Invalid
files can appear as invalid summaries with reasons; a list does not silently
repair, migrate or discard their bytes. Exact load fails clearly on invalid
schema/hash/identity/encoding. Deletion remains explicit and uses contained paths.
Do not assume that reading a file grants permission to normalize it.

## 6. Study Environment schema

Root fields: `schema_version`, `object_type`, `environment_id`, `content_hash`,
`display_name`, `description`, `created_at_utc`, `updated_at_utc`, `created_from`,
`entries`. `created_from` is null or the four-field MarketId object. `entries`
must contain at least one valid entry, with unique entry IDs in dependency order.

Each entry has exactly the defined semantic fields:

| Field | Contract |
|---|---|
| `entry_id` | Canonical ID local to this Environment |
| `mode` | `calculation` or `artifact` |
| `kind`, `tool_key` | Canonical Financial Tool kind/key agreement |
| `display_name` | Nonempty trimmed text |
| `parameters` | JSON-safe fully canonical calculation parameters, excluding selectors owned by explicit sources |
| `sources` | Ordered source descriptors with unique roles |
| `artifact_id` | Exact saved Artifact SHA-256 for Artifact mode; null for calculation mode |
| `expected_output_names` | Nonempty, unique, ordered outputs; calculation mode must resolve to exactly these names |
| `user_metadata` | `important`, `dataset_role`, `description` |
| `presentation` | `visible`, `line_styles`, `fill_styles`, optional nonempty `guide_styles` |

Artifact-mode entries require empty parameters/sources and a valid Artifact ID.
Calculation-mode entries must not have an Artifact ID. An entry that was calculated
and later saved still retains its calculation setup; save status alone does not
convert it into Artifact mode.

Each source object serializes all eight members: `role`, `source_kind`,
`column_name`, `source_entry_id`, `artifact_kind`, `artifact_tool_key`,
`artifact_id`, `output_name`. Unused members are null.

| Kind | Non-null members besides role/kind |
|---|---|
| `ohlcv` | `column_name` |
| `environment` | `source_entry_id`, `output_name` |
| `artifact` | `artifact_kind`, `artifact_tool_key`, `artifact_id`, `output_name` |

Environment sources must name an earlier entry and valid analysis-usable output;
no forward reference or cycle is accepted. Tool role/family rules still apply.
Artifact sources must agree with their tool kind, output and current lineage.
An Environment containing any Artifact reference requires exact `created_from`
MarketId when applying; calculation-only definitions can be reused on another
accepted dataset. Legacy excluded tools can be read for compatibility reporting
but are not thereby admitted to Research application.

The schema deliberately excludes session/Study/task IDs, chart slots, viewport,
detached state, caches and complete numerical arrays. A standalone pool
Environment and its embedded copy in a Snapshot have independent lifetimes.

## 7. Workspace Snapshot schema

Root fields: `schema_version`, `object_type`, `snapshot_id`, `content_hash`,
`display_name`, `description`, `created_at_utc`, `updated_at_utc`, `workspace`,
`charts`, and (schema 1.1) `notebook_id`.

`workspace` contains `visualization_mode` (`scroll_4` or `fit_8`),
`pan_anchor_enabled` (boolean), and `active_chart_ref` (must exist in charts).
`charts` contains 1..16 entries in ascending workspace-position order; chart
references and positions are unique. A Snapshot cannot represent an empty Suite.

| Chart field | Contract |
|---|---|
| `chart_ref` | Canonical identifier within this Snapshot |
| `workspace_position` | Integer 1..16; independent of runtime slot ID |
| `detached` | Boolean |
| `market_id` | Canonical four-field identity |
| `viewport` | `center_timestamp_ms` integer; `visible_count` positive integer |
| `price_scale` | `autoscale_enabled`, `manual_low`, `manual_high`; automatic mode requires null bounds; manual mode requires finite numeric low < high |
| `volume_visible` | Boolean |
| `pane_sizes` | Nonempty ordered objects `{pane_ref, size}` with unique refs and positive integer sizes |
| `study_environment` | Full embedded Environment object, or null when no Studies |

Pane references start with `price`, may next include `volume`, then use
`study:<entry_id>` for existing oscillator entries in the embedded Environment.
The Snapshot stores pane sizes/order, not runtime pane objects. Viewport capture
clamps a padding-only center to a real candle before storing its timestamp.
Restoration maps that timestamp against the current accepted dataset; it does
not preserve old file bytes or require historical session identity.

`notebook_id` is null or a canonical pool ID, not embedded Notebook content.
Schema 1.0 omits that member entirely and cannot contain an assignment. Reading
1.0 does not rewrite the file. Newly built/updated Snapshots use 1.1. The increase
to 16 charts did not change the schema version; older builds limited to eight
cannot load a larger Snapshot. Capacity is not a silent migration policy.

The root and nested Snapshot parsers validate expected key sets and content
hash. A compatible saved format is separate from runtime preflight: a structurally
valid Snapshot can still be blocked by absent data, stale Artifact lineage,
Notebook absence, busy state or capacity.

## 8. Notebook schema and annotations

Root fields: `schema_version`, `object_type`, `notebook_id`, `content_hash`,
`display_name`, `description`, `created_at_utc`, `updated_at_utc`,
`annotation_settings`, `pages`. Zero to 64 pages are allowed. A Notebook does
not contain a list of owning Snapshots.

`annotation_settings` contains booleans `show_points_of_interest` and
`show_potential_trades` (both default true), and integer offsets `poi_offset_px`
(default -28), `long_offset_px` (56), `short_offset_px` (-56), each -200..200.

Each page has `market_id`, `notes`, `potential_trades`, `points_of_interest`.
Pages are canonicalized in MarketId order and markets are unique. Row IDs must
be unique across the entire Notebook, not just within one table/page.

| Row family | Fields and validation |
|---|---|
| Note | `row_id`; `timestamp_ms` null or nonnegative integer; `text` nonempty trimmed string |
| Potential Trade | `row_id`; required nonnegative `timestamp_ms`; `direction` long/short; `entry_price`, `target_price`, `stop_price` null or positive finite numbers; `status` planned/open/closed/cancelled; `outcome` pending/win/loss/breakeven; `note` string that may be empty |
| Point of Interest | `row_id`; required nonnegative `timestamp_ms`; `price` null or positive finite number; nonempty trimmed `title`; `description` string that may be empty |

Untimed Notes sort first, then timestamp and row ID. Trades/Points sort by
timestamp and row ID. A trade row is a record of the user's observation; these
fields do not imply broker order validation, financial outcome calculation or
an automatic status transition. There is no trading engine behind the table.

Annotation projection uses the exact page MarketId. Plain Notes are not plotted.
Trade annotations have kinds `trade_long`/`trade_short`, labels `L`/`S`, and
optional entry-price anchor; Points use kind `poi`, label `+` and optional price.
The projection carries `annotation_id = notebook_id + ':' + row_id`, notebook
and row IDs, market, timestamp, kind, anchor price, label, title, tooltip and
pixel offset. The chart supplies placement when an explicit price is absent.
Preview uses the editor's last valid draft and is suspended during restore.
Annotation projection never changes a financial result or persistence.

## 9. Artifact and external service boundaries

Research does not redefine Artifact/Portable Recipe schemas. The required durable
Save contract is: consume exact complete result + MarketId + resolved parameters/
bindings + source references; validate current OHLCV evidence; return canonical
saved identity and truthful creation/reuse outcome; publish through existing
managed authorities. Read/apply must validate market, fingerprint, timestamp axis,
values integrity, source lineage and output roles before accepting stored values.

Market-bound recipe files live under
`historical_data/<market>/recipes/<kind>/<tool_key>/<recipe_id>.json`; calculation
payloads under `artifacts/<kind>/<tool_key>/<artifact_id>/` contain `values.csv`,
`artifact.meta.json` and optional `analysis.json`. Managed versions live under
the same market's `artifact_versions/`; Portable Recipes under
`data_manager/recipes/`. The [DMS manual](../data_manager_docs/DATA_MANAGER.md)
specifies global definition, version, collection and Database semantics.

Financial Tool calls return full-axis typed results, not just plotting arrays.
Canonical specs resolve defaults, valid ranges, roles, output names/order, pane
mode, analysis eligibility and style drivers. All 25 Research tool names and
their categories are in the scope manual. Rebuilding Research uses that service
contract; implementing Leonardo's numerical library from scratch additionally
requires its canonical tool specifications and calculation acceptance fixtures.
This distinction prevents a Research manual from creating competing formulas.

## 10. Exact chart layout and camera rules

Order attached charts by reserved workspace position; ignore holes for layout,
but do not erase reservations or renumber session IDs. Two equal-width columns
are available. Rows below are ordered top to bottom; `full` spans both columns.

| Attached count in a group | Rows |
|---|---|
| 0 | Empty-state view |
| 1 | full |
| 2 | pair |
| 3 | full, pair |
| 4 | pair, pair |
| 5 | pair, pair, full |
| 6 | pair, pair, pair |
| 7 | pair, pair, pair, full |
| 8 | pair, pair, pair, pair |

**Fit 8:** 0..8 use one group, no vertical scrollbar, minimum content-height
ratio 1. More than eight uses first eight + remaining charts as separate pages;
apply the table independently to each page. Both page hosts have at least one
viewport height; overall content minimum is twice viewport height plus the
existing 2-pixel page spacing. Vertical scrolling is enabled as needed. The
second page's small count fills that page using its own row count, not eight
uniform miniature slots. Compact panel density is selected when that page has
at least three rows. At most sixteen total charts are allowed.

**Scroll 4:** retain the same general adaptive positions in one scrolling layout.
For counts >=4 place pairs in row order and let the last chart span both columns
for odd counts >=5. Minimum height ratio is `max(1, row_count / 2)` and vertical
scrolling is as needed. Mode changes/detach/dock must explicitly keep reparented
panels visible. All-detached state shows its distinct empty-workspace message.

The horizontal camera domain is `[-left_padding, dataset_count+right_padding)`.
Defaults: 1,000 padding each side, visible count 500, allowed visible count
20..2,000 bounded by domain size. Initial latest alignment places the last real
candle at the right edge. Start is clamped so the complete visible window remains
inside the domain. Crosshair indices are chart-space indices; padding is not data.

Zoom in uses `int(count*0.8)` bounded by the minimum; zoom out uses
`max(count+1, int(count*1.25))` bounded by maximum. Retain the anchor's screen
fraction: require a numeric fraction in 0..1 and clamp the anchor to domain, calculate
`anchor_position = round(fraction * max(1, new_count-1))`, then clamp
`start = anchor-anchor_position`. Centering uses `center-floor(count/2)` then
clamps. Timestamp resolution remains in the session, not a second viewport index.

Resident refill tests the real-data intersection of the camera, not empty
padding. Request more on a side only when that side has more data and the camera
is outside or within the default 250-row threshold. Competing nearby edges are
resolved by choosing the smaller distance; on equal distances choose left when
the interest center is at or before the resident center, otherwise right. Refill
completion must match
the active resident request before replacing projections.

## 11. Observable acceptance matrix

The following are reconstruction criteria, not an invitation to expand product
scope. Tests named here are under `tests/` in the repository. The production
composition and generated data must be used for lifecycle integration checks.

| Contract | Required observations | Executable evidence |
|---|---|---|
| Admission/loading | Missing/stale/nonaccepted evidence refused; current full axis/hash accepted; cancellation and changed-file checks | `research_test/test_accepted_dataset_catalog.py`, `test_full_historical_dataset_loader.py` |
| Resident/camera | Correct edges, nearest timestamp tie, padding, range, refill and identity | `research_test/test_resident_slice_service.py`, `test_horizontal_viewport.py`, `test_chart_session_state.py` |
| Session isolation | Same-market charts remain independent; old generations/results cannot publish | `research_test/test_research_workspace_state.py`, `gui_test/test_research_multi_chart_integration.py` |
| Capacity and layout | 1..16 accepted, 17 refused; original 0..8 rules preserved; Fit 8 second-page interaction and reparenting | `gui_test/test_research_sixteen_chart_pages.py`, `test_research_workspace_layout.py`, `test_research_gui_visual_freeze_geometry.py` |
| Study calculation | Full-axis values, exact NaNs/outputs/lineage; excluded tool refusal | `research_test/test_study_execution.py`, Financial Tools fixtures/tests |
| Edit/dependencies | Block live dependents; retain old result on failure; retain ID/style on success, clear saved link | `research_test/test_study_edit.py`, `test_study_dependencies.py` |
| Save/publication | No recalculation, saved sources required, source fence and managed/portable publication | `research_test/test_study_artifact_apply_save.py`, `test_study_managed_artifact_publication.py` |
| Environment | Canonical hash/round trip; topological entries; compatibility; partial-run rollback/cancellation | `research_test/test_study_environment_models.py`, `test_study_environment_store.py`, `test_study_setup_service.py`, active Research GUI Environment tests |
| Snapshot | 1.0/1.1 compatibility; exact nested state; position/capacity plan; Replace rollback and Append preservation | `research_test/test_workspace_snapshot_models.py`, `test_workspace_snapshot_service.py`, `test_workspace_snapshot_store.py`, `gui_test/test_research_gui_service_workspace_lifecycle.py` |
| Notebook | Row/page validation/order; dirty draft vs saved object; annotation market isolation | `research_test/test_research_notebook_models.py`, `test_research_notebook_service.py`, `test_research_notebook_store.py`, active Notebook GUI tests |
| Link/deletion | Assign idempotency, stale unassign refusal, shared references, coordinated delete and rollback failure reporting | `research_test/test_workspace_notebook_link.py`, `test_research_notebook_application.py` |
| Composed dirty transitions | Save/Discard/Cancel before teardown; main/suite tracking; source catalog freshness; restore/Manager ordering; Save -> Clear and genuine conflict | `gui_test/test_research_composed_transition_guards.py` |
| Late completion and shutdown | Fenced durable save truthful after Qt owner deletion; stale callback dropped; fresh reopen | `gui_test/test_research_composed_transition_guards.py`, `test_research_gui_service_shutdown.py` |
| Leonardo integration | Actual restored composition, Maintenance -> Research, DMS Notebook shortcut and shared authorities | `gui_test/test_research_main_application_composition.py`, `test_download_maintenance_research_workflow.py` |

Minimum lifecycle scenarios also include deletion versus removal and surviving
references from the lifecycle matrix. No test may use real saved user roots.
Native validation checks real Qt behavior, pane visibility, page scrolling and
close/reopen; offscreen tests alone do not establish visual acceptance.

## 12. Format examples

The examples below are complete model payloads with computed hashes, validated
against the current parsers. IDs and observations are illustrative generated
data. A successful model parse does not assert that referenced OHLCV or a Notebook
exists in a user's installation; runtime preflight makes that separate check.
Serialize with each model's canonical serializer before writing store files.

### Study Environment 1.0

```json
{
  "schema_version": "1.0",
  "object_type": "study_environment",
  "environment_id": "environment_example",
  "display_name": "Example moving average",
  "description": "Reusable calculated Study definition",
  "created_at_utc": "2026-10-08T00:00:00+00:00",
  "updated_at_utc": "2026-10-08T00:00:00+00:00",
  "created_from": {
    "exchange": "bybit",
    "market_type": "linear",
    "symbol": "BTCUSDT",
    "timeframe": "1m"
  },
  "entries": [
    {
      "entry_id": "entry_001",
      "mode": "calculation",
      "kind": "indicator",
      "tool_key": "ema",
      "display_name": "EMA 20",
      "parameters": {
        "period": 20
      },
      "sources": [],
      "artifact_id": null,
      "expected_output_names": [
        "ema_20"
      ],
      "user_metadata": {
        "important": true,
        "dataset_role": "supporting_indicator",
        "description": "Fast structural average."
      },
      "presentation": {
        "visible": true,
        "line_styles": [
          {
            "output_name": "ema_20",
            "color": "#22C55E",
            "line_width": 2.0,
            "line_pattern": "solid",
            "visible": true,
            "render_mode": "line",
            "marker_shape": "none",
            "marker_size": 8,
            "conditional_driver_name": null,
            "conditional_colors": {}
          }
        ],
        "fill_styles": []
      }
    }
  ],
  "content_hash": "dc479f40b37fe1b0fa029316000c91663a17b69b58b7a5b8fe0fcaf4f24b8cfa"
}
```

### Notebook 1.0

```json
{
  "schema_version": "1.0",
  "object_type": "research_notebook",
  "notebook_id": "notebook_example",
  "display_name": "Example observations",
  "description": "Illustrative records, no trading execution",
  "created_at_utc": "2026-10-08T00:00:00+00:00",
  "updated_at_utc": "2026-10-08T00:00:00+00:00",
  "annotation_settings": {
    "show_points_of_interest": true,
    "show_potential_trades": true,
    "poi_offset_px": -28,
    "long_offset_px": 56,
    "short_offset_px": -56
  },
  "pages": [
    {
      "market_id": {
        "exchange": "bybit",
        "market_type": "linear",
        "symbol": "BTCUSDT",
        "timeframe": "1m"
      },
      "notes": [
        {
          "row_id": "note_1",
          "timestamp_ms": null,
          "text": "Review the accepted historical series"
        }
      ],
      "potential_trades": [
        {
          "row_id": "trade_1",
          "timestamp_ms": 1791417600000,
          "direction": "long",
          "entry_price": 100.0,
          "target_price": 110.0,
          "stop_price": 95.0,
          "status": "planned",
          "outcome": "pending",
          "note": "Illustrative only"
        }
      ],
      "points_of_interest": [
        {
          "row_id": "poi_1",
          "timestamp_ms": 1791417600000,
          "price": null,
          "title": "Review point",
          "description": "No price anchor specified"
        }
      ]
    }
  ],
  "content_hash": "2a72feb2ef1978609b76ba46bc8e2b244ee6a5be42461207e6b112be739c2dbb"
}
```

### Workspace Snapshot 1.1

```json
{
  "schema_version": "1.1",
  "object_type": "research_workspace_snapshot",
  "snapshot_id": "snapshot_example",
  "content_hash": "a30824bea6ef81797deb2c7c95360a0635817d6dde7674960eb99b29de282bb6",
  "display_name": "Example one-chart workspace",
  "description": "Loads current accepted data at restore time",
  "created_at_utc": "2026-10-08T00:00:00+00:00",
  "updated_at_utc": "2026-10-08T00:00:00+00:00",
  "workspace": {
    "visualization_mode": "fit_8",
    "pan_anchor_enabled": false,
    "active_chart_ref": "chart_1"
  },
  "charts": [
    {
      "chart_ref": "chart_1",
      "workspace_position": 1,
      "detached": false,
      "market_id": {
        "exchange": "bybit",
        "market_type": "linear",
        "symbol": "BTCUSDT",
        "timeframe": "1m"
      },
      "viewport": {
        "center_timestamp_ms": 1791417600000,
        "visible_count": 500
      },
      "price_scale": {
        "autoscale_enabled": true,
        "manual_low": null,
        "manual_high": null
      },
      "volume_visible": true,
      "pane_sizes": [
        {
          "pane_ref": "price",
          "size": 600
        },
        {
          "pane_ref": "volume",
          "size": 150
        }
      ],
      "study_environment": null
    }
  ],
  "notebook_id": "notebook_example"
}
```

