# Leonardo Light V2 Application GUI Smoke

This procedure supersedes the old reset-baseline visual smoke. It checks the
current application-level GUI lifecycle without duplicating the detailed
Research acceptance procedure.

1. Activate the `py312_Leo` environment and launch the application with
   `python tools\dev_launch_gui.py`.
2. Confirm the Main Window opens without a traceback and that application
   navigation remains responsive.
3. Open Runtime Manager. Invoke the command again and confirm the existing
   single-instance window is reused or focused.
4. Open Historical Download Manager. Invoke the command again and confirm the
   existing single-instance window is reused or focused.
5. Open OHLCV Maintenance. Invoke the command again and confirm the existing
   single-instance window is reused or focused.
6. Open Research Suite. Invoke the command again and confirm the existing
   single-instance window is reused or focused.
7. Refresh Runtime Manager and confirm the tracked Main Window, Runtime
   Manager, Historical Download Manager, OHLCV Maintenance, and Research Suite
   windows appear with their current lifecycle state.
8. Confirm the bundled Leonardo theme is applied coherently across the open
   windows and local control states.
9. Confirm unavailable suites remain honestly disabled or shell-only. Do not
   extend Task 1064 Data Manager acceptance into the remaining Tasks 1065-1067.
10. Close the Main Window and confirm tracked windows close and the shared Core
    runtime settles without a shutdown traceback or hanging process.

For Research-specific workflow and acceptance details, use the
[Research Suite manual](../research_docs/RESEARCH_SUITE.md).

## Data Manager post-1064 native-smoke baseline

**Task 1064 final combined native smoke: PASSED**

Treat this accepted behavior as the Data Manager regression baseline:

1. Open Data Manager Suite twice. Confirm one tracked Suite is reused, the first
   creation opens maximized, and a reused Suite preserves its current maximized
   or restored state and geometry.
2. On first creation, confirm `Loading Data Manager` uses the Suite Operation
   surface, foreground reconciliation succeeds, the product catalog scan follows,
   valid catalogs are applied before warm-up completes, and failed warm-up remains
   visible and retryable.
3. After warm-up, confirm background reconciliation is autonomous,
   non-blocking, and does not claim foreground Operation ownership or create a
   second progress authority.
4. Open Select Dataset repeatedly and confirm the tracked selector is reused.
   Verify cascading filters, both searches, Show All, rejected-entry gating, and
   Active Dataset synchronization.
5. Sort the full Select Dataset table by text, Rows, and UTC in both directions.
   Confirm filtering, search, refresh, and current-market synchronization retain
   the sort and selected `MarketId`. Confirm the one-row Active Dataset table is
   not sortable.
6. Inspect all seven central Catalog families. Sort text, numeric, and UTC
   columns in both directions, switch families, and confirm per-family state,
   selected domain identity, Inspector content, and history association remain
   correct. Inspector, Revision History, and Operation details remain unsorted.
7. Confirm the responsive Suite layout uses `3:1` Workspace/Operation, `7:3`
   upper/bottom, and `1:1` Inspector/Revision History proportions, with the
   bottom strip spanning the full width through restored, resized, and maximized
   states.
8. From one accepted OHLCV dataset, run `Create Artifact...`, configure a
   canonical Financial Tool, and confirm `Calculate Artifact` creates or reuses
   the global Recipe and durably publishes or reuses the market/fingerprint-
   specific managed Artifact without a Research Apply step or automatic
   Collection creation.
9. Confirm managed Artifact publication advances immutable/current state and
   refreshes the relevant catalogs while preserving global Recipe reuse
   semantics.
10. Open `Batch Constructs...` and verify the saved-Artifact source tree and the
    Selected Signals, All Indicators, All Oscillators, and All Constructs scopes.
11. Confirm raw current-dataset sources offer only `Open`, `High`, `Low`, and
    `Close`. Raw Volume must be absent and rejected; a saved Volume Artifact must
    remain available through the normal saved-Artifact source route.
12. Run Batch Preview and confirm `Source(s)`, `Construct`, `Parameters`,
    `Inputs`, and `Result`, including `New` and `Reuse Current`, agree with the
    reviewed plan.
13. Execute the reviewed Batch plan. Confirm the Suite Operation surface is the
    only live progress, task-state, cancellation, and operation authority.
14. Confirm the Batch terminal report includes reviewed-plan-derived branch,
    `New`, and `Reuse Current` counts, closes independently, leaves the Batch
    window open, and invalidates Preview so another Execute requires a new
    Preview.
15. Observe Data Manager work in Runtime Manager, request cancellation only while
    allowed, and confirm terminal state remains honest.
16. Close Data Manager with bounded child windows open and confirm all children
    close and Leonardo shuts down without a surviving worker, callback traceback,
    or native failure.

Future Data Manager functional acceptance continues through Tasks 1065, 1066,
and 1067. This baseline does not claim that the complete Data Manager workplan
is finished and defines no speculative smoke steps for those tasks.
