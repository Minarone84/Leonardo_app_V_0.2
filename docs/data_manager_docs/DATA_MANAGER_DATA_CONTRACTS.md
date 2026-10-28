# Data Manager data and interface contracts

**Targeted revision: 2026-10-28 (R07).** Reconciles accepted R01-R06 and current source. Earlier edition dates and validation counts below remain historical; R08 integrated and R09 native acceptance are separate, not performed by this documentation revision.

**Updated:** 2026-10-08. Companion to [scope](DATA_MANAGER.md),
[architecture](DATA_MANAGER_ARCHITECTURE.md),
[lifecycles](DATA_MANAGER_LIFECYCLES.md) and the
[map](Leonardo_V2_Data_Manager_Suite_Complete_Map.pdf).

This reference defines current identities, compatibility, persisted structures,
serialization, operation evidence and observable outcomes. Internal request/plan
dataclasses are not promoted into new public schemas. Existing owners and format
versions are preserved. Paths in code references are relative to the repository;
runtime roots come from configuration.

### UTC measurement enrichment (2026-10-15)

UTC analysis accepts empty legacy mappings, V1 `utc_classification` alone, or
that unchanged section plus `utc_episode_metrics` schema 1.0. Metrics bind the
full original classification digest and source/configuration witnesses. Unknown
sections, broken bindings and inconsistent measurements are rejected.

The Artifact `analysis.json` and database V6 `utc_classification.json` envelope
continue to carry the complete mapping. Enrichment changes a newly calculated
physical Artifact's analysis hash/identity while preserving numeric values and
the existing Recipe/logical identity rules. It does not modify old saved objects.
Copied reports remain physical-provider snapshots with explicit association
coverage; a full report does not imply that every outcome row was imported.
Append retains old reports and adds suffix-provider evidence. Frozen-formation
conflict checks continue to compare only the original classification facts.

Legacy load/edit never invents enrichment from live Artifacts. Current readers
accept V1-only and enriched reports; compatibility with older readers is not
promised. Exact measurements and timing rules are documented in
[UTC episode measurements](../analysis_docs/UTC_EPISODE_MEASUREMENTS.md).

## 1. Canonical identity and compatibility

`MarketId = (exchange, market_type, symbol, timeframe)` must already agree with
canonical market and timeframe normalization. A shared symbol alone is not a
market identity. Dataset/value positions use integer UTC milliseconds; created/
updated metadata use timezone-aware UTC. Calendar-month continuity uses the
canonical month helper, not a guessed fixed number of seconds.

IDs and hashes have different roles:

| Identity | Meaning |
|---|---|
| Portable `recipe_id` | SHA-256 of the canonical executable portable definition; no market/origin/display metadata |
| Semantic object key | Recursive tool + semantic parameters + actual inputs; detects equivalent graphs even when old dependency IDs differ |
| Market-bound Artifact `recipe_id` | SHA-256 of market, tool, parameters, bindings, outputs and exact saved source references |
| `logical_artifact_id` | SHA-256 of canonical MarketId + portable Recipe ID + logical-identity version/type |
| Physical `artifact_id` | SHA-256 of exact execution recipe, source fingerprint/references, row bounds/count, values hash and optional analysis hash |
| Collection / Seed / Database ID | Stable object identity, separate from revision/content |
| Revision ID | Hash of the canonical revision payload excluding its own revision_id; includes the format's revision metadata and history link |
| Head | Mutable pointer to an immutable revision/version; inspection of history never changes it |

Portable Recipe Collections use `prc_` plus 32 lowercase hex characters; Artifact
Collections use `ac_`, Seeds `seed_`, and Databases `db_` with the same 32-character
suffix. Hash IDs contain exactly 64 lowercase hexadecimal characters. Canonical
column names match `^[A-Za-z_][A-Za-z0-9_.-]*$`. Text validation rejects unintended
leading/trailing whitespace where the model requires canonical text. Integers do
not accept booleans merely because Python treats bool as an int subclass.

### The three materialized compatibility rules

1. Same canonical OHLCV identity, including timeframe.
2. Same row count.
3. Same first and last timestamps.

These rules apply to materialized saved-input admission, Artifact Collections and
Database composition. Captured fingerprints, physical versions and values hashes
remain provenance/integrity evidence and exact reviewed-plan fences. They are not
an extra generic fourth cross-object compatibility condition. Compatible inputs
still need valid payloads, required types, exact roles/output names and dependency
closure. Changed reviewed evidence can stale a plan even when a newly prepared
plan would admit those objects under the three rules.

### Portable semantic projection

The canonical portable payload contains schema/type, tool key/version, kind,
canonical parameters, ordered output names, OHLCV input descriptors and dependency
descriptors. Build helpers sort OHLCV inputs by role/column and dependencies by
role/Recipe/output. Execution selectors already represented by those inputs are
normalized from new persistence for the tools whose canonical policy defines it.

For semantic equivalence, resolve each dependency to its semantic key rather
than comparing only the persisted Recipe ID. Input records distinguish OHLCV
columns from object outputs and include roles. Tools with implicit OHLCV inputs
obtain them from the canonical specification. Raw OHLC selections in Constructs
remain real calculation input identity; changing Open to Close is not equivalent.
Collection equivalence compares semantic member sets, not display order or name.

## 2. Persistence layout and byte contracts

```text
historical_data/<canonical market path>/
  ohlcv/candles.csv + candles.meta.json
  recipes/<kind>/<tool_key>/<recipe_id>.json
  artifacts/<kind>/<tool_key>/<artifact_id>/
    values.csv + artifact.meta.json [+ analysis.json]
  artifact_versions/<logical_artifact_id>/
    head.json
    versions/<artifact_id>.json

study_environments/<environment_id>.json       Research owner
research_notebooks/<notebook_id>.json          Research owner

data_manager/
  recipes/<portable_recipe_id>.json
  recipe_provenance/<portable_recipe_id>/
    metadata.json
    <provenance_id>.json
  recipe_collections/<prc_id>/
    head.json
    revisions/<revision_id>.json
  artifact_collections/<ac_id>/
    head.json
    revisions/<revision_id>.json
  database_seeds/<seed_id>.json                legacy V1
  database_seeds/<seed_id>/                    V2
    manifest.json + values.csv
  databases/<db_id>/
    definition.json
    head.json
    revisions/<revision_id>/manifest.json + values.csv
```

The market path contains exchange/market type/symbol/canonical timeframe segment;
it is derived by the canonical store, not by user labels. Research Snapshot and
Notebook assignments remain in Research roots; Open Notebooks creates no DMS
copy or alternate Notebook format.

Portable Recipes, their provenance/Collections, managed version/head records and
DMS creation models serialize sorted-key UTF-8 JSON with two-space indentation,
`ensure_ascii=False`, `allow_nan=False`, and one trailing newline. Market-bound
Artifact recipe/metadata JSON uses its canonical encoder with the same formatting.
Load compares canonical bytes, validates expected fields and identities, and
rejects collisions instead of overwriting immutable history.

Do not conflate persisted bytes with hash input:

| Family | Identity byte convention |
|---|---|
| Portable Recipe semantic payload and Collection revision payload | Indented sorted JSON plus newline, as defined by Recipe identity functions |
| Artifact recipe, physical Artifact and logical Artifact identity | Compact sorted JSON, separators comma/colon, no trailing newline |
| DMS revision/plan deterministic hash | Indented canonical JSON plus newline, excluding the self-ID when that model's builder specifies it |
| Values / analysis integrity | SHA-256 of exact saved bytes |
| Research Environment/Notebook/Snapshot content hash | Research's own compact payload rule; not the DMS revision rule |

Safe paths reject traversal, unsafe symlinks/reparse points and unexpected payload
shapes. Immutable writes accept only byte-identical reuse at an existing identity.
Mutable heads/metadata use temporary files, flush/fsync and replace through their
owner. Revision bundles are staged and checked before publication; expected old
head and predecessor are checked again. Failure cleanup is scoped to newly owned
publication state, with existing history retained. This is not a universal
multi-root crash transaction.

