# Data Manager workflows and object lifecycles

**Targeted revision: 2026-10-28 (R07).** Reconciles accepted R01-R06 and current source. Earlier edition dates and validation counts below remain historical; R08 integrated and R09 native acceptance are separate, not performed by this documentation revision.

**Updated:** 2026-10-08. Read with [scope](DATA_MANAGER.md),
[architecture](DATA_MANAGER_ARCHITECTURE.md),
[data contracts](DATA_MANAGER_DATA_CONTRACTS.md) and the
[companion map](Leonardo_V2_Data_Manager_Suite_Complete_Map.pdf).

These are current workflows and their mutation boundaries. A plan is a reviewed
read model, not a reservation that bypasses later checks. Success means the
correct domain state and visible outcome, not merely a button callback. Failed
and cancelled operations must preserve the guarantees of their actual publication
boundary; do not infer one global transaction around every multi-stage workflow.

## 1. Open, initialize, select and inspect

1. Main application opening creates or focuses the single retained Suite. A new
   Suite opens maximized; reuse retains its current geometry. Its presenter begins
   a new DMS integrity-evidence session.
2. Foreground warm-up shows Loading Data Manager, performs `reconcile_status`,
   then scans product catalogs. Warm-up succeeds only when valid catalogs have
   been applied. A failure stays visible; Refresh can retry with `force=True`.
3. Select Dataset opens one retained selector. It lists accepted and rejected
   summaries. Exchange -> Market Type -> Symbol -> Timeframe filters cascade;
   text filters combine with them using AND. Filtering/sorting changes the view
   only. No active market is invented from the first row.
4. Selecting an accepted canonical MarketId inspects that market, updates the
   selected summary, scopes relevant catalogs and synchronizes creation targets.
   A rejected row cannot become the active target. Changing selection invalidates
   old creation/update plans.
5. The main Catalogs tab exposes Environments, Recipes, Recipe Collections,
   Artifacts, Artifact Collections, Seeds and Databases. Global definitions remain
   global; Current Dataset limits market-bound products. All Datasets exposes
   saved orphan products when their OHLCV no longer exists or is unselected.
6. Inspect a current object or select an exact history row. Loading history does
   not advance a head, rewrite an object or refresh it from upstream providers.

Normal catalog/currentness work is metadata-only. Dataset or Artifact preview
consumes the corresponding payload and uses its existing read checks; it is not
an instruction to validate every object in the pool. Invalid products are exposed
with reasons where the catalog can represent them; a malformed structure that
prevents an exact load fails clearly, without automatic normalization.

Open Notebooks routes to the shared active Research Suite and its existing
Notebook Manager. It is available without an active DMS market when not blocked
by work. Notebook editing, dirty Save/Discard/Cancel and assignments remain
Research lifecycles, including its restore admission guards.

## 2. OHLCV lifecycle at the DMS boundary

Connection/download and Maintenance own candles, validation, repair and deletion.
DMS consumes accepted canonical identity and evidence; it neither accepts a raw
file by itself nor supplies a second OHLCV writer/validator.

Creation or calculation starts from accepted source evidence. A consuming
operation verifies the selected source and required inputs, using successful
evidence cached only in the current DMS session/source generation. Mutation
notifications invalidate affected evidence and reviewed context. Merely renewing
validation metadata for unchanged CSV does not require new calculation versions
when the calculation's actual inputs remain unchanged.

Deleting OHLCV through Maintenance removes the reviewed CSV/sidecar only. It does
not cascade into Recipes, Artifacts, Collections, Seeds or Databases. V2 Seeds and
Database revisions own values and remain historical snapshots. A legacy V1 Seed
is reference-based, so operations needing its original values can still require
the source. Missing input blocks a new calculation or append that needs it;
it does not prohibit removing stored derived Database content.

### Controlled Windows replacement failure and supported recovery

The original intermittent Windows replacement cause is still unknown. A later
controlled locked-handle reproduction verified failure reporting, temporary-file
cleanup and preservation of the last successful CSV/metadata pair, while saved
Seeds/Databases stayed unchanged. If a newer page was already committed before
a later page failed, an interior source gap can remain. Update Latest alone may
finish without repairing that gap. The supported path is Maintenance validation
-> Plan Repair -> explicit review -> repair -> validation/acceptance. This
evidence does not prove that every I/O failure is recoverable or authorize
speculative retries, new locks or changes to the writer.

