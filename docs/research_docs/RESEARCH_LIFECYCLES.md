# Research Suite workflows and object lifecycles

**Targeted revision: 2026-10-28 (R07).** Reconciles accepted R01-R06 and current source. Earlier edition dates and validation counts below remain historical; R08 integrated and R09 native acceptance are separate, not performed by this documentation revision.

**Updated:** 2026-10-08. Read after [scope](RESEARCH_SUITE.md) and
[architecture](RESEARCH_ARCHITECTURE.md). Field-level rules are in
[data contracts](RESEARCH_DATA_CONTRACTS.md).

The phases below describe existing control flow. They are not a proposal for
new state machines, queues or persistence. A refused action leaves its reason
in the relevant dialog, chart status or Research Activity. A disabled command
is a presentation aid; the receiving controller also checks current admission.

## 1. Open, reuse and close the Suite

Opening Research from the main application creates the active composition once.
Opening it again focuses the same Suite. Initial catalog work runs through Core;
the workspace starts empty, in Scroll 4, with Pan Anchor off and no live Snapshot
or Notebook assignment. Saved objects are not automatically loaded merely because
they exist on disk.

Accepted close first resolves any dirty Notebook decision. It then retires the
GUI presenter, cancels cancellable work, invalidates pending GUI intentions and
closes its chart-local and administrative windows. Chart sessions are disposed,
Qt objects are retired, and composition forgets the pair. Reopening constructs
a fresh Suite. Results belonging to a disposed presenter cannot reach that new
Suite. Core and durable saved pools survive Suite close.

Main-window close/Exit asks the same Research guard before closing the main
window or other suites. Cancel preserves all those windows and their tracking
state. A save already in progress can hold one accepted close continuation;
unrelated pending Notebook work refuses close. After a successful save the
accepted continuation runs once. A failed save does not retire the editor.

At application shutdown, Leonardo owns stopping the shared runtime. Research
does not terminate worker threads or invent successful task completion to make
shutdown appear finished. A write past its cancellation fence may settle after
GUI retirement; its actual result remains in TaskManager.

ResearchDatasetApplicationService performs terminal cancellation-map cleanup before outward GUI delivery, even when a retired presenter drops that delivery. Its finished event prevents reinsertion after early completion; progress/result callbacks use the existing dispatcher once, outside the service RLock. Actual task identity, active cancellation and GUI-thread ownership remain unchanged.

## 2. Select and load OHLCV

1. **New Chart...** starts a fresh accepted-catalog scan unless a scan is already
   pending. Repeated pending opens share the request; an already visible selector
   is reused. Scan failures are visible and a later opening can retry.
2. The selector uses Exchange -> Market Type -> Asset -> Timeframe from accepted
   summaries. It does not make a raw file accepted and cannot load by symbol alone.
3. Admission requires capacity below 16 and a current choice. Allocate the lowest
   free logical slot and a new session; register a free workspace position.
4. The chart presenter creates a dataset-open attempt and submits load through
   the dataset application service. Beginning a new dataset generation clears
   the old generation's resident data, Studies and pending attempts.
5. The loader rechecks canonical acceptance and current bytes, parses full OHLCV,
   validates the timestamp axis and returns an immutable dataset. A catalog row
   is not a promise that the source remains valid by the time loading occurs.
6. Accept only the matching task/session/generation attempt. Request a resident
   slice, install the viewport and project chart data. Initial navigation aligns
   the latest real candle; the chart becomes available for tools/navigation.
7. On cancellation, source change, invalid data or failure, settle the matching
   attempt and display the terminal reason. Do not publish partial data or attach
   an old result to a reused slot. Failed initial chart loading remains an error
   state the user can close; composite restore handles its own added-slot cleanup.

Research loading is read-only. It neither repairs CSV nor changes a validation
sidecar. Download/Maintenance owns any such action. A newly accepted source becomes
available on the next selector scan. An already-open chart keeps its immutable
dataset and Study results until explicitly replaced or reopened.

## 3. Chart placement, multiple sessions and navigation

