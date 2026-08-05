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
   treat Data Manager as accepted through this smoke.
10. Close the Main Window and confirm tracked windows close and the shared Core
    runtime settles without a shutdown traceback or hanging process.

For Research-specific workflow and acceptance details, use the
[Research Suite manual](../research_docs/RESEARCH_SUITE.md).

## Data Manager Final Native Smoke

**Status: PENDING FINAL NATIVE ACCEPTANCE**

1. Launch the real application and open Data Manager Suite twice. Confirm one
   tracked window is reused and focused.
2. Confirm the tabs are Catalogs, Create Database, and Update & Reconcile.
3. Inspect all eight catalog families. Confirm rejected or invalid rows remain
   visible with textual reasons and revision histories are inspectable.
4. Select accepted OHLCV and confirm Research handoff focuses the same canonical
   `MarketId`.
5. Create a Seed with explicit OHLCV columns and range. Inspect and validate it.
6. Inspect a Study Environment, choose explicit roots, plan Recipe derivation,
   persist Recipes, or select multiple existing portable Recipe roots, and
   create or update a Recipe Collection.
7. Plan and execute base Artifacts. Add one explicit compatible batch branch,
   review its plan, and execute it.
8. Create or revise an Artifact Collection. Edit selected outputs, unique
   Database column names, and complete presentation order; confirm required
   supports remain locked and lineage, blockers, and Database readiness are
   visible.
9. Review and explicitly confirm the first immutable Database revision. Confirm
   its terminal report survives reconciliation and catalog refresh.
10. Extend accepted OHLCV, run manual reconciliation, inspect `APPEND_ONLY`,
    plan and execute Artifact updates, validate the exact new Collection
    revision report, then plan and execute Database append. Confirm only Append
    is enabled for the matching `APPEND` plan and inspect the Commit Revision
    report.
11. With controlled historical source mutation evidence, confirm reconciliation
    reports `HISTORICAL_MUTATION`, append is refused, and rebuild remains a
    separate explicitly confirmed action that preserves prior revisions.
12. Change the selected Collection or Database after planning and confirm the
    stale execution action disables and submits nothing. Restart Leonardo and
    select old and current Recipe Collection, managed Artifact, Artifact
    Collection, and Database history rows through the Catalog inspector.
13. Observe Data Manager tasks in Runtime Manager, request cancellation during
    cancellable work, and confirm the terminal state is honest.
14. Close Data Manager and confirm its timer stops. Close Leonardo and confirm
    shared Core shutdown completes without a surviving worker or traceback.