## 3. Study Environment inspection and Recipe derivation

An Environment is owned by Research and contains ordered Study definitions.
DMS can list it, inspect its entries and classify their portability. It is an
optional definition source; users may instead work directly with saved Recipes,
Recipe Collections or direct Artifact creation.

1. Load the exact saved Environment and capture its identity/content hash.
2. Classify entries and resolve requested root entries plus required supports.
   Canonical tool and dependency rules determine whether a graph is portable;
   do not relabel an unsupported entry as a supported calculation. Artifact-backed
   entry derivation uses proven saved calculation identity where available.
3. Plan Recipe definitions, dependency order, actions, provenance and blockers.
   Global semantic equivalence may identify existing Recipes or an equivalent
   Recipe Collection; names and originating Environment are not calculation keys.
4. Execute only the current unblocked plan against its reviewed Environment
   evidence. Persist or reuse Recipes and record origin/provenance separately.
   Create/reuse a Recipe Collection only when explicitly requested.
5. Return separate created/reused Recipe and new/existing provenance outcomes and
   the Collection outcome. Refresh affected catalogs after successful publication.

Later Research edits do not mutate the already derived Recipes. Deleting the
Environment or removing a Study definition from it does not delete those Recipes
or their calculated products. Research Apply is transient; Research explicit
Save is a separate canonical publication route that DMS subsequently discovers.

Both GUI derivation routes pass `expected_environment_content_hash=plan.environment_content_hash` through the existing application command. Execution compares two freshly built plans and the reviewed hash before persistence, then reloads and compares the Environment after the publication gate and before writes. A changed saved definition requires Preview again. Programmatic `None` retains the explicit no-preview compatibility path and execution-time checks; GUI requests must carry their token. Equivalent Recipe reuse and provenance remain separate from that reviewed-intent check.

## 4. Portable Recipe and Recipe Collection lifecycle

### Portable Recipes

A Recipe is an immutable, global calculation definition. Its actual tool,
parameters and input graph determine semantic equivalence. It has no MarketId,
chart lifetime or mutable numerical values. A changed calculation is a different
Recipe, not an in-place edit to its meaning. Origin records may accumulate without
changing calculation identity. First-persisted age is owned metadata; filesystem
timestamps do not establish authoritative age for legacy Recipes.

Creation routes include Environment derivation, explicit Research Save and DMS
Artifact creation. All use the same semantic authority. New persistence
normalizes execution selectors already represented by explicit input roles;
loading older valid Recipes does not rewrite them. Dynamic Binning is excluded.

Delete requires explicit confirmation and authoritative Recipe-domain dependency
checks. Other Recipe dependencies and **historical** Recipe Collection membership
can protect a Recipe. Artifact-domain provenance is not a runtime ownership
dependency on a Portable Recipe and does not by itself block deletion. Failure
or dependency refusal must remain visible; deletion is not forced by removing a
row from the GUI.

### Recipe Collections

1. Choose explicit root Recipes and metadata. Plan the complete dependency graph:
   supports are included, edges identify exact roles/outputs, cycles and missing
   required definitions are refused.
2. Compare semantic set identity with existing Collections. Member order, name,
   description, origin or a different historical ID does not manufacture a new
   semantic calculation set.
3. Create or explicitly edit. Persist an immutable revision and select it with a
   mutable head, retaining preceding revisions. A reused semantic winner is
   reported as reuse, not silently claimed as a new object.
4. Inspect any exact revision without changing the head. Materialize chosen
   roots/revision on a market only through an explicit calculation request.
5. Delete removes that Collection's owned head/revisions, not member Recipes or
   Artifacts. Removing a member from the current revision likewise does not
   delete its Recipe or remove references from immutable older revisions.

## 5. Direct Artifact creation and Recipe materialization

### Direct creation

Preconditions: current accepted market, valid canonical tool/parameters, available
eligible input roles and no conflicting foreground operation. Open Create
Artifact, obtain the current setup/source catalog, configure the request and
choose Calculate Artifact. This means durable calculation/publication or reuse;
there is no transient Research-style Apply step.