Two charts may use the same MarketId and immutable loaded dataset while retaining
independent session IDs, Studies, viewports, styles and pane state. Changing the
active chart selects command context; it does not transfer studies between charts.

Move changes shell positions: moving onto another attached chart swaps positions;
moving into a free position relocates the chart. A detached chart's position is
reserved, and moving the detached chart or occupying its reserved position is
refused. Detach reparents the same panel to a tracked window. Dock returns it to
its position. Closing that detached window requests docking. Explicit chart
removal retires its presenter/session, dialogs and attempts and releases the slot
and position. Surviving sessions retain identity; attached panels are laid out
compactly in position order.

Scroll 4 and Fit 8 operate on attached panels only. Detached charts still count
toward the 16-chart capacity. The exact adaptive layout table is in the data
reference; Fit 8 applies the same rule independently to each of its two pages
when there are more than eight attached charts. Mode changes alter presentation,
not data, Study results or saved objects.

Horizontal navigation changes a chart-space viewport, which may include empty
padding around the real data axis. Go To resolves a UTC timestamp to the nearest
real candle (earlier candle wins a tie), centers the viewport and requests refill
when necessary. A resident refill projects an immutable range from the full
dataset; existing full Study results are sliced to that same range. No indicator
is recalculated solely because the camera moved.

Pan Anchor uses the source chart's user-originated horizontal navigation timestamp
to move other ready charts through their own timestamp resolver. It does not copy
row numbers between different timeframes, and does not turn an initial load,
restore or programmatic synchronization into a new source event. Guard feedback
to prevent recursive panning. Go To is single-instance for its chart. Autoscale
and manual vertical price bounds are chart-local; restoring a Snapshot reinstates
the stored choice. Crosshair updates are dynamic overlays, not static scene
rebuilds. Pane ordering and size are presentation, not changes to the results.

Oscillator resize and time-axis changes rebuild scene geometry through the existing refresh owner. Numerical series, timestamp order, NaNs and zero values remain unchanged; the pane keeps shared horizontal navigation. Camera/axis geometry changes do not create a new financial calculation.

## 4. Financial Tools and Study Apply

**Preconditions:** a ready chart dataset/session, current setup catalog, no
conflicting chart operation or Environment run, and a valid calculation draft.

1. Open the chart's Financial Tools dialog. Build its available tools, eligible
   source outputs and saved Artifact choices from the canonical specifications
   and the target chart's current Study snapshot. Reuse a current dialog; rebuild
   a stale catalog after the chart's Study set changes.
2. Choose tool, editable parameters, required source roles, display metadata and
   Apply. Parameters are resolved by the tool specification. A source role is
   explicit OHLCV, a same-session Study output or an exact saved Artifact output.
   Only eligible outputs may feed a construct; raw Construct input is Open,
   High, Low or Close, not raw Volume. An eligible calculated output is a separate
   case governed by construct-input policy.
3. Begin a correlated Study Apply attempt. Snapshot the required inputs; resolve
   exact market, fingerprint, source outputs and dependencies. Invoke the shared
   Financial Tools calculator on the full accepted dataset axis.
4. Validate returned schema and timeline. A result must correspond to the attempt,
   tool, full row count and dataset timestamps; preserve NaNs and categorical
   outputs. `PreparedStudy` has not yet changed the live session.
5. On the GUI thread, session acceptance rechecks attempt/generation/current
   dependencies. Only then publish a new `ChartStudy`, presentation defaults,
   resident projection and the corresponding overlay/pane.

Apply creates no durable Recipe, Artifact, Environment or Snapshot. On submission
failure, cancellation, calculation error or stale completion, the candidate
Study is not published. Existing Studies remain. A renderer uses renderable and
style-driver outputs according to the tool contract; analysis-usable does not
automatically mean visible.

### Applying a saved Artifact