For V2 Seed append, `.seed-append-<seed_id>.json` records version, seed ID,
backup token, old manifest hash and old values hash. A same-root backup holds
the old exact pair. While pending, metadata reads expose the old manifest;
full reads use the verified old pair. Candidate values/manifest are replaced
and verified before removing the record to commit. Failed publication restores
the previous pair. A disposable backup may remain if post-commit cleanup fails;
do not mistake it for another Seed. V1 append preserves V1 and updates its
reference file only. If both V1 and V2 paths claim one ID, fail closed.

### Values and numerical precision

Artifact values CSV starts with `ts_ms`, followed by the exact declared output
order. Its typed encoder uses lowercase true/false for booleans, declared strings
for categorical outputs, empty tokens for allowed numerical NaN, and float32
round-trip decimal formatting (`.9g`) for numerical Financial Tool outputs.
Infinities, malformed timestamps and invalid output types are rejected. This
preserves the canonical calculation representation; GUI decimal formatting does
not rewrite numerical data.

Seed/Database values preserve the full timestamp axis and declared ordered
columns. Base values remain finite; derived columns may contain legitimate NaNs
and supported categorical values. Header, row/column counts, bounds, values hash
and permitted nullable columns must agree with the manifest. A later Artifact
update cannot fill historical Database NaNs. Content editing preserves retained
tokens through the established row-editing path; append preserves the old prefix
and adds only a continuous suffix. No all-finite intersection is substituted for
the accepted source axis.

## 3. Global Recipe schemas

### PortableRecipeV1 and inputs

Schema `1.0`, type `portable_recipe`. Root fields are `schema_version`,
`object_type`, `recipe_id`, `tool_key`, `tool_version`, `kind`, `parameters`,
`output_names`, `ohlcv_inputs`, `dependencies`. OHLCV descriptors contain `role`
and `column_name`; dependency descriptors contain `role`, `recipe_id`,
`output_name`. Source roles are unique, refer to permitted inputs and declared
outputs, and are checked against tool requirements. The general OHLCV column
enum does not permit raw Volume in a Construct.

`PortableRecipePersistenceMetadataV1` belongs to the Recipe, separately from its
semantic definition. It holds `recipe_id`, optional `first_persisted_at_utc` and
origin records. Origin kinds are study_environment, research_save and
data_manager_artifact. Environment origins identify Environment, content hash
and entry; a Research Save may carry a Study ID. Origin ID and recorded UTC time
identify metadata history, not numerical meaning. Legacy absent age is unknown,
not inferred from file modification time.

`PortableRecipeProvenanceV1` records an exact derivation relationship: Recipe,
origin MarketId, Environment ID/content hash/update time/name, entry ID, Study
name/description, and its own provenance ID. It does not turn an Environment
into a runtime dependency of its already saved Recipe.

### Recipe Collection revision and head

`PortableRecipeCollectionRevisionV1` has schema/type, `collection_id`,
`revision_id`, name/description, explicit `root_recipe_ids`, complete
`member_recipe_ids`, `previous_revision_id`, and `created_at_utc`. Roots must
belong to members; graph planning establishes complete supports, role/output
validity and topological execution stages. A cycle or absent required Recipe
blocks a graph, rather than producing a partial executable Collection.

`PortableRecipeCollectionHeadV1` has schema/type, collection ID, revision ID and
`updated_at_utc`. New revisions preserve history; the head alone advances.
Historical membership still participates in Recipe deletion protection.

## 4. Artifact and Artifact Collection schemas

### Source and exact calculated payload

`OHLCVSourceFingerprintV1` carries schema version, canonical MarketId,
`csv_sha256`, `sidecar_sha256`, `row_count`, first/last timestamps,
`persistence_status`, `validation_status` and `sidecar_schema_version`. It records
what was consumed, not an instruction to rewrite another compatible object's
historical evidence.

`ArtifactRecipeV1` is market-bound: schema, recipe ID, MarketId, tool/kind,
parameters, named bindings, output names, saved `source_artifacts`, display
name/description and creation time. Each `ArtifactSourceRefV1` has role, exact
Artifact ID and output name. The display metadata is excluded from execution
identity, while market/bindings/sources are included.

`ArtifactMetadataV1` embeds that recipe and source fingerprint and includes
Artifact ID, row count, endpoints, values filename/hash, optional analysis
filename/hash and creation time. Values use `values.csv`; metadata uses
`artifact.meta.json`; optional analysis uses its declared canonical file. The
source role graph must resolve to the correct market, outputs and lineage.

`ArtifactVersionRecordV1` connects logical Artifact ID to physical Artifact ID,
portable Recipe ID, MarketId, previous physical version and creation time, plus
schema/type. `ArtifactHeadV1` records logical ID, current physical ID and update
time. Missing Portable Recipe persistence does not invalidate an otherwise valid
saved Artifact's embedded execution/lineage. Deletion still respects genuine
Artifact-domain references.

### Artifact Collection graph

`ArtifactCollectionRevisionV1` defines explicit roots/supports, members,
dependency edges, selected outputs, presentation order, source portable Recipe
IDs and optional source Recipe Collection identity/revision, source OHLCV
evidence, endpoints, validation/readiness, previous revision, and metadata.
`ArtifactCollectionRevisionV2` retains those fields and adds `value_provenance`.
The head contains Collection ID, revision ID, updated time and schema version.

| Nested record | Exact serialized members |
|---|---|
| Artifact Collection member | logical_artifact_id, artifact_id, portable_recipe_id, tool_key, kind, output_names, values_sha256 |
| Logical dependency edge | dependency_logical_artifact_id, dependent_logical_artifact_id, role, output_name |
| Selected output | logical_artifact_id, output_name, column_name |
| Physical dependency edge | dependency_artifact_id, dependent_artifact_id, role, output_name |
| Exact physical output segment | column_name, logical_artifact_id, output_name, artifact_id, first_timestamp_ms, last_timestamp_ms |

The Python member model groups its two identity values into `version_key`; JSON
flattens them into logical_artifact_id and artifact_id. Required dependencies
form an acyclic graph; an edge's output must exist and each dependent role is
unique. Roots/supports are distinct, supports must remain required, output column
names are unique, and presentation order accounts for selected columns exactly.
An Artifact Collection requires a nonempty root set.

V2 `value_provenance` has `members`, `dependency_edges`, `outputs` describing
exact physical providers. Each selected Collection output has one full-range
provider segment. Logical membership, physical value providers and provenance
are related but must not be collapsed into "follow the newest head" behavior.

## 5. Seed, Database and legacy schemas

### Seed formats

Both Seed schemas contain seed ID, display name/description, MarketId, source
fingerprint, source row count/endpoints, selected OHLCV columns, selected range
start/end and creation time, plus schema/type. V1 is a reference file. V2 adds
owned `row_count`, `column_count`, `values_sha256` and a separate values CSV.
The more general legacy range/column fields remain readable; the **new creation
operation** restricts them to complete source coverage, OHLC plus optional Volume.
Format capability must not be mistaken for an exposed arbitrary trimming feature.

### Database definition and versions

`DatabaseDefinitionV1` holds schema/type, database ID, name, description, MarketId,
Seed ID and creation time. `DatabaseHeadV1` holds schema, database ID, revision ID
and update time. A current head and all old immutable revision bundles coexist.

All revision formats include identity/metadata, source/Seed evidence, coverage,
row/column counts, values hash, previous revision and creation time. The formats
differ in their representation of imported content:

| Version | Imported membership and attribution |
|---|---|
| V1 / 1.0 | Collection ID/revision/manifest hash; Artifact version keys and payload hashes; portable Recipe IDs; original-to-saved column_mapping. It may lack exact per-column logical binding. |
| V2 / 2.0 | Explicit members, logical dependency edges, selected outputs and Collection references. column_mapping becomes identity mapping, including ts_ms and all declared columns. |
| V3 / 3.0 | V2-style content plus selection_sources describing direct Artifact or Collection ownership of each included output. |
| V4 / 4.0 | Adds value_provenance to distinguish logical selection from physical value-provider segments and preserve append history. Fully attributed publication without copied UTC classification uses this version. |
| V5 / 5.0 | Same main field set as V4, with explicit legacy-unbound output/selection forms and captured original manifests. Used when an explicit operation must retain truthful unknown legacy attribution. |
| V6 / 6.0 | Retains V4/V5 value provenance and incomplete legacy forms; adds a checksummed, revision-owned UTC classification sidecar for selected UTC output providers. |