The domain resolves one portable definition graph, including saved-input
calculation semantics and raw OHLC selectors, then resolves target source and
dependencies. It creates/reuses global Recipes through their owner and prepares
market-specific Artifact results. Equivalent direct and existing-definition
routes must converge on the same semantic calculation. No Artifact Collection
is automatically created by ordinary direct creation.

### Materialize existing definitions

Select explicit Recipe roots or an exact Recipe Collection revision and target
market. Planning returns complete root/support closure, dependencies, stages,
source evidence, current physical heads, create/reuse decisions and blockers.
Preview is read-only. Execution requires that exact current unblocked plan.

1. Resolve every role to accepted OHLCV or a valid exact saved output. Verify the
   required graph in dependency order; supports precede dependents.
2. Calculate on the complete accepted timestamp axis using Financial Tools.
   Retain legitimate warm-up/interior NaNs, categorical values, output schema
   and internal precision; do not trim the axis to all-finite rows.
3. Prepare immutable values, metadata, market-bound execution recipe, version
   record and proposed logical head. Reuse exact current results where allowed.
4. Recheck reviewed source/head evidence at publication. Publish the managed
   graph through ArtifactService, using its supported rollback/cleanup boundary.
   Do not intentionally expose a partial new head set on graph failure.
5. Report created/reused physical versions and advanced logical heads. Existing
   versions remain inspectable. DMS refreshes relevant views immediately.

Graph publication safety is not a guarantee that a larger workflow containing
Recipe persistence and later Collection publication is one crash-atomic operation.
A completed independently published product may remain after a later stage fails.

R02 code/package resolution (2026-10-27) replaces the unresolved DMS-DOC-F1 status. Canonical Artifact readers/enumeration and deletion use the existing Windows-aware `_io_path` while preserving containment, link/junction refusal, exact allowed-name cleanup and propagated failures. IDs, formats and hierarchy do not change. Demonstrated ordinary-long-root DIRECT and RECIPE post-head source-change rollback restores owned payloads, market-local Recipes, heads and versions; legitimate global portable definitions remain distinct. Six file-symlink cases, actual UNC shares and native/registry behavior remain unexecuted. This is not universal crash atomicity, arbitrary-depth writer support or a repair of the earlier unidentified CSV replacement mechanism.

## 6. Batch Constructs

Batch is explicit expansion of a reviewed set, not recursive discovery of newly
generated results. Supported families are derivative, angle, percent_span_angle,
angle_momentum, delta, trap_area, braids and braid_instability.

Source scopes are Selected Signals, All Indicators, All Oscillators and All
Constructs. Automatic family scopes contain eligible saved Artifact outputs
only. Selected Signals can include raw current-dataset Open/High/Low/Close.
Raw Volume is prohibited. A saved Volume Artifact can supply an eligible output
under the canonical saved-source policy. Raw sources never invent Artifact IDs.

| Expansion | Exact behavior |
|---|---|
| derivative / angle | One branch per resolved signal, role `source` |
| percent_span_angle / angle_momentum in automatic expansion | One branch per resolved signal, role `source_1`; explicit multi-source requests retain numeric source-role order |
| delta | One current fixed signal in fast or slow role against each other resolved signal; skip the identical fixed signal |
| braids / braid_instability | User-specified fast/mid/slow triples from the resolved pool |
| trap_area | User-specified fast/slow pair or fast/mid/slow triple |

No implicit Cartesian-product expansion is added. Tool parameters, output names,
source roles, dependencies, semantic collisions and destination compatibility
are checked before execution. Changing a raw source column changes calculation
identity. Repeating an identical saved-only, raw-only or mixed raw/saved request
reuses its current semantic results, including shared supports.

The workflow is configure -> Preview -> review New/Reuse Current branch rows ->
Execute -> terminal report. Destinations are individual results, a new Artifact
Collection, or an existing Collection revision. The plan holds the exact input
set and destination; stale evidence or changed configuration requires a new
Preview. Existing destinations require compatible coverage and collision-free
column mappings. Execution cannot recurse into its own newly produced outputs.

Suite Operation remains the foreground progress surface. The Batch terminal
report summarizes the reviewed branches and New/Reuse counts; it is not another
task lifecycle. Successful execution invalidates Preview. Closing that report
does not close the Batch window.

Cancellation before a Collection commit preserves that Collection head. Recipes
or Artifacts already independently published by an earlier phase can remain.
Report that real boundary rather than claiming a rollback of every product.