Select an exact saved Artifact; validate current source lineage, tool and output
semantics, market and full timestamps. Load the stored values without recalculating
them, then publish a new session Study with a saved link and Artifact-mode setup.
Missing/stale/wrong-market lineage blocks Apply. Selecting an Artifact never
updates it to the current market behind the user's back. Dynamic Binning remains
blocked even if an old saved reference can be parsed.

### Applying more than one selected saved Artifact

The lifecycle presenter sequences selected requests against the same current
chart/session and uses the existing Study service for each. It tracks batch
identity and admission; it does not merge their calculations into a new financial
object. Results and failures must remain attributable to their individual task
and target. This batch is distinct from the rollback contract of an Environment.
It stops on the first failed/stale item; already applied items remain and the
status reports how many completed. It is not an all-or-nothing group Apply.

## 5. Study Edit, presentation and removal

Edit operates on the existing Study's tool and editable parameters, not a second
tool-selection flow. Keep its Study ID, display name and user metadata. Reject
edits while another Study depends on it; there is no automatic dependency-graph
recalculation cascade. Reject self-dependency and stale/foreign input identity.

Calculate the replacement without mutating the old Study. At acceptance recheck
attempt, target existence, full axis and dependency state. Successful Edit replaces
the numerical result, retains compatible presentation, and clears the old saved
link: the modified result is an unsaved calculation Study, including when the
original was Artifact-backed. It does not overwrite the old saved Artifact.
Failure/cancellation leaves the previous result intact.

Visibility, line/fill/marker/guide styles and pane arrangement are immediate
chart-local presentation changes. They neither change calculation parameters nor
write saved pools. Reset style regenerates accepted defaults. These changes can
be captured by a later explicit Environment/Snapshot save.

Remove first checks live dependents. A required Study cannot be removed until
its dependents are removed. Successful removal deletes only the transient Study,
its projection/presentation and pending edit/save acceptance. It leaves every
saved Artifact, Recipe, Environment, Snapshot and Notebook untouched. Late worker
completion cannot recreate that removed Study.

Study Style Apply/OK catches only `StudyPresentationValidationError`, displays inline feedback and emits no invalid or partial presentation patch. A corrected valid draft can apply normally; unrelated exceptions still propagate. This validation is separate from application theme-token validation.

## 6. Study Save and DMS publication

**Preconditions:** an existing full Study result and current accepted source;
source Study dependencies must have valid durable saved links when needed.
Saving a dependent Study does not silently save every unsaved dependency.

1. Begin a save attempt, snapshot the Study and sources, validate durable source
   references and exact dataset/Artifact lineage. Refuse missing, stale or
   unsaved dependency lineage with a reason.
2. Check cancellation before persistence. Crossing the existing fence makes this
   operation non-interruptible by a later GUI cancel request.
3. For a new result, persist its existing full calculation through ArtifactService;
   do not calculate again or trim initial NaNs. The service owns deterministic
   Recipe/Artifact identity and source fencing.
4. Validate the persisted result against the original Study, publish its portable
   definition graph, recheck source evidence, and publish managed Artifact graph
   records. An already linked Study is verified and its publication path reused;
   it does not become a second independent calculation merely because Save repeats.
5. Return `StudySaveOutcome`. Only a still-current session accepts its saved link.
   DMS catalogs can now discover the published objects without Research changing
   a Database or collection.

On publication failure, the implementation attempts removal of a newly created
invalid/stale Artifact; it does not delete a pre-existing Artifact as cleanup.
Report the actual exception, including cleanup failure. This multi-service path
is not a newly promised all-files crash transaction. Core terminal state remains
authoritative if the window closes after the persistence fence.

The Financial Tools form's **Save** first calculates/applies the draft once,
then calls this same Save path. If Apply succeeds but Save fails, the resulting
Study is still a transient result; a persistence failure must not be presented
as a successful durable save. **Apply** alone never enters this Save path.

## 7. Study Environment lifecycle

### Create and update

The save dialog selects a ready source chart containing Studies. Capture the
full Study definitions and current presentations from that exact session.
Translate runtime Study dependencies into Environment entry references; include
the required source entries in earlier/topological order. Retain calculation
mode for calculated Studies and exact Artifact mode for Artifact-applied Studies.
A calculated Study remains calculation mode merely because it has been saved.