`DatabaseCollectionReferenceV2` is the pair collection_id/revision_id. A normal
selection source has `source_kind`, `source_id`, `source_revision_id`,
`column_names`. For an Artifact owner, source_id is its logical ID and revision
is null. For Collection ownership it is Collection ID plus exact revision. V5
also permits `legacy_snapshot` with this Database ID and captured revision.
Source keys are unique; column lists are nonempty/unique; every selected output
has ownership; Collection references agree with Collection owners. Multiple
owners may justify one retained column.

### Physical provenance and truthful legacy history

Database `value_provenance` contains physical members, physical edges and output
segments, optionally `legacy_revisions`. Exact members identify physical IDs
uniquely. Role edges must reference present providers/outputs and remain acyclic.
For each selected output, ordered nonoverlapping segments must cover the entire
revision range contiguously, using timeframe-aware next-timestamp calculation.

An exact segment contains column, logical ID, output, physical Artifact ID and
first/last timestamps. A legacy segment replaces artifact_id with
`legacy_revision_id`. V5 can omit logical_artifact_id only for an actually unbound
legacy output. Its `DatabaseLegacyOutputV1` has `column_name`, `output_name`,
`legacy_revision_id`; its Python logical_artifact_id property is not a fabricated
persisted logical ID. The captured V1 mapping must prove the stored column.

Captured legacy revisions must be canonical original V1/V2/V3 manifests of the
same Database/MarketId; each must be used by the retained evidence. Known
bindings must agree with that capture. Exact future segments for an unbound
column start strictly after original legacy coverage, refer to an allowed
captured candidate, and agree on one logical provider. A surviving candidate
alone is not historical proof. Future exact suffixes cannot overlap/relabel
the original unbound history.

No-op and ordinary loading write nothing. V5 is not a bulk migration or permission
to invent missing Artifact/Recipe/Collection IDs. V1-V4 old bytes remain unchanged.

## 6. Plans, payload validation and update algorithms

Requests/plans are immutable internal values, not saved pools. They carry enough
evidence to compare the exact reviewed context at execution and publication.

| Plan family | Essential retained evidence |
|---|---|
| Recipe derivation | Environment content hash, selected root/support entries, portable definitions, dependency stages, provenance/actions, blockers |
| Artifact materialization | Target market/source, root/member Recipe IDs, source Collection revision, ordered nodes and current/previous physical heads |
| Artifact Collection selection | Root/support logical IDs, exact members/edges, source and coverage, mapped outputs/presentation |
| Batch | Request source fingerprint, exact branches/roles/parameters/outputs, destination, graph, New/Reuse decisions, collisions and blockers |
| Seed creation / append | Candidate manifest/values; previous Seed/values hashes and row count for append; accepted source and appended count |
| Seed-only Database | Seed hash/source, requested metadata, columns, row count and endpoints |
| Database content edit | Starting revision, removals/additions, reviewed incoming members, final ownership/columns/provenance and blockers |
| Artifact update | Roots/dependencies, current source/heads, node actions, context/overlap/revisable-tail rules and blockers |
| Database append | Starting revision/source/Artifact heads, fixed retained outputs, proven providers, compatible suffix and mode/blockers |

Execution must use the current plan rather than rebuilding a different operation
silently. A stale plan requires another user review. Publication repeats the
relevant source/head checks; passing Preview once is not a lifetime waiver.

### Scope of checks

Metadata reads classify validity/currentness without opening every values CSV.
Actual operations validate consumed payloads and their required graph, plus new
outputs. Checked OHLCV evidence is cached by DMS session generation + market
source generation + exact source record. A successful check stores the proven
timestamp axis, while values stay in the loader cache. End-session, source-change,
failed/cancelled check or mismatching evidence prevents reuse. Hidden external
tamper detection after trusted checks is outside this approved model.

### Suffix and membership algorithms

Seed append chooses rows later than the saved last timestamp, verifies each next
timestamp against fixed-timeframe or calendar-month continuity, and concatenates
the old values unchanged with that suffix. No suffix means no publication. V1
remains reference-based; V2's owned pair is published through its recovery record.

Database edit starts from owned values, resolves final source ownership, retains
remaining columns, copies only reviewed incoming compatible columns, and publishes
a new manifest/value bundle when something changes. Incoming checks do not force
unrelated retained providers to survive. Derived removal uses saved column names;
base columns are protected. A no-op returns the existing result without a revision.

Database append first determines whether a suffix exists. For growth, every
retained derived output needs a provable current provider and valid coverage;
providers may require a separate explicit Artifact update. Compose old values
plus new suffix, combine old and new physical provenance, recheck reviewed
source/heads/bindings, then publish. Preserve old cells/NaNs even if the latest
Artifact would now give different historical values. CURRENT publishes nothing;
BLOCKED reports reasons. The rebuild endpoint always refuses.

Both GUI derivation routes pass `expected_environment_content_hash=plan.environment_content_hash` through the existing application command. Execution compares two freshly built plans and the reviewed hash before persistence, then reloads and compares the Environment after the publication gate and before writes. A changed saved definition requires Preview again. Programmatic `None` retains the explicit no-preview compatibility path and execution-time checks; GUI requests must carry their token. Equivalent Recipe reuse and provenance remain separate from that reviewed-intent check.

Before proof reuse, DMS compares session/market generation, exact accepted source metadata and both CSV/sidecar stat fingerprints `(st_size, st_mtime_ns, st_ino)` (inode defaults to zero when unavailable). Metadata and file identities are checked again before return. A mismatch drops cached proof and uses the existing strict loader parse/hash path; successful proof retains the timestamp axis, not another full-values cache. This protects against observed replacement even without GUI invalidation, not hostile same-stat tampering or continuous file watching.

## 7. Currentness, result and GUI contracts

Currentness is a read-only assessment, distinct from validity and publication.
The source statuses are UNCHANGED, APPEND_ONLY, HISTORICAL_MUTATION, TRUNCATED,
IDENTITY_MISMATCH and INVALID_SOURCE. Artifact assessments can report CURRENT,
APPEND_AVAILABLE, HISTORICAL_SOURCE_CHANGED, REBUILD_REQUIRED, INVALID,
BLOCKED_BY_SOURCE, BLOCKED_BY_DEPENDENCY or RECIPE_CHANGED. Collection and Database
reports add alignment/readiness, waiting-for-provider and prefix/schema reasons.
Some historical enum values remain representable; that is not authorization to
expose retired rebuild behavior. Current Database planning uses CURRENT/APPEND/
BLOCKED and the GUI displays the actual domain reason.

`TaskSubmission` correlates requests with Core; `TaskResult` carries terminal
status, value and failure. Queued dispatch returns work to Qt. Presenter checks
disposal, task/generation, selection and retained window/plan before presentation.
Only matching pending state is released. A late success can be a truthful Core
result while its retired GUI delivery is correctly ignored.

The foreground Operation surface displays progress and cancellation derived from
Core. Background reconciliation is separately correlated and never invents a
second executor or task owner. `WindowRegistry` receives distinct IDs for the
Database Artifact and Collection editors; titles are not identity. The full
identity table and command/sorting behavior remain in the entry manual.

The Operation view uses typed result evidence for `Published` and `Publication evidence`. New Artifacts, versions or advanced heads demonstrate publication; a materialization with only reused outputs and no returned Collection reports no new publication. A stored Collection revision alone does not reveal new versus reused and is reported as unknown. Construct batch combines its materialization result with the optional Collection result. Failed/cancelled status or an unexpected result type reports unknown, never inferred rollback. Recipe derivation separately reports created/reused Recipes, provenance and its explicit Collection outcome.

The six current report branches are `execute_recipe_artifact_materialization`, `create_recipe_collection_from_catalog`, `update_recipe_collection_from_catalog`, `create_artifact_collection_from_materialization`, `edit_artifact_collection_from_selection` and `execute_construct_batch`. Retained materialize/batch names and the existing direct/derivation branches use the same projection; no new persisted result fields are introduced.