The Operation view uses typed result evidence for `Published` and `Publication evidence`. New Artifacts, versions or advanced heads demonstrate publication; a materialization with only reused outputs and no returned Collection reports no new publication. A stored Collection revision alone does not reveal new versus reused and is reported as unknown. Construct batch combines its materialization result with the optional Collection result. Failed/cancelled status or an unexpected result type reports unknown, never inferred rollback. Recipe derivation separately reports created/reused Recipes, provenance and its explicit Collection outcome.

## 7. Managed Artifact update, history and deletion

A managed Artifact has a logical identity and immutable physical versions. Its
current head identifies one version; its embedded execution recipe and lineage
permit loading a saved version even when the global Portable Recipe file is gone.

Preview Update on selected Artifact roots resolves all required dependencies,
the current accepted source, starting heads, and canonical per-tool update
strategy. Node actions distinguish REUSE_CURRENT, UPDATE, RECREATE and BLOCKED.
The plan includes mathematical context and revisable-tail requirements. There
is no generic rule that every tool can append only one value or must always
recalculate its full history: the existing Financial Tools policy decides.

Execute Reviewed Update recomputes/validates required results, checks overlap
where that policy requires it, and rechecks source/head evidence before
publication. Actual updates create new immutable versions. Unchanged CSV with
renewed sidecar validation and unchanged consumed inputs reuses existing versions;
provenance fingerprints are not a fourth generic materialized compatibility gate.

Updating an Artifact does not advance any Artifact Collection or rewrite an
owned Database snapshot. Exact older versions remain readable. A shorter or
historically changed source is classified by the current source/update rules;
it is not permission to rewrite a Database's retained cells.

Pool deletion targets a logical Artifact's owned version history through the
authoritative service. Genuine dependent Artifact lineage and Artifact Collection
references, including retained history, can block it. Copied Database provenance
is not an upstream deletion blocker. Deleting or removing imported Database
content does not itself delete the pool Artifact.

## 8. Artifact Collection lifecycle

An Artifact Collection is a market-bound graph of exact saved versions, explicit
roots/supports, output selections and Database column mappings. It is independent
of a Recipe Collection and does not follow later Recipe or Artifact edits.

1. Select logical roots and inspect the current exact versions. Plan complete
   required support closure and role/output edges.
2. Admit materialized objects by canonical MarketId, row count, and first/last
   timestamps. Check each consumed payload's integrity and required dependency
   closure separately. Different historical source fingerprints are not by
   themselves a fourth compatibility rejection.
3. Choose outputs, unique canonical Database column names and complete presentation
   order. Required supports remain present/locked. At least one root is required.
4. Publish a new immutable Collection revision using reviewed head/source evidence,
   or report an existing equivalent semantic winner. A head points to the current
   revision; historical revisions remain loadable.
5. Explicit Edit can add/remove roots or change supported output/metadata choices.
   Pure removals retain saved versions/mappings for retained content. Remove only
   graph members no longer needed; shared supports survive.

Collection validation/update assesses compatibility; it does not calculate
Artifacts, move all member heads or synchronize a Database. If new current
Artifact versions are desired in a Collection, the user must perform the explicit
permitted Collection operation and review the resulting revision.

Delete removes the Collection's owned head/revision persistence after confirmation.
Member Artifacts and all copied Database values survive. A Collection's historical
Artifact references are genuine references until the Collection itself is removed.

## 9. Database Seed lifecycle

New Seed creation captures the full accepted OHLCV source. It requires Open,
High, Low, Close in canonical order, with optional Volume. There is no arbitrary
column selection or date-range trimming in this creation route.

Preview captures source evidence, complete values and plan identity. Execute
checks the candidate against current accepted source again at publication, then
saves a V2 manifest/values pair. Failed/cancelled creation must not advertise a
successful Seed. V2 values remain independent of later source growth or deletion.

Existing V1 Seeds are reference-format objects; V2 Seeds own values. Enumeration
understands both `seed_<id>.json` and `seed_<id>/`. If both layouts claim one ID,
loading fails closed. Do not rewrite old Seeds merely by listing them or weaken
global path-safety checks to accommodate the two layouts.

### Explicit Seed append