Create requires a valid unique name. Update selects an existing pool object,
retains its ID and creation timestamp, and allows the current name/description
and definitions to change under naming validation. The store updates the content
hash and update timestamp. Switching the dialog back to Create clears the name
and requires a new valid one. Empty chart capture is refused.

An Environment is a definition snapshot. It contains no live chart ID, full values,
viewport, window geometry or task. `created_from` is provenance, not a general
market lock: a calculation-only Environment can apply to another accepted market.
Any Artifact references require exact `created_from` MarketId and current lineage.

Manage mode can also update the selected Environment's name, description and
entry metadata (important flag, dataset role and description) without applying
it to a chart. Those are explicit saved-definition changes, not formula edits or
automatic changes to charts or embedded Snapshot copies. Load mode presents those
details read-only. Changing the selected target chart requires a current
compatibility result for that target.

### Load and apply

1. List/load the selected pool Environment and check compatibility against the
   target dataset. Present blockers, including unavailable/stale Artifact outputs,
   missing dependencies and excluded tools. Do not change the file to hide them.
2. Choose Append (the default) or Replace and establish one run bound to target
   session/generation. Determine stable dependency
   order; keep a map from entry ID to newly created Study ID.
3. Apply one entry at a time through Study tasks, resolving earlier Environment
   sources to that map. Apply saved presentation after the Study is accepted.
   Progress counts accepted entries, not simply submitted requests.
4. Append success leaves the new Studies alongside the original Studies. Replace
   builds the complete new set first, then removes the original Studies in reverse
   order at finalization. Thus a calculation-stage failure does not prematurely
   erase the old set. Both modes retain the new styles and relationships.
5. Failure, cancellation or stale/disposed target removes this run's added Studies
   in reverse order and preserves the preceding chart Studies. Late progress and
   results cannot resume the cancelled run. Retry starts a fresh run.

An unexpected exception while removing old Studies at Replace finalization is
reported as failure and triggers cleanup of the new set. This path is not a
separate durable transaction or a guarantee that already removed runtime Studies
can be resurrected. Normal dependency-safe reverse removal is the supported path.

### Delete

Delete removes the selected Environment definition file after confirmation.
Live Studies already created from it remain. Embedded Environment definitions
inside saved Workspace Snapshots remain. Artifact and Recipe pools remain.
Deleting a definition is not cascade deletion of its sources or copies.

## 8. Workspace Snapshot creation and update

A Snapshot is explicit capture, not continuous autosave. Capture requires one
to sixteen ready charts and no conflicting busy state. Read placement (including
detached charts), active chart, mode/Pan Anchor, full dataset identity, viewport,
price scale, volume, pane sizes and Study definitions. Convert runtime IDs to
chart references and embedded Environment entry references.

The Snapshot stores MarketIds and embedded definitions, not candles or full Study
results. Embedded Environments are independent of the Environment pool. Create
allocates a new Snapshot identity; update keeps identity and creation time while
replacing captured content. In the GUI, Update selects an existing Snapshot with
its name read-only and description editable. The lower-level store's draft can
carry a name, so this UI constraint must not be confused with a schema immutability
rule. Update preserves the saved Notebook assignment. New assignment is an
explicit link-service operation, not inference from the currently open editor.

A metadata-only save updates the selected saved Snapshot but never assigns the live Snapshot ID or Notebook ID, even when that saved object was formerly current. A late completion cannot overwrite a newer live association. Explicit restore and explicit assignment retain their separate behavior.

## 9. Workspace Snapshot restore

### Review and preflight

Load an exact Snapshot, choose Replace or Append, and check the current target:
idle state, capacity, accepted datasets, embedded Environment compatibility and
the assigned Notebook's availability. The report has global and per-chart
blockers/warnings and a deterministic Append position plan. Load is enabled only
when compatible and the loaded model/report still match the selected Snapshot,
content hash/update time, actual radio mode and transient request generation.
A-B-A reselection invalidates the old request too. Both Load and final Load
Workspace confirmation recheck this identity; read-only recap without a selection
does not authorize restore. Cancel before Load changes no live workspace.