## 8. Integration interfaces and reconstruction limits

Required existing boundaries are canonical MarketId/timeframe handling; OHLCV
catalog/accepted evidence and checked full loader; Research Environment loading;
portable identity/graph/store; Financial Tool specification/eligibility/calculate/
update policy; Artifact prepare/load/publication/lineage; Core submission/dispatch/
tracking; and configured paths. Reuse those authorities instead of creating a
second calculation or persistence policy inside DMS.

The Dataset selector carries complete identity only. The Research handoff reloads
DMS truth for that market. Open Notebooks reuses Research's owner and does not
copy Notebook schemas or mutation APIs into DMS. Database snapshots are durable
inputs for downstream analysis; this contract does not invent an Analysis engine.

These documents specify DMS within Leonardo. Exact formulas, categorical output
contracts and per-tool numerical fixtures stay in Financial Tools. The schemas,
examples and observable criteria below complement the workflow rules; they are
not an invitation to migrate real user files or treat prose as an executable
replacement for canonical validation.

## 9. Observable acceptance matrix

Test paths below are under `tests/`; all executions must use isolated/generated
roots. Existing suites overlap and their pass counts must not be added together.

| Boundary | Required observable result | Current executable evidence |
|---|---|---|
| Catalog/session checks | Browsing metadata-only; successful exact-session evidence reused; failed/cancelled/stale checks not reused | `data_manager_test/test_metadata_only_catalogs.py`, `test_operation_check_session.py`, `test_operation_input_checks.py` |
| Portable identity | Equivalent graph reuse across origins/markets; actual raw selectors remain meaningful | `recipes_test/test_portable_recipe_models.py`, `data_manager_test/test_environment_artifact_derivation_identity.py`, `test_portable_recipe_workflow.py` |
| Recipe history/deletion | Immutable revisions; real references protect Recipes; Collection deletion preserves members | `recipes_test/test_portable_recipe_planner_store.py` |
| Direct/full-axis Artifact | Full axis/NaNs and exact roles; saved inputs obey canonical eligibility; graph publication preserves history | `data_manager_test/test_direct_artifact_creation.py`, `test_artifact_materialization.py`, `test_full_axis_lifecycle.py`, `artifacts_test/test_managed_artifact_versions.py` |
| Three-rule admission | Market/count/endpoints decide compatibility; sidecar-only change is not a fourth blocker | `data_manager_test/test_three_rule_alignment.py` |
| Batch | Explicit expansion, mixed/raw/saved replay, destination and stale/cancel boundaries | `data_manager_test/test_construct_batch.py`, `test_creation_workflow.py`, `gui_test/test_data_manager_construct_batch_dialog.py` |
| Seeds | Full-source creation; V1/V2 enumeration; explicit append preserves prefix and recovery pair | `data_manager_test/test_full_source_seed_creation.py`, `test_seed_append_workflow.py`, `test_seed_only_database_workflow.py` |
| Database edits | No-op/removal/unrelated addition after deleted upstream; column ownership, base protection and retained values | `data_manager_test/test_database_content_management.py`, `test_database_v2_models.py` |
| Provenance / NaNs | V4/V5 truthful segments; unknown legacy not fabricated; exact future providers; old values and NaNs retained | `data_manager_test/test_materialized_provenance_models.py`, `test_database_lifecycle_provenance.py`, `test_nan_database_composition.py`, `test_nan_snapshot_updates.py` |
| Updates | Separate Artifact update and Database APPEND; stale plan refusal; no hidden recalc/rebuild/shrink | `data_manager_test/test_update_workflow.py`, `test_update_application_vertical.py` |
| GUI lifecycle | Active production navigation, immediate projection, first-open warm-up, coalescing, late result isolation and close | `gui_test/test_data_manager_suite_window.py`, `test_data_manager_reconciliation_lifecycle.py`, `test_data_manager_check_session_lifecycle.py`, `test_data_manager_revision_history.py` |
| Editor identity and orphan access | Different editor IDs; owned snapshots remain editable/inspectable without source | `gui_test/test_database_content_window_identity.py`, `test_data_manager_database_content_vertical.py`, `test_data_manager_catalogs.py` |
| Research bridge | Open/reuse real Notebook Manager, preserve Research dirty/restore admission | `gui_test/test_research_main_application_composition.py`, `test_research_composed_transition_guards.py`; separate DMS shortcut smoke receipt |

No new behavior is required by this matrix beyond the accepted implementation.
Native evidence and the user's personal visual acceptance remain distinct from
domain or offscreen tests. Detailed prior gate counts and current documentation
validation belong in the audit report, not inferred from this list of files.

## 10. Complete model field inventory

The following inventory lists model attributes with their current types, including
inherited fields where a version extends a prior model. Class-level validation
constants are excluded. This is a field-completeness aid, not a claim that every
internal Python record is a public API. Model-to-wire differences are specified
above (notably flattened Artifact member version keys); canonical `to_dict` and
`from_dict` define exact nested JSON. Source links identify each owner.

### recipes/models.py

Owner: [source](../../src/leonardo/recipes/models.py).

#### PortableRecipeOHLCVInputV1

| Attribute | Type | Declared default |
|---|---|---|
| `role` | `str` | required |
| `column_name` | `str` | required |

#### PortableRecipeDependencyV1

| Attribute | Type | Declared default |
|---|---|---|
| `role` | `str` | required |
| `recipe_id` | `str` | required |
| `output_name` | `str` | required |

#### PortableRecipeV1

| Attribute | Type | Declared default |
|---|---|---|
| `recipe_id` | `str` | required |
| `tool_key` | `str` | required |
| `tool_version` | `str` | required |
| `kind` | `str` | required |
| `parameters` | `Mapping[str, object]` | required |
| `output_names` | `tuple[str, ...]` | required |
| `ohlcv_inputs` | `tuple[PortableRecipeOHLCVInputV1, ...]` | required |
| `dependencies` | `tuple[PortableRecipeDependencyV1, ...]` | required |
| `schema_version` | `str` | `'1.0'` |
| `object_type` | `str` | `'portable_recipe'` |

#### PortableRecipeOriginV1

| Attribute | Type | Declared default |
|---|---|---|
| `origin_id` | `str` | required |
| `origin_kind` | `str` | required |
| `origin_recorded_at_utc` | `datetime` | required |
| `details` | `Mapping[str, str]` | required |
| `schema_version` | `str` | `'1.0'` |
| `object_type` | `str` | `'portable_recipe_origin'` |

#### PortableRecipePersistenceMetadataV1

| Attribute | Type | Declared default |
|---|---|---|
| `recipe_id` | `str` | required |
| `first_persisted_at_utc` | `datetime \| None` | required |
| `origins` | `tuple[PortableRecipeOriginV1, ...]` | required |
| `schema_version` | `str` | `'1.0'` |
| `object_type` | `str` | `'portable_recipe_persistence_metadata'` |

#### PortableRecipeProvenanceV1

| Attribute | Type | Declared default |
|---|---|---|
| `provenance_id` | `str` | required |
| `recipe_id` | `str` | required |
| `origin_market_id` | `MarketId` | required |
| `study_environment_id` | `str` | required |
| `study_environment_content_hash` | `str` | required |
| `study_environment_updated_at_utc` | `datetime` | required |
| `study_environment_display_name` | `str` | required |
| `study_entry_id` | `str` | required |
| `study_display_name` | `str` | required |
| `study_description` | `str` | required |
| `schema_version` | `str` | `'1.0'` |
| `object_type` | `str` | `'portable_recipe_provenance'` |

#### PortableRecipeCollectionRevisionV1

| Attribute | Type | Declared default |
|---|---|---|
| `collection_id` | `str` | required |
| `revision_id` | `str` | required |
| `display_name` | `str` | required |
| `description` | `str` | required |
| `root_recipe_ids` | `tuple[str, ...]` | required |
| `member_recipe_ids` | `tuple[str, ...]` | required |
| `previous_revision_id` | `str \| None` | required |
| `created_at_utc` | `datetime` | required |
| `schema_version` | `str` | `'1.0'` |
| `object_type` | `str` | `'portable_recipe_collection_revision'` |