Plan against the exact saved Seed/values and accepted source. A new suffix must
have compatible identity/start/coverage. Historical snapshots may remain as they
are. A shorter source or conflict does not authorize shrinking or overwriting.
Execute rechecks the plan and copies only the required suffix, preserving the
previous CSV bytes as a prefix. No-op growth returns without publication.

The store protects the manifest/values pair using its existing append recovery
record and verified backup. The commit boundary is removal of the pending record;
while it exists, reads expose the prior committed pair. Recovery is explicit in
that store protocol, not a new general transaction service. Append preserves
the Seed class: V1 updates its reference manifest, while V2 publishes its owned
pair. It does not migrate a V1 Seed into a V2 Seed.

Deleting a Seed removes only its owned persistence. A Database already created
from it owns its values and does not disappear. The operation is explicit and
must honor existing safe-path and pending-publication checks.

## 10. Create a Database

The normal user path is Catalogs -> create/select a Seed -> preview Seed-only
Database creation -> confirm publication. Recipe derivation, Artifact creation
and Collection creation are optional independent workflows, not prerequisites
for an OHLCV-only Database.

Planning reads the Seed's current identity/hash, exact base values, requested
name/description, columns, row count and coverage. V2 can provide its owned base
without live upstream OHLCV. A legacy V1 reference still needs its referenced
source to obtain values. Execution regenerates/checks the reviewed plan and
rechecks Seed evidence at publication.

Initial publication creates an immutable Database definition, a V4 revision
manifest with empty derived membership/provenance for a Seed-only Database,
copied values and a head. The revision's values hash must agree with those bytes.
The store validates staged values and predecessor expectations, then publishes
through its existing revision/head protocol. On supported failure paths, old
heads/history remain intact and incomplete new publication is cleaned up.

The older full creation workflow can build from explicitly reviewed Seed and
Collection state through domain APIs, but the retained staged GUI is not the
active navigation route. Both routes must satisfy the same full-axis snapshot
and compatibility rules. No leading warm-up trimming, interior-NaN row removal,
or future subscription to the imported Collection is implied.

## 11. Edit Database content without upstream ownership

The Artifact and Collection editors are separate retained window contexts with
different IDs. Both use Preview and Apply. Their request changes derived
membership/columns; base `ts_ms` and mandatory OHLCV base columns are not removed
through this operation.

| Intent | Required truth | Mutation |
|---|---|---|
| Read / unchanged plan | Owned Database snapshot and local metadata | No new revision for a no-op |
| Add Artifact/Collection outputs | Incoming exact outputs, their required lineage and three-rule compatibility with the stored frame | Copy incoming columns into a new revision; preserve retained columns |
| Remove derived outputs | Stored column names and existing ownership/provenance | New revision omits removed columns; providers may already be deleted |
| Mixed add/remove | Local retained state plus only the incoming required evidence | New revision with reviewed final membership and ownership |

An included column can have direct Artifact and/or Collection selection owners.
Removing one source owner is not necessarily removal of the physical column if
another retained owner still includes it. Explicit output removal and the final
reviewed source mapping determine the result. Distinct outputs cannot silently
collide into the same name. Retained values, textual numerical tokens where
preserved by the editing path, row axis and old revisions remain unchanged.

Execution refuses a stale starting revision or changed incoming evidence. A
source Collection's subsequent edit does not update the Database's copied
membership. A deleted original Collection or Artifact need not exist for no-op,
local removal or an unrelated valid addition. The snapshot's own validity is
still required; missing providers do not excuse corrupt owned bytes.

### Legacy attribution

V1-V4 remain readable. When an explicit edit must retain unknown legacy
column-to-Artifact or Collection attribution, V5 preserves the original canonical
manifest and records the unknown information honestly. It does not guess from
the last surviving candidate or create fictitious IDs. Ordinary fully attributed
new revisions remain V4. Loading/no-op does not migrate files, and earlier
revision bytes remain unchanged.

## 12. Append a Database

Preview Update returns CURRENT, APPEND or BLOCKED for the current operation.
Legacy REBUILD_REQUIRED vocabulary may remain in read models; the rebuild
execution endpoint is retired and rejects requests.

1. Load the current owned revision and accepted source. If there are no new rows,
   do not require providers for nonexistent suffix values or publish a revision.
2. For real growth, require compatible identity/start and a valid continuous
   suffix. A shorter/conflicting source blocks append while leaving the historical
   snapshot usable; it does not shrink it.
