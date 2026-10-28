# Core architecture and Leonardo integration

**Targeted revision: 2026-10-28 (R07).** Reconciles accepted R01-R06 and current source. Earlier edition dates and validation counts below remain historical; R08 integrated and R09 native acceptance are separate, not performed by this documentation revision.

**Verified:** 2026-10-09, accepted Core patch V2 candidate. Companion to [Core Runtime](LIGHT_V2_RUNTIME.md), [lifecycles](CORE_LIFECYCLES.md), [contracts](CORE_DATA_CONTRACTS.md) and the [visual map](Leonardo_V2_Core_Complete_Map.pdf).

## 1. Architecture and dependency direction

Leonardo is a layered desktop modular monolith with vertical Areas, explicit manual composition and a shared asynchronous runtime. Core's infrastructure managers are domain-neutral. `core/app.py` is the deliberate application composition point: it imports current Areas and assembles their concrete dependencies. Its location in the Core package does not mean TaskManager, registries or the runner own financial rules.

```text
Application entry / LeonardoGuiRunner
  -> LeonardoApp [constructs shared graph]
       -> Core managers / audit / configuration
       -> Area services -> canonical stores, policies, provider adapters
       -> CoreContext [references, no independent state authority]
  -> GuiCompositionRoot -> windows / presenters
       -> Area application services -> CoreRunner
       -> RuntimeManagerBackend -> authoritative snapshots
```

CoreRunner depends on TaskManager and minimal async helpers, not Qt or Areas. TaskManager and ProcessManager use audit/error routing, not financial services. RuntimeManagerBackend knows managers and snapshot shapes, not widgets. GUI presenters translate user intent and queue results; they do not duplicate task state, calculation truth or persistence authority.

## 2. Authority map

| Mutable state / truth | Authoritative writer | Other participation |
|---|---|---|
| App status and cleanup order | LeonardoApp under its RLock | GUI runner initiates; Runtime Manager reads |
| Event-loop/worker lifecycle and admission | CoreRunner under its lifecycle lock | Areas submit; TaskManager owns each task |
| Task identity/status/progress/history | TaskManager under its RLock, tasks on Core loop | Reporter updates; callbacks project; history is disposable |
| Process IDs, handles and terminal state | ProcessManager under its RLock | Launcher creates OS handle outside lock; owner polls |
| Connection/channel summaries | ConnectionRegistry under its RLock | Connection Area reports provider observations |
| Logical window records | WindowRegistry under its RLock | GuiWindowTracker adapts Qt events/accepted closure |
| Actions and recent triggers | ActionRegistry under its RLock | GUI observers record; handlers execute through invoke when used |
| Historical audit evidence | AuditLog and configured sinks | Runtime owners emit; ErrorRouter formats errors |
| OHLCV, financial results, saved object relationships | Respective Area/policy/store | Core executes the callable, not its business meaning |

Private shutdown coordination and in-flight process IDs stay inside their existing owners. Runtime snapshots, presenter busy state, task IDs held by a dialog and cached read models are projections/coordination, not competing canonical managers.

## 3. Construction graph in LeonardoApp

Construction is explicit and eager for services; this does not start a worker thread, provider operation or GUI. The following dependency groups preserve source order and sharing:

1. Resolve AppConfig; build operational logger, AuditLog and ErrorRouter.
2. Build TaskManager with that audit/router/logger and CoreRunner with that manager. Build ProcessManager, ConnectionRegistry and WindowRegistry.
3. Build the default provider registry and ConnectionApplicationService using the shared connection summaries.
4. Create one OHLCVStore and shared OHLCVDatasetOperationLocks. HistoricalDownloadService uses connection, store, audit and those locks; its application service uses CoreRunner.
5. Create CanonicalOHLCVValidator, OHLCVMaintenanceService, AcceptedDatasetCatalog, HistoricalDatasetLoader and ResidentSliceService. Maintenance application service shares Core, download domain and market locks; successful mutation invalidates the shared loader cache. Research dataset application service shares loader/catalog/resident slices.
6. Create ArtifactService, StudyEnvironmentStore, PortableRecipeStore/GraphPlanner and DataManagerCreationStore. DataManagerService receives the existing catalog, loader, Artifact/Environment/Recipe authorities and creation store; its application wrapper receives the same CoreRunner. Immediately afterward create `AnalysisService(self.data_manager_creation_store)` and `AnalysisApplicationService(self.core_runner, self.analysis_domain)`.
7. Create ResearchStudyService from shared Artifact/Recipe services and StudySetupService from shared Artifact/Environment store; wrap each with CoreRunner.
8. Create WorkspaceSnapshotStore and ResearchNotebookStore, NotebookService, then one WorkspaceNotebookLinkService spanning those stores. WorkspaceSnapshotService receives catalog/loader/StudySetup/link authority; its application service and Notebook application service reuse the same link service and CoreRunner.
9. Build ActionRegistry; initialize app status/lock; build RuntimeManagerBackend with a status provider and all shared managers. Freeze the CoreContext reference bundle.