#### PortableRecipeCollectionHeadV1

| Attribute | Type | Declared default |
|---|---|---|
| `collection_id` | `str` | required |
| `revision_id` | `str` | required |
| `updated_at_utc` | `datetime` | required |
| `schema_version` | `str` | `'1.0'` |
| `object_type` | `str` | `'portable_recipe_collection_head'` |

### artifacts/models.py

Owner: [source](../../src/leonardo/artifacts/models.py).

#### OHLCVSourceFingerprintV1

| Attribute | Type | Declared default |
|---|---|---|
| `market_id` | `MarketId` | required |
| `csv_sha256` | `str` | required |
| `sidecar_sha256` | `str` | required |
| `row_count` | `int` | required |
| `first_timestamp_ms` | `int` | required |
| `last_timestamp_ms` | `int` | required |
| `persistence_status` | `str` | required |
| `validation_status` | `str` | required |
| `sidecar_schema_version` | `str` | required |
| `schema_version` | `str` | `'1.0'` |

#### ArtifactSourceRefV1

| Attribute | Type | Declared default |
|---|---|---|
| `role` | `str` | required |
| `artifact_id` | `str` | required |
| `output_name` | `str` | required |

#### ArtifactRecipeV1

| Attribute | Type | Declared default |
|---|---|---|
| `recipe_id` | `str` | required |
| `market_id` | `MarketId` | required |
| `tool_key` | `str` | required |
| `kind` | `str` | required |
| `parameters` | `Mapping[str, object]` | required |
| `bindings` | `Mapping[str, object]` | required |
| `output_names` | `tuple[str, ...]` | required |
| `source_artifacts` | `tuple[ArtifactSourceRefV1, ...]` | required |
| `display_name` | `str` | required |
| `description` | `str` | required |
| `created_at_utc` | `datetime` | required |
| `schema_version` | `str` | `'1.0'` |

#### ArtifactMetadataV1

| Attribute | Type | Declared default |
|---|---|---|
| `artifact_id` | `str` | required |
| `recipe` | `ArtifactRecipeV1` | required |
| `source_ohlcv` | `OHLCVSourceFingerprintV1` | required |
| `row_count` | `int` | required |
| `first_timestamp_ms` | `int` | required |
| `last_timestamp_ms` | `int` | required |
| `values_sha256` | `str` | required |
| `analysis_filename` | `str \| None` | required |
| `analysis_sha256` | `str \| None` | required |
| `created_at_utc` | `datetime` | required |
| `values_filename` | `str` | `'values.csv'` |
| `schema_version` | `str` | `'1.0'` |

#### ArtifactVersionRecordV1

| Attribute | Type | Declared default |
|---|---|---|
| `logical_artifact_id` | `str` | required |
| `artifact_id` | `str` | required |
| `portable_recipe_id` | `str` | required |
| `market_id` | `MarketId` | required |
| `previous_artifact_id` | `str \| None` | required |
| `created_at_utc` | `datetime` | required |
| `schema_version` | `str` | `'1.0'` |
| `object_type` | `str` | `'artifact_version_record'` |

#### ArtifactHeadV1

| Attribute | Type | Declared default |
|---|---|---|
| `logical_artifact_id` | `str` | required |
| `artifact_id` | `str` | required |
| `updated_at_utc` | `datetime` | required |
| `schema_version` | `str` | `'1.0'` |
| `object_type` | `str` | `'artifact_head'` |

### data_manager/creation_models.py

Owner: [source](../../src/leonardo/data_manager/creation_models.py).

#### ArtifactCollectionMemberV1

| Attribute | Type | Declared default |
|---|---|---|
| `version_key` | `ManagedArtifactVersionKey` | required |
| `portable_recipe_id` | `str` | required |
| `tool_key` | `str` | required |
| `kind` | `str` | required |
| `output_names` | `tuple[str, ...]` | required |
| `values_sha256` | `str` | required |

#### ArtifactCollectionDependencyV1

| Attribute | Type | Declared default |
|---|---|---|
| `dependency_logical_artifact_id` | `str` | required |
| `dependent_logical_artifact_id` | `str` | required |
| `role` | `str` | required |
| `output_name` | `str` | required |

#### ArtifactCollectionOutputV1

| Attribute | Type | Declared default |
|---|---|---|
| `logical_artifact_id` | `str` | required |
| `output_name` | `str` | required |
| `column_name` | `str` | required |

#### ArtifactCollectionRevisionV1

| Attribute | Type | Declared default |
|---|---|---|
| `collection_id` | `str` | required |
| `revision_id` | `str` | required |
| `display_name` | `str` | required |
| `description` | `str` | required |
| `market_id` | `MarketId` | required |
| `root_logical_artifact_ids` | `tuple[str, ...]` | required |
| `support_logical_artifact_ids` | `tuple[str, ...]` | required |
| `members` | `tuple[ArtifactCollectionMemberV1, ...]` | required |
| `dependency_edges` | `tuple[ArtifactCollectionDependencyV1, ...]` | required |
| `selected_outputs` | `tuple[ArtifactCollectionOutputV1, ...]` | required |
| `presentation_order` | `tuple[str, ...]` | required |
| `source_portable_recipe_ids` | `tuple[str, ...]` | required |
| `source_recipe_collection_id` | `str \| None` | required |
| `source_recipe_collection_revision_id` | `str \| None` | required |
| `source_ohlcv` | `OHLCVSourceFingerprintV1` | required |
| `first_timestamp_ms` | `int` | required |
| `last_timestamp_ms` | `int` | required |
| `validation_state` | `str` | required |
| `database_ready` | `bool` | required |
| `previous_revision_id` | `str \| None` | required |
| `created_at_utc` | `datetime` | required |
| `revised_at_utc` | `datetime` | required |
| `schema_version` | `str` | `'1.0'` |
| `object_type` | `str` | `'artifact_collection_revision'` |

#### ArtifactCollectionRevisionV2

| Attribute | Type | Declared default |
|---|---|---|
| `collection_id` | `str` | required |
| `revision_id` | `str` | required |
| `display_name` | `str` | required |
| `description` | `str` | required |
| `market_id` | `MarketId` | required |
| `root_logical_artifact_ids` | `tuple[str, ...]` | required |
| `support_logical_artifact_ids` | `tuple[str, ...]` | required |
| `members` | `tuple[ArtifactCollectionMemberV1, ...]` | required |
| `dependency_edges` | `tuple[ArtifactCollectionDependencyV1, ...]` | required |
| `selected_outputs` | `tuple[ArtifactCollectionOutputV1, ...]` | required |
| `presentation_order` | `tuple[str, ...]` | required |
| `source_portable_recipe_ids` | `tuple[str, ...]` | required |
| `source_recipe_collection_id` | `str \| None` | required |
| `source_recipe_collection_revision_id` | `str \| None` | required |
| `source_ohlcv` | `OHLCVSourceFingerprintV1` | required |
| `first_timestamp_ms` | `int` | required |
| `last_timestamp_ms` | `int` | required |
| `validation_state` | `str` | required |
| `database_ready` | `bool` | required |
| `previous_revision_id` | `str \| None` | required |
| `created_at_utc` | `datetime` | required |
| `revised_at_utc` | `datetime` | required |
| `schema_version` | `str` | `'2.0'` |
| `object_type` | `str` | `'artifact_collection_revision'` |
| `value_provenance` | `Mapping[str, object]` | `field(kw_only=True)` |

#### ArtifactCollectionHeadV1

| Attribute | Type | Declared default |
|---|---|---|
| `collection_id` | `str` | required |
| `revision_id` | `str` | required |
| `updated_at_utc` | `datetime` | required |
| `schema_version` | `str` | `'1.0'` |

#### DatabaseSeedV1