Append keeps each saved position if free; if occupied, assign the lowest free
position and reserve it before planning the next chart. Detached positions count
as occupied. Reject more than sixteen combined charts; never evict an existing
chart to make room.

### Before changing charts

If the target requires changing the open Notebook, resolve its dirty transition
first. Cancel or failed/invalid Save preserves the editor and existing workspace.
Keeping the same Notebook does not add a dirty prompt. Save completes explicitly,
then reruns compatibility preflight using current workspace/session/position and
editor identity. A stale target, changed workspace, invalidated preflight dialog
or newly dirty editor refuses the old continuation.

Keep the outgoing editor/buffer until restore succeeds so failure can preserve
it. Disable conflicting Notebook operations for pending/active restore. Manager
Refresh, including a queued signal, is deferred; it cannot use the Notebook task
slot reserved by this workflow. Newly created late Managers inherit busy state.

### Ordered reconstruction

1. Replace captures an in-memory rollback definition and previous live Snapshot/
   Notebook identities, then removes old charts. Append records the pre-existing
   active chart, mode and Pan Anchor and keeps those chart sessions.
2. Allocate each planned chart sequentially, load the current accepted dataset,
   await its resident slice, apply its embedded Environment, and restore viewport,
   manual/automatic scale, volume, panes, position and detached status.
3. Correlate every callback with the run and chart reference; do not continue a
   superseded run. Preflight does not waive loader/source checks during actual work.
4. When all charts are ready, apply the Snapshot's global mode, Pan Anchor and
   active chart. Both successful Replace and Append adopt that Snapshot's live
   identity and Notebook assignment. Append is therefore more than adding panels.
5. Retire stale secondary windows and pending New Chart opening intent. Retain the
   same Notebook editor if still assigned, otherwise close/replace it and load the
   target assigned Notebook (or close it if the Snapshot has no assignment).
6. Settle the run and refresh current command state. Successful restore has retired
   the Manager, so its deferred refresh is dropped, not allowed to delay the
   assigned Notebook opening.

The active restore/rollback dialog disables Cancel and rejects close/Escape until
terminal settlement. This is not a promise of a user-cancellable composite restore.
Underlying Core tasks still retain their own lifecycle. Environment application
has its separate cancellation/rollback behavior.

### Failure and recovery

| Failure point | Required result |
|---|---|
| Before teardown: dirty Cancel, invalid/failed Save, incompatible or stale preflight | Preserve live charts and editor; show refusal/failure; restore usable Manager commands |
| Append after one or more added charts | Remove only this run's added charts; restore previous active chart when still current, mode, Pan Anchor and live identities |
| Replace with a captured previous workspace | Remove failed run's additions; reconstruct captured previous workspace through normal dataset/Environment paths; reinstate previous live identities on successful rollback |
| Replace without previous charts | Remove the failed additions; report failure with no invented old workspace |
| Rollback itself fails | Report original failure and rollback failure explicitly; do not claim atomic recovery or that the original session objects survived |

Replace rollback reconstructs equivalent captured state with fresh sessions and
current accepted inputs; it does not resurrect deleted Qt objects or historical
dataset bytes. A completed explicit Notebook Save is not rolled back. The outgoing
editor buffer is preserved on restore failure, including a prior Discard choice
whose destructive transition never succeeded. A surviving current Manager
refreshes once after settlement. Closed/replaced Managers stay closed.

### Snapshot deletion

Delete removes that pool Snapshot only. It does not delete its datasets,
Artifacts, standalone Environments or assigned Notebook. If the deleted Snapshot
is the live current one, clear its live ID/assignment indicator; the open charts
continue as transient research state. Embedded Environment content disappears
with that Snapshot file, not with deletion of an unrelated pool Environment.

## 10. Notebook editing and annotations