CoreContext exposure is selective: it has 21 fields, including ten runtime/logger/config references, the runtime backend and Area application services (the exact field table is in contracts). Stores and domain services are not all directly exposed to GUI. Do not infer an extra factory or service-locator framework from this bundle.

## 4. Component catalogue

| Source under `src/leonardo/` | Responsibility / key collaborators |
|---|---|
| `core/config.py` | Frozen path/config models and side-effect-free default path resolution |
| `core/app.py` | Concrete composition, CoreContext and application lifecycle; Area imports are intentional here |
| `core/async_runtime.py` | Task-name normalization, coroutine recognition/closure and UTC helper |
| `core/core_runner.py` | Thread/loop/default executor, reporter, submission and terminal delivery |
| `core/task_manager.py` | Async task registration, snapshots, progress, cancellation, terminal audit and retention |
| `core/process_manager.py` | Child-handle admission, launch, poll, terminate/kill and shutdown |
| `core/connection_registry.py` | Coarse connections and channel counters; no real socket ownership |
| `core/window_registry.py` | Logical window identity/status/timestamps; no Qt imports |
| `core/action_registry.py` | ActionDefinition, ActionTrigger, registration and invocation evidence |
| `core/audit_log.py` | Memory/JSONL/composite sinks, failure records, forwarding AuditLog |
| `core/error_router.py` | Exception-to-AuditEventV1 translation |
| `core/runtime_manager.py` | Sequential aggregation of manager snapshots into RuntimeSnapshot |
| `audit/event_v1.py` | Durable event fields, normalization and dict round-trip |
| `gui/runner.py` | Startup/event-loop/finalization orchestration and exception precedence |
| `gui/composition.py` | Shared GUI/service wiring, window creation/reuse and tracker attachment |
| `gui/window_tracking.py` | Show/focus/ordinary-close events and explicit accepted-close recording |
| `gui/action_observer.py` | Registers/records observable GUI action IDs without becoming a business authority |
| `gui/windows/runtime_manager_window.py` | Six-tab snapshot presentation and manual refresh |

`core/__init__.py` is the export surface, not another runtime. All concrete method signatures, protocol methods, properties and model fields from the 14 Core/audit source files are inventoried in contracts.

## 5. Thread and callback boundaries

| Activity | Thread / scheduling | Required discipline |
|---|---|---|
| QWidget creation, mutation, focus, dialogs | Qt GUI thread | Presenter queues callback invocation here |
| Coroutine job and terminal-result awaiter | LeonardoCore thread / its asyncio loop | Do not block with synchronous I/O or runner methods waiting on this loop |
| Synchronous blocking job | Shared default executor | Use reporter; cooperate with Area cancellation; no widget mutation |
| `submit_*`, `cancel`, `shutdown` calls | External caller synchronously waits for loop work/join | Submission registration wait is five seconds; keep financial work inside job |
| Default inline progress callback | Job's execution thread | Not safe for Qt widget mutation |
| Default inline terminal callback | Core loop | A queued dispatcher is required for GUI delivery |
| Process launcher/poll/terminate | Calling thread, outside the record lock for external handle methods | No automatic Core thread offload in ProcessManager itself |

Core locks protect individual owners, not a transaction across the entire app. RuntimeManagerBackend reads owners one after another; two rows can reflect slightly different instants. Dictionary payloads in frozen snapshots are copied at their defined boundaries but are not deeply immutable.

Production queued dispatch uses QObject signals connected with `Qt.ConnectionType.QueuedConnection`. Active Research lifecycle callbacks also check disposal and object validity before emission/invocation. DMS presenters fence by operation/task identity and lifetime. Core supplies task IDs and results; it does not decide whether a formerly selected chart still wants a result. No general generation-token or stale-result subsystem is hidden inside CoreRunner.