| Attribute | Type | Declared default |
|---|---|---|
| `seed_id` | `str` | required |
| `display_name` | `str` | required |
| `description` | `str` | required |
| `market_id` | `MarketId` | required |
| `source_ohlcv` | `OHLCVSourceFingerprintV1` | required |
| `source_row_count` | `int` | required |
| `first_timestamp_ms` | `int` | required |
| `last_timestamp_ms` | `int` | required |
| `selected_ohlcv_columns` | `tuple[str, ...]` | required |
| `selected_range_start_ms` | `int` | required |
| `selected_range_end_ms` | `int` | required |
| `created_at_utc` | `datetime` | required |
| `schema_version` | `str` | `'1.0'` |
| `object_type` | `str` | `'database_seed'` |

#### DatabaseSeedV2

| Attribute | Type | Declared default |
|---|---|---|
| `seed_id` | `str` | required |
| `display_name` | `str` | required |
| `description` | `str` | required |
| `market_id` | `MarketId` | required |
| `source_ohlcv` | `OHLCVSourceFingerprintV1` | required |
| `source_row_count` | `int` | required |
| `first_timestamp_ms` | `int` | required |
| `last_timestamp_ms` | `int` | required |
| `selected_ohlcv_columns` | `tuple[str, ...]` | required |
| `selected_range_start_ms` | `int` | required |
| `selected_range_end_ms` | `int` | required |
| `created_at_utc` | `datetime` | required |
| `row_count` | `int` | required |
| `column_count` | `int` | required |
| `values_sha256` | `str` | required |
| `schema_version` | `str` | `'2.0'` |
| `object_type` | `str` | `'database_seed'` |

#### DatabaseLegacyOutputV1

| Attribute | Type | Declared default |
|---|---|---|
| `column_name` | `str` | required |
| `output_name` | `str` | required |
| `legacy_revision_id` | `str` | required |

#### DatabaseDefinitionV1

| Attribute | Type | Declared default |
|---|---|---|
| `database_id` | `str` | required |
| `display_name` | `str` | required |
| `description` | `str` | required |
| `market_id` | `MarketId` | required |
| `seed_id` | `str` | required |
| `created_at_utc` | `datetime` | required |
| `schema_version` | `str` | `'1.0'` |
| `object_type` | `str` | `'database_definition'` |

#### DatabaseRevisionManifestV1

| Attribute | Type | Declared default |
|---|---|---|
| `database_id` | `str` | required |
| `revision_id` | `str` | required |
| `display_name` | `str` | required |
| `description` | `str` | required |
| `seed_id` | `str` | required |
| `market_id` | `MarketId` | required |
| `source_ohlcv` | `OHLCVSourceFingerprintV1` | required |
| `collection_id` | `str` | required |
| `collection_revision_id` | `str` | required |
| `collection_manifest_hash` | `str` | required |
| `artifact_version_keys` | `tuple[ManagedArtifactVersionKey, ...]` | required |
| `artifact_payload_hashes` | `tuple[str, ...]` | required |
| `portable_recipe_ids` | `tuple[str, ...]` | required |
| `column_mapping` | `Mapping[str, str]` | required |
| `first_timestamp_ms` | `int` | required |
| `last_timestamp_ms` | `int` | required |
| `row_count` | `int` | required |
| `column_count` | `int` | required |
| `values_sha256` | `str` | required |
| `previous_revision_id` | `str \| None` | required |
| `created_at_utc` | `datetime` | required |
| `schema_version` | `str` | `'1.0'` |
| `object_type` | `str` | `'database_revision'` |

#### DatabaseCollectionReferenceV2

| Attribute | Type | Declared default |
|---|---|---|
| `collection_id` | `str` | required |
| `revision_id` | `str` | required |

#### DatabaseRevisionManifestV2

| Attribute | Type | Declared default |
|---|---|---|
| `database_id` | `str` | required |
| `revision_id` | `str` | required |
| `display_name` | `str` | required |
| `description` | `str` | required |
| `seed_id` | `str` | required |
| `market_id` | `MarketId` | required |
| `source_ohlcv` | `OHLCVSourceFingerprintV1` | required |
| `members` | `tuple[ArtifactCollectionMemberV1, ...]` | required |
| `dependency_edges` | `tuple[ArtifactCollectionDependencyV1, ...]` | required |
| `selected_outputs` | `tuple[ArtifactCollectionOutputV1, ...]` | required |
| `collection_sources` | `tuple[DatabaseCollectionReferenceV2, ...]` | required |
| `column_mapping` | `Mapping[str, str]` | required |
| `first_timestamp_ms` | `int` | required |
| `last_timestamp_ms` | `int` | required |
| `row_count` | `int` | required |
| `column_count` | `int` | required |
| `values_sha256` | `str` | required |
| `previous_revision_id` | `str \| None` | required |
| `created_at_utc` | `datetime` | required |
| `schema_version` | `str` | `'2.0'` |
| `object_type` | `str` | `'database_revision'` |

#### DatabaseRevisionManifestV3

| Attribute | Type | Declared default |
|---|---|---|
| `database_id` | `str` | required |
| `revision_id` | `str` | required |
| `display_name` | `str` | required |
| `description` | `str` | required |
| `seed_id` | `str` | required |
| `market_id` | `MarketId` | required |
| `source_ohlcv` | `OHLCVSourceFingerprintV1` | required |
| `members` | `tuple[ArtifactCollectionMemberV1, ...]` | required |
| `dependency_edges` | `tuple[ArtifactCollectionDependencyV1, ...]` | required |
| `selected_outputs` | `tuple[ArtifactCollectionOutputV1, ...]` | required |
| `collection_sources` | `tuple[DatabaseCollectionReferenceV2, ...]` | required |
| `column_mapping` | `Mapping[str, str]` | required |
| `first_timestamp_ms` | `int` | required |
| `last_timestamp_ms` | `int` | required |
| `row_count` | `int` | required |
| `column_count` | `int` | required |
| `values_sha256` | `str` | required |
| `previous_revision_id` | `str \| None` | required |
| `created_at_utc` | `datetime` | required |
| `selection_sources` | `tuple[Mapping[str, object], ...]` | required |
| `schema_version` | `str` | `'3.0'` |
| `object_type` | `str` | `'database_revision'` |

#### DatabaseRevisionManifestV4

| Attribute | Type | Declared default |
|---|---|---|
| `database_id` | `str` | required |
| `revision_id` | `str` | required |
| `display_name` | `str` | required |
| `description` | `str` | required |
| `seed_id` | `str` | required |
| `market_id` | `MarketId` | required |
| `source_ohlcv` | `OHLCVSourceFingerprintV1` | required |
| `members` | `tuple[ArtifactCollectionMemberV1, ...]` | required |
| `dependency_edges` | `tuple[ArtifactCollectionDependencyV1, ...]` | required |
| `selected_outputs` | `tuple[ArtifactCollectionOutputV1, ...]` | required |
| `collection_sources` | `tuple[DatabaseCollectionReferenceV2, ...]` | required |
| `column_mapping` | `Mapping[str, str]` | required |
| `first_timestamp_ms` | `int` | required |
| `last_timestamp_ms` | `int` | required |
| `row_count` | `int` | required |
| `column_count` | `int` | required |
| `values_sha256` | `str` | required |
| `previous_revision_id` | `str \| None` | required |
| `created_at_utc` | `datetime` | required |
| `selection_sources` | `tuple[Mapping[str, object], ...]` | required |
| `schema_version` | `str` | `'4.0'` |
| `object_type` | `str` | `'database_revision'` |
| `value_provenance` | `Mapping[str, object]` | `field(kw_only=True)` |

#### DatabaseRevisionManifestV5

| Attribute | Type | Declared default |
|---|---|---|
| `database_id` | `str` | required |
| `revision_id` | `str` | required |
| `display_name` | `str` | required |
| `description` | `str` | required |
| `seed_id` | `str` | required |
| `market_id` | `MarketId` | required |
| `source_ohlcv` | `OHLCVSourceFingerprintV1` | required |
| `members` | `tuple[ArtifactCollectionMemberV1, ...]` | required |
| `dependency_edges` | `tuple[ArtifactCollectionDependencyV1, ...]` | required |
| `selected_outputs` | `tuple[ArtifactCollectionOutputV1, ...]` | required |
| `collection_sources` | `tuple[DatabaseCollectionReferenceV2, ...]` | required |
| `column_mapping` | `Mapping[str, str]` | required |
| `first_timestamp_ms` | `int` | required |
| `last_timestamp_ms` | `int` | required |
| `row_count` | `int` | required |
| `column_count` | `int` | required |
| `values_sha256` | `str` | required |
| `previous_revision_id` | `str \| None` | required |
| `created_at_utc` | `datetime` | required |
| `selection_sources` | `tuple[Mapping[str, object], ...]` | required |
| `schema_version` | `str` | `'5.0'` |
| `object_type` | `str` | `'database_revision'` |
| `value_provenance` | `Mapping[str, object]` | `field(kw_only=True)` |