Create opens one editor with a new dirty draft and pages for currently loaded
chart markets. Open/load reads an exact saved Notebook into that editor after
the existing transition guard. New/Open/Save As are separate intents. Pages are
keyed by complete MarketId, including timeframe, and may also be added from the
current chart. A Notebook can exist without any assigned Snapshot or open chart.

Notes, Potential Trades and Points of Interest have stable row IDs. Add/edit/
remove in the editor changes its draft and dirty state. Editing a trade's status
or outcome does not run a trading strategy. Row deletion remains an unsaved draft
change until Save. Save updates the existing ID; Save As creates a different
pool Notebook, requiring a valid unique name. It does not silently reassign every
Snapshot that referred to the old Notebook.

The editor supplies a last valid draft. Preview annotations are built from that
draft and projected only to charts with the exact page MarketId. An invalid
intermediate edit cannot publish a malformed Notebook. Potential Trades and
Points of Interest produce annotations; plain Notes do not become chart Studies
or plotted financial output. Visibility and pixel offsets come from Notebook
annotation settings. Closing the editor clears its chart annotation projections.

Go To from a timestamped row uses the active matching chart if available, otherwise
the first matching chart by workspace position. If no matching chart is open,
report that fact; do not open an unrelated market automatically. Navigation uses
the normal timestamp/refill path and is refused during Snapshot restore.

### Dirty transition table

This table applies to editor replacement/closure, Suite/main close, Clear after
confirmation, and restore when the Notebook must change.

| State/choice | Continuation | Saved state |
|---|---|---|
| Clean editor | Proceed when other admission allows | Unchanged |
| Dirty + Cancel | Refuse entire requested transition | Unchanged; dirty buffer retained |
| Dirty + Discard | Proceed without saving; restore retains buffer until success | Existing saved Notebook unchanged |
| Dirty + Save | Validate and submit exactly one save; retain continuation until success | Create/update through Notebook store |
| Invalid draft / submission failure / failed save | Clear pending continuation; keep editor with reason | No success assumed |
| Save already pending | Retain one compatible continuation; reject conflicting requests | Settle the original save honestly |
| Other Notebook operation or link mutation pending | Refuse conflicting transition | No parallel mutation path |

Dirty handling is not automatic saving. The earlier dirty-close and restore
corrections apply before any destructive chart/window teardown. Tracking closure
must reflect the accepted close, not merely a close request.

Notebook row insertion blocks table signals while every control and cell is initialized, then resumes normal validation. Blank required content stays invalid and preserves the last valid draft. Replaced page containers are removed and scheduled for deferred deletion; current-page signals remain connected.

Go uses `Signal(object, object)` to transport the existing validated nonnegative Python integer milliseconds without int32/int64 narrowing. Above-int64 regression values prove transport only, not representable calendar dates or valid market ranges. Receivers and persisted schemas are unchanged.

## 11. Notebook assignment, unassignment and deletion

Each Snapshot can refer to zero or one Notebook; the same Notebook can be referred
to by multiple Snapshots. The reference lives in the saved Snapshot, not in an
owning folder or a reciprocal field inside the Notebook.

Assign validates that both objects exist, then changes the Snapshot reference
under the link service's lock. Reassign changes that reference; it does not delete
the previous Notebook. Assigning the same current Notebook is idempotent. Unassign
requires the expected current Notebook ID; a stale/mismatched request fails.
Unassign preserves the Notebook and its contents. Current live assignment display
is synchronized after a successful mutation of the live Snapshot.

Notebook deletion is distinct from ordinary editor replacement. Manager confirms
deletion. If that Notebook is open and dirty, only explicit **Discard** permits
this deletion path; Save or Cancel stops the deletion attempt. It does not silently
Save and then delete. The editor is closed before the delete task is submitted.