ResearchDatasetApplicationService removes terminal cancellation-map entries on Core delivery before queuing outward callbacks. Its finished event prevents reinsertion when completion precedes submission return. Result/progress dispatch occurs outside its RLock, once through the existing dispatcher; a retired GUI may drop delivery without retaining terminal service entries. Actual task IDs and active cancellation still belong to Core and the existing service.

## 6. Area integration contracts

An Area application service accepts user/domain inputs, validates them through its authorities, creates operation/correlation metadata and submits a callable or coroutine. It provides progress/result callbacks and dispatcher where needed. Its domain layer decides valid outcomes and publication. Its store alone writes the persisted format. The presenter renders that result only if it remains relevant to its current selection/lifetime.

Research's five application services share one runner: dataset, study, StudySetup, WorkspaceSnapshot and Notebook. DMS uses that same runner for catalogs, explicit creation and update, plus reconciliation. Download and Maintenance share the canonical OHLCV lock/cache relationships from composition. An empty Runtime Manager Processes tab is therefore normal for these in-process workflows.

The DMS cancellation gate is an Area-owned safeguard, not a second task manager: it mediates accepted cancellation versus an irreversible publication boundary, while Core still records task status. Both `LeonardoApp.stop_core_runtime()` and `shutdown()` call DMS `cancel_all_pending()`, Analysis `cancel_all_pending()`, then Core shutdown, in that order. Core-only stop does not perform whole-app process, registry and audit cleanup. Research service/presenter disposal closes admission at the relevant GUI service and fences callbacks; application Core remains shared until whole-app shutdown. Detailed object deletion, assignment survival and source compatibility remain in their existing manuals.

ConnectionRegistry describes status but does not authenticate, retry requests, subscribe, reconnect or close a real provider session. The app's `shutdown_tracking()` is consequently not a universal provider teardown contract. A future Area with a persistent resource requires an explicitly approved integration lifecycle; documentation does not introduce one.

Analysis shares the existing creation store and CoreRunner. GUI composition injects `CoreContext.analysis_service` into AnalysisSuitePresenter; `_retire_analysis_suite` checks both retained window and presenter identity before disposal and reference retirement. Closing that Suite retires its session, not the shared runtime.

## 7. Persistence and identity boundaries

RuntimePaths derive eight locations from one resolved root; config itself creates no directory. Area stores consume their own paths. In Core, only the optional JSONL sink writes durable audit records. Task/process/window/connection/action histories are per-instance in-memory state with no automatic restore from disk. Core does not delete saved objects on task eviction, window closure or shutdown.

Task IDs are generated runtime identities; process IDs can be caller-supplied; connection/channel/window/action IDs are supplied by their integration owners. A display title or task name is not the universal identity. Distinct editor modes must retain distinct logical window IDs. Reopening a closed record is not recreating a saved Research object.

## 8. Reconstruction order and verification

1. Implement AuditEventV1 normalization/serialization, then configuration, sinks and ErrorRouter; test optional durable output in temporary paths.
2. Implement TaskManager task creation/wait/progress/cancel/audit and bounded eligible history on a running asyncio loop.
3. Implement CoreRunner around that manager with one loop thread and one executor; verify job placement, callback thread boundaries, cancellation and both retry timings.
4. Implement ProcessManager identity reservation, launcher port, polling/terminal audit and termination escalation; use generated/fake handles before real child controls.
5. Implement connections/channels, windows and actions as independent canonical registries, retaining exact validation and ordering behaviour.
6. Implement RuntimeManagerBackend directly over those owners, including process polling and selective action projection.
7. Compose LeonardoApp in the dependency order above with existing Area/store authorities; expose its CoreContext and implement ordered application lifecycle.
8. Attach GUI runner/composition, queued callback dispatch, action observation, accepted-close tracking and the six-tab Runtime Manager.
9. Validate Core/schema tests, selected GUI integration and native generated-data close/reopen behaviour. Use the [contracts acceptance matrix](CORE_DATA_CONTRACTS.md#8-verification-matrix).

This order explains existing architecture. It does not authorize replacement infrastructure, generic plugin lifecycles, alternative storage or broader concurrent-start behaviour. The original July map's growth recommendations remain historical proposals.