#### DatabaseHeadV1

| Attribute | Type | Declared default |
|---|---|---|
| `database_id` | `str` | required |
| `revision_id` | `str` | required |
| `updated_at_utc` | `datetime` | required |
| `schema_version` | `str` | `'1.0'` |


## 11. Complete generated format examples

The examples below are generated from isolated accepted OHLCV through current
services, then parsed/round-tripped by their current models. IDs/hashes reflect
illustrative generated data, not the user's saved pools. A valid payload is not
proof that its referenced objects exist in another installation. Canonical store
and operation checks remain required. Full values are independently hash-checked
in the documentation validation evidence.

### Portable Recipe (PortableRecipeV1)

```json
{
  "dependencies": [],
  "kind": "indicator",
  "object_type": "portable_recipe",
  "ohlcv_inputs": [],
  "output_names": [
    "sma_3"
  ],
  "parameters": {
    "period": 3
  },
  "recipe_id": "f1c9ae4fd142ff1a69b5b93890aa93cee28d79c25604cae509dc47e0cb18095c",
  "schema_version": "1.0",
  "tool_key": "sma",
  "tool_version": "1.0"
}
```

### Recipe Collection revision (PortableRecipeCollectionRevisionV1)

```json
{
  "collection_id": "prc_14f9f239ed5e43b2a0594dd5e9810ea1",
  "created_at_utc": "2026-10-08T18:37:17.347970+00:00",
  "description": "Generated documentation example",
  "display_name": "Example reusable SMA",
  "member_recipe_ids": [
    "f1c9ae4fd142ff1a69b5b93890aa93cee28d79c25604cae509dc47e0cb18095c"
  ],
  "object_type": "portable_recipe_collection_revision",
  "previous_revision_id": null,
  "revision_id": "4ada8f50ade477af824232f41067d73556a4a9a9335c95f3d2b144fade8f1816",
  "root_recipe_ids": [
    "f1c9ae4fd142ff1a69b5b93890aa93cee28d79c25604cae509dc47e0cb18095c"
  ],
  "schema_version": "1.0"
}
```

### Artifact Collection revision (ArtifactCollectionRevisionV2)

```json
{
  "collection_id": "ac_1b7067ad44b948cfbb8c92aa2843a6ed",
  "created_at_utc": "2026-10-08T18:37:17.364969Z",
  "database_ready": true,
  "dependency_edges": [],
  "description": "",
  "display_name": "Example calculated SMA",
  "first_timestamp_ms": 1700000000000,
  "last_timestamp_ms": 1700005700000,
  "market_id": {
    "exchange": "bybit",
    "market_type": "linear",
    "symbol": "BTCUSDT",
    "timeframe": "1m"
  },
  "members": [
    {
      "artifact_id": "8b97200d16b7217b7215c987f10ab4be4f3d7cce6524df4e7901e2c953328bfd",
      "kind": "indicator",
      "logical_artifact_id": "a22062e239f7a6fee2e492249e5bf1ab1c4f035924bf4d802c7532578c81016e",
      "output_names": [
        "sma_3"
      ],
      "portable_recipe_id": "f1c9ae4fd142ff1a69b5b93890aa93cee28d79c25604cae509dc47e0cb18095c",
      "tool_key": "sma",
      "values_sha256": "6ae09d34fcb34c25fc1697f7c40abe91f8a3e56c8cc01b184b9c3c36fb38ca04"
    }
  ],
  "object_type": "artifact_collection_revision",
  "presentation_order": [
    "sma_3"
  ],
  "previous_revision_id": null,
  "revised_at_utc": "2026-10-08T18:37:17.364969Z",
  "revision_id": "c5aef9c11a722ecc641438df0240dd08cb57da8e6970363a5838b1d148165960",
  "root_logical_artifact_ids": [
    "a22062e239f7a6fee2e492249e5bf1ab1c4f035924bf4d802c7532578c81016e"
  ],
  "schema_version": "2.0",
  "selected_outputs": [
    {
      "column_name": "sma_3",
      "logical_artifact_id": "a22062e239f7a6fee2e492249e5bf1ab1c4f035924bf4d802c7532578c81016e",
      "output_name": "sma_3"
    }
  ],
  "source_ohlcv": {
    "csv_sha256": "df6957c71cf229331b4a3645400c5099d8f2f0df28a88db6a7b614c241caad29",
    "first_timestamp_ms": 1700000000000,
    "last_timestamp_ms": 1700005700000,
    "market_id": {
      "exchange": "bybit",
      "market_type": "linear",
      "symbol": "BTCUSDT",
      "timeframe": "1m"
    },
    "persistence_status": "committed",
    "row_count": 96,
    "schema_version": "1.0",
    "sidecar_schema_version": "1.0",
    "sidecar_sha256": "8be328a72650a83566c274f4fe7adf253d72ebe778d7eabf782ef8f29874b434",
    "validation_status": "ok"
  },
  "source_portable_recipe_ids": [
    "f1c9ae4fd142ff1a69b5b93890aa93cee28d79c25604cae509dc47e0cb18095c"
  ],
  "source_recipe_collection_id": null,
  "source_recipe_collection_revision_id": null,
  "support_logical_artifact_ids": [],
  "validation_state": "valid",
  "value_provenance": {
    "dependency_edges": [],
    "members": [
      {
        "artifact_id": "8b97200d16b7217b7215c987f10ab4be4f3d7cce6524df4e7901e2c953328bfd",
        "kind": "indicator",
        "logical_artifact_id": "a22062e239f7a6fee2e492249e5bf1ab1c4f035924bf4d802c7532578c81016e",
        "output_names": [
          "sma_3"
        ],
        "portable_recipe_id": "f1c9ae4fd142ff1a69b5b93890aa93cee28d79c25604cae509dc47e0cb18095c",
        "tool_key": "sma",
        "values_sha256": "6ae09d34fcb34c25fc1697f7c40abe91f8a3e56c8cc01b184b9c3c36fb38ca04"
      }
    ],
    "outputs": [
      {
        "artifact_id": "8b97200d16b7217b7215c987f10ab4be4f3d7cce6524df4e7901e2c953328bfd",
        "column_name": "sma_3",
        "first_timestamp_ms": 1700000000000,
        "last_timestamp_ms": 1700005700000,
        "logical_artifact_id": "a22062e239f7a6fee2e492249e5bf1ab1c4f035924bf4d802c7532578c81016e",
        "output_name": "sma_3"
      }
    ]
  }
}
```

### Owned Seed (DatabaseSeedV2)

```json
{
  "column_count": 6,
  "created_at_utc": "2026-10-08T18:37:17.413413Z",
  "description": "",
  "display_name": "Example full-source Seed",
  "first_timestamp_ms": 1700000000000,
  "last_timestamp_ms": 1700005700000,
  "market_id": {
    "exchange": "bybit",
    "market_type": "linear",
    "symbol": "BTCUSDT",
    "timeframe": "1m"
  },
  "object_type": "database_seed",
  "row_count": 96,
  "schema_version": "2.0",
  "seed_id": "seed_881b3d2d784443d891f5b16099ac2cb4",
  "selected_ohlcv_columns": [
    "open",
    "high",
    "low",
    "close",
    "volume"
  ],
  "selected_range_end_ms": 1700005700000,
  "selected_range_start_ms": 1700000000000,
  "source_ohlcv": {
    "csv_sha256": "df6957c71cf229331b4a3645400c5099d8f2f0df28a88db6a7b614c241caad29",
    "first_timestamp_ms": 1700000000000,
    "last_timestamp_ms": 1700005700000,
    "market_id": {
      "exchange": "bybit",
      "market_type": "linear",
      "symbol": "BTCUSDT",
      "timeframe": "1m"
    },
    "persistence_status": "committed",
    "row_count": 96,
    "schema_version": "1.0",
    "sidecar_schema_version": "1.0",
    "sidecar_sha256": "8be328a72650a83566c274f4fe7adf253d72ebe778d7eabf782ef8f29874b434",
    "validation_status": "ok"
  },
  "source_row_count": 96,
  "values_sha256": "680d3a8078fe75bc6686d345db486f437d7dd0d8e323426a0481e89418ea6e14"
}
```