3. For every retained derived column, prove a usable provider and its required
   inputs/coverage. A missing or ambiguous provider blocks with a concrete reason.
   Artifact calculation/update is a separate explicit operation, never hidden
   inside Database append.
4. The user may remove unsupported content in the existing editor, or recreate/
   update a provable provider through existing calculation paths, then replan.
   A previously validated exact appended segment can prove its logical provider
   for a later suffix without requiring unrelated deleted original candidates.
5. Execute only the matching unblocked APPEND plan. Recheck source, starting
   Database revision, Artifact heads, provider bindings and reviewed evidence
   before publication.
6. Copy the existing values and append the new suffix. Preserve every prior cell
   and NaN, even if newer Artifact calculations now produce different historical
   values. Extend physical value-segment provenance without relabeling old history.
7. Publish a new immutable revision, advance the Database head and invalidate/
   refresh currentness. Old revisions are still exact historical snapshots.

For a V5 unbound legacy column, an exact future segment cannot overlap original
unbound coverage. Future provider proof does not retroactively establish the
unknown historical binding. Missing providers and stale plans are refusals, not
authorization for automatic removal, backfill, rebuilding or metadata repair.

## 13. Reconciliation and change notification

Reconciliation discovers truth. It classifies source change and product currentness,
returns reasons/blockers and an evidence signature, and never updates numerical
Artifacts or Databases by itself. Source classifications include unchanged,
append-only, historical mutation, truncation, invalid source and identity mismatch.
Product validity, currentness and Database readiness are distinct questions.

After warm-up, silent background requests use Core and are coalesced. Matching
results update the current view; stale generations/selections do not. Unchanged
evidence avoids repeated scans/view churn. Pending market catch-up ensures a
new selection receives the corresponding result. Foreground success immediately
refreshes its relevant catalogs and retained child context; background work
verifies that state afterward and does not erase the foreground terminal report.

Before proof reuse, DMS compares session/market generation, exact accepted source metadata and both CSV/sidecar stat fingerprints `(st_size, st_mtime_ns, st_ino)` (inode defaults to zero when unavailable). Metadata and file identities are checked again before return. A mismatch drops cached proof and uses the existing strict loader parse/hash path; successful proof retains the timestamp axis, not another full-values cache. This protects against observed replacement even without GUI invalidation, not hostile same-stat tampering or continuous file watching.

## 14. Duplicate Maintenance and pool deletion

Duplicate Maintenance is user-initiated: preflight -> background scan -> results
-> reviewed safe purge -> terminal outcome. It is not a startup cleanup pass.
Recipe and Recipe Collection scans are global; Artifact/Artifact Collection
scans are scoped to selected MarketId and exact source fingerprint.

Semantic equality excludes names/origins where the object contract says they are
metadata. Legitimate historical Artifact versions are not duplicate current
objects. Trustworthy first-persisted age selects canonical Recipe winners;
unknown legacy age can require REVIEW REQUIRED with no automatic purge.
The scan result is not permission to skip later checks: each purge candidate
passes current evidence and the normal domain-specific dependency/deletion gate.

| Delete target | Owned persistence removed | Surviving independent objects |
|---|---|---|
| Recipe | Definition and exclusively owned metadata/provenance, if Recipe references permit | Existing Artifacts/Database snapshots |
| Recipe Collection | Its head and revisions | Member Recipes and Artifact-domain products |
| Managed Artifact | Its logical lineage/version-owned persistence when genuine references permit | Copied Database values and global definitions |
| Artifact Collection | Its head/revisions | Member Artifacts and copied Databases |
| Seed | Its reference file or owned pair | Databases already copied from it; OHLCV |
| Database | Definition, head and owned revisions/values | Seeds, Artifacts, Collections and OHLCV |

History may legitimately block deletion of a referenced Recipe or Artifact.
Removing a current membership does not erase history. A Database's copied
provenance is not that kind of live upstream ownership. Never infer cascade
deletion from a visual tree or from the word "source".

## 15. Cancellation, close, reopen and restart

An ordinary confirmation Cancel submits no operation. Once work starts, Suite
Operation shows the managed task's actual ID, progress, state, error and current
cancel availability. A cancellation request is cooperative; the view must wait
for actual settlement. A publication gate may reject a late request after its
non-interruptible boundary begins. Already published earlier-stage objects are
reported honestly rather than erased by an invented global rollback.