The application submits one coordinated, fenced operation: load the Notebook,
find valid saved Snapshots referring to it, clear those references, then delete
the Notebook. If reference cleanup or deletion fails, attempt to restore the
references already cleared in reverse order. Report rollback failures as well as
the primary error. Restoring a reference can advance Snapshot update time/hash;
this is reference recovery, not a byte-for-byte transaction across all files.
Invalid/unreadable Snapshot summaries are not silently repaired by this scan.
Charts, Studies, OHLCV and Artifact pools are not deletion targets.

The Manager is a read model of pool summaries and assignments. Refresh changes
that view, not ownership. Stale Manager result delivery is ignored. During restore
its refresh is deferred; after failure only the surviving current Manager may
refresh. Closing Manager does not close or delete its saved Notebook pool.

## 12. Clear Research Suite

1. Check the existing busy conflict boundary: pending setup/Snapshot/Notebook/link
   work, active restore, tool catalogs, Artifact batches, tool-save runs,
   Environment application and busy chart work. A refused Clear does not bypass
   those operations or queue an automatic retry.
2. Ask explicit Clear confirmation. No changes nothing, including the dirty editor.
3. Resolve a dirty Notebook. Cancel preserves the whole workspace. Save completes
   before any teardown; failure retains the editor and charts.
4. On successful Save with Clear pending, invoke the existing Clear continuation
   **before** any Manager listing. A retired Manager needs no refresh. If an
   independent conflict now refuses Clear, the saved editor may already be closed,
   charts remain, and a surviving Manager refreshes. The guard remains intact and
   there is no automatic retry. The explicit save remains durable.
5. Accepted Clear closes editor and secondary windows, cancels pending selector
   opening intent, removes attached and detached charts, clears live Snapshot/
   Notebook assignment, switches Pan Anchor off and Scroll 4 on, and resets the
   Activity surface. The Suite itself stays open for new work.

Clear never deletes any pool object or rewrites saved assignments. Resetting a
live assignment indicator is not unassigning the saved Snapshot.

## 13. Ownership and survival matrix

| Operation | Removed/changed | Must survive |
|---|---|---|
| Close chart | Session, resident projection, transient Studies, local views | Saved Artifacts/Recipes and all Research pools |
| Remove Study | One dependency-safe transient result and presentation | Saved counterpart, source data and definitions elsewhere |
| Hide/style Study | Presentation only | Numerical values, lineage and durable objects |
| Delete Environment | One pool definition | Applied Studies, embedded Snapshot copies, Artifacts |
| Delete Snapshot | One pool capture; live ID reset if current | Notebook, source data, live charts, Artifact/Environment pools |
| Unassign Notebook | Snapshot reference | Notebook contents and all chart data |
| Delete Notebook | Notebook file and coordinated valid Snapshot references | Datasets, Studies, Artifacts, Snapshot chart definitions |
| Clear/close Suite | Live GUI/session context | All saved pools and accepted historical data |
| Update OHLCV elsewhere | Canonical source/validation/cache state through its owner | Existing immutable chart dataset and results until explicitly reopened |

## 14. End-to-end example and observable completion

Select accepted BTCUSDT 1m, open two charts, apply SMA to the first, and apply a
dependent eligible construct. The second chart remains unchanged. Save source
Studies before the dependent result when durable links are required. DMS can
discover those saved publications; no Database changes automatically.

Save the first chart's definitions as an Environment. Save both charts, their
positions and view settings as a Workspace Snapshot. Create a Notebook with a
BTCUSDT 1m page and observations, save it, and explicitly assign it to the Snapshot.
Clear removes the live charts/editor but none of these files. Restore the Snapshot:
current accepted data load, calculation definitions recalculate, Artifact-mode
entries demand exact current lineage, view state is restored and the assigned
Notebook opens. Deleting the standalone Environment still leaves this Snapshot's
embedded definitions usable. Unassigning the Notebook still leaves it in its pool.

Completion is the coherent final domain and view state, not just a successful
button callback. For example, restored charts with a valid assignment but no
assigned Notebook editor are an incomplete restore. Saved Notebook plus residual
charts after an otherwise admissible Save -> Clear is an incomplete Clear. The
verification matrix tests these composed outcomes as well as individual methods.