### Database revision after explicit Collection addition (DatabaseRevisionManifestV4)

```json
{
  "collection_sources": [
    {
      "collection_id": "ac_1b7067ad44b948cfbb8c92aa2843a6ed",
      "revision_id": "c5aef9c11a722ecc641438df0240dd08cb57da8e6970363a5838b1d148165960"
    }
  ],
  "column_count": 7,
  "column_mapping": {
    "close": "close",
    "high": "high",
    "low": "low",
    "open": "open",
    "sma_3": "sma_3",
    "ts_ms": "ts_ms",
    "volume": "volume"
  },
  "created_at_utc": "2026-10-08T18:37:17.670972Z",
  "database_id": "db_8081c12eeb244750bc1b8968f30215b0",
  "dependency_edges": [],
  "description": "",
  "display_name": "Example owned Database",
  "first_timestamp_ms": 1700000000000,
  "last_timestamp_ms": 1700005700000,
  "market_id": {
    "exchange": "bybit",
    "market_type": "linear",
    "symbol": "BTCUSDT",
    "timeframe": "1m"
  },
  "members": [
    {
      "artifact_id": "8b97200d16b7217b7215c987f10ab4be4f3d7cce6524df4e7901e2c953328bfd",
      "kind": "indicator",
      "logical_artifact_id": "a22062e239f7a6fee2e492249e5bf1ab1c4f035924bf4d802c7532578c81016e",
      "output_names": [
        "sma_3"
      ],
      "portable_recipe_id": "f1c9ae4fd142ff1a69b5b93890aa93cee28d79c25604cae509dc47e0cb18095c",
      "tool_key": "sma",
      "values_sha256": "6ae09d34fcb34c25fc1697f7c40abe91f8a3e56c8cc01b184b9c3c36fb38ca04"
    }
  ],
  "object_type": "database_revision",
  "previous_revision_id": "75cbe4789e2f92679629a364b24b58f1cd99ad2c9312223b4f5eb7774842e2e2",
  "revision_id": "607b0dd9dedabfb321ff0cbb8a7c5e9e6c6f75f29587c67629b238c5d894215a",
  "row_count": 96,
  "schema_version": "4.0",
  "seed_id": "seed_881b3d2d784443d891f5b16099ac2cb4",
  "selected_outputs": [
    {
      "column_name": "sma_3",
      "logical_artifact_id": "a22062e239f7a6fee2e492249e5bf1ab1c4f035924bf4d802c7532578c81016e",
      "output_name": "sma_3"
    }
  ],
  "selection_sources": [
    {
      "column_names": [
        "sma_3"
      ],
      "source_id": "ac_1b7067ad44b948cfbb8c92aa2843a6ed",
      "source_kind": "collection",
      "source_revision_id": "c5aef9c11a722ecc641438df0240dd08cb57da8e6970363a5838b1d148165960"
    }
  ],
  "source_ohlcv": {
    "csv_sha256": "df6957c71cf229331b4a3645400c5099d8f2f0df28a88db6a7b614c241caad29",
    "first_timestamp_ms": 1700000000000,
    "last_timestamp_ms": 1700005700000,
    "market_id": {
      "exchange": "bybit",
      "market_type": "linear",
      "symbol": "BTCUSDT",
      "timeframe": "1m"
    },
    "persistence_status": "committed",
    "row_count": 96,
    "schema_version": "1.0",
    "sidecar_schema_version": "1.0",
    "sidecar_sha256": "8be328a72650a83566c274f4fe7adf253d72ebe778d7eabf782ef8f29874b434",
    "validation_status": "ok"
  },
  "value_provenance": {
    "dependency_edges": [],
    "members": [
      {
        "artifact_id": "8b97200d16b7217b7215c987f10ab4be4f3d7cce6524df4e7901e2c953328bfd",
        "kind": "indicator",
        "logical_artifact_id": "a22062e239f7a6fee2e492249e5bf1ab1c4f035924bf4d802c7532578c81016e",
        "output_names": [
          "sma_3"
        ],
        "portable_recipe_id": "f1c9ae4fd142ff1a69b5b93890aa93cee28d79c25604cae509dc47e0cb18095c",
        "tool_key": "sma",
        "values_sha256": "6ae09d34fcb34c25fc1697f7c40abe91f8a3e56c8cc01b184b9c3c36fb38ca04"
      }
    ],
    "outputs": [
      {
        "artifact_id": "8b97200d16b7217b7215c987f10ab4be4f3d7cce6524df4e7901e2c953328bfd",
        "column_name": "sma_3",
        "first_timestamp_ms": 1700000000000,
        "last_timestamp_ms": 1700005700000,
        "logical_artifact_id": "a22062e239f7a6fee2e492249e5bf1ab1c4f035924bf4d802c7532578c81016e",
        "output_name": "sma_3"
      }
    ]
  },
  "values_sha256": "7a1b5bac2ee2a7d9a96d349cd7c40b8ad1c8f1497762139751f0a79b2572c957"
}
```

The example Database has 96 rows, all five base columns and `sma_3`. The initial SMA warm-up values remain NaN; this is valid full-axis composition. A repeated content edit is a no-op. Example hashes and complete generated files are retained in `Leo_V2_Task_Packages/20261008_DMS_Documentation_Complete_Map/EXAMPLES.json` and `generated_examples_verified/`. The original October 8 validation harness used explicit Windows extended paths for its deep isolated root; that historical long-path finding was resolved at code/package level by R02 on 2026-10-27. Canonical reader/enumeration/deletion spelling and demonstrated ordinary-long-root rollback are described in the entry manual section 10. Six file-symlink cases and actual UNC/native/registry behavior remain unexecuted. These original examples and hashes are not regenerated by R07.

## UTC database V6 contract (2026-10-13 extension)

`DatabaseRevisionManifestV6` retains physical value-provider segments and the
explicitly incomplete V5 legacy provenance forms. Its added `utc_classification`
descriptor contains exactly `schema_version` (`1.0`), `filename`
(`utc_classification.json`) and `sha256`. The descriptor participates in the
normal deterministic revision identity.

The V6 revision directory contains exactly `manifest.json`, `values.csv` and
`utc_classification.json`. V1–V5 retain their original two-file contract. The
sidecar is canonical JSON with schema `1.0`, a `reports` mapping and an
`associations` list. Report keys are hashes of the existing Artifact analysis
serialization, not separate detection identities. Values are full UTC analysis
mappings, or `{}` for copied legacy unavailability.

Each association has exactly `artifact_id`, `logical_artifact_id`, `column_name`,
`output_name`, `first_timestamp_ms`, `last_timestamp_ms` and `report_sha256`.
Its provider/column/coverage must equal a selected UTC physical-value segment.
Every report must be used, every such segment must be covered, and one physical
Artifact must have one report. Formation anchors can precede a provider's suffix;
the association does not claim that provider supplied earlier database values.

`LoadedDatabaseRevision.utc_classification` is copied bytes or `None`. The store
checks the declared file set, sidecar hash, report hashes, validated UTC schema
and associations before exposing a revision. No read fallback loads a source
Artifact. Seed-only and non-UTC publication do not force V6. Old revision bytes,
IDs and unknown legacy provider identities remain unchanged.

The existing compatibility rule remains market identity, row count and first/
last timestamps. Classification checksums are integrity/provenance evidence,
not an additional market-data compatibility condition. A plain values.csv export
does not include the classification sidecar. Full fields, examples and causal
limits are documented in [UTC classification](../analysis_docs/UTC_CLASSIFICATION.md).