Closing a child invalidates its target and reviewed context; late callbacks must
not reopen it. Closing the Suite stops scheduling, closes bounded children,
requests cancellation of owned work, disposes the presenter and ends its evidence
session. Core/LeonardoApp retain final task and application shutdown authority.
There is no Suite-owned worker kill or alternate success status.

Opening again after disposal creates a fresh GUI pair with new request correlation
and warm-up; opening an already retained Suite instead focuses that same window.
Persisted objects are scanned through their canonical stores. Exact history is
still available. A closed DMS does not own or close an independently opened
Research Notebook lifecycle merely because its shortcut originally opened it.
Main application shutdown still applies Research's dirty close guard.

## 16. End-to-end reference scenario

Open DMS, finish warm-up, and select accepted BTCUSDT 1m. Create a full-source
Seed with Volume, then create a Seed-only Database. Create an SMA Artifact and
a dependent eligible Construct, using canonical sources and explicit publication.
Save their selected outputs in an Artifact Collection and add that Collection
to the Database through Preview/Apply. The Database now owns copied values and
explicit imported membership, including original NaNs.

Edit the Collection independently: the Database does not follow it. Delete that
Collection if its ordinary gates permit: the Database remains readable. Remove
one stored derived Database column even if its original provider is gone; pool
objects are not removed by that membership edit.

After OHLCV grows and is accepted, reconcile. Explicitly update any required
Artifact providers, then preview Database append. Resolve any missing retained
provider by removal or provable recreation and replan. Append publishes a new
revision containing the exact old prefix and new suffix. Inspect the preceding
revision to confirm its unchanged history. Close/reopen DMS and inspect the same
saved objects; no startup operation recalculates or purges them.

The [acceptance matrix](DATA_MANAGER_DATA_CONTRACTS.md#9-observable-acceptance-matrix)
ties these outcomes to existing executable evidence. The original 8 October 2026
documentation validation reproduced a Windows long-path Artifact-read defect in
generated data, recorded in the [entry manual](DATA_MANAGER.md#18-validation-and-acceptance)
and canonical audit package. No behavioral correction was applied in that edition.
R02 subsequently resolved DMS-DOC-F1 at code/package and scoped-validation level
on 27 October 2026, including the demonstrated ordinary-long-root read and
post-head rollback paths. Its recorded platform and native-acceptance limitations
remain; the earlier CSV replacement mechanism remains unidentified. Settled DMS
ownership/lifecycle policy and deferred performance work remain unchanged.

## UTC classification lifecycle extension (2026-10-13)

New UTC calculations attach formation, origin, timing and continuation records
to their nonvisual analysis. Saving them uses existing Artifact analysis bytes
and identity. Loading an old empty-analysis UTC Artifact preserves that exact
legacy state; neither load nor linked Study restore enriches it automatically.

Explicit direct or Collection import copies metadata for the reviewed physical
UTC providers alongside selected values. V6 associations retain each output
alias and covered timestamp segment. A UTC dependency alone is not an implicitly
selected analysis context. Several UTC instances remain separate.

Partial removal retains a provider report while a selected output still uses it.
Last-output removal drops it from the new revision. Earlier revisions remain
unchanged, and retained copied evidence survives deletion of the original
Artifact. Sidecar deletion belongs to the database's existing owned-file path.

Append preserves old values and copied reports, then adds each new provider with
its actual suffix coverage. A new formation may start before that suffix and
become confirmed later. Existing confirmed formation facts cannot be silently
rewritten. Conflicts require explicit replacement/new-build review; the existing
retired rebuild command remains rejected. New build or reviewed removal/import
publishes matching values and metadata together.

Stage, flush, reviewed-evidence/cancellation checks, publish and head update remain
one transaction. Missing files, wrong hashes, conflicting associations, stale
evidence or failed publication reject the revision; rollback accounts for the
sidecar. Ordinary V1–V5 load writes nothing. Retained old UTC segments keep
classification unavailable instead of retrieving new claims from live providers.

See [UTC classification](../analysis_docs/UTC_CLASSIFICATION.md) for exact timing,
legacy semantics, full payload fields and DAS consumption.
