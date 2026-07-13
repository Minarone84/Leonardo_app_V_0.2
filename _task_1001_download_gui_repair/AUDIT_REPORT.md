# Task 1001 Audit Report

## Task

- **Task ID:** 1001
- **Task name:** Historical Download GUI preflight and reset repair
- **Parent workplan:** WP-01 Market Access and Historical Ingestion
- **Implementation agent:** Rick-authorised direct patch
- **Decision entropy:** Low
- **Architecture status:** Frozen for task

## Audit

### Confirmed findings

1. The Task 1000 GUI shell respected the intended layering:
   - the window owned fields, checkboxes, presentation state, and signals;
   - the presenter coordinated GUI intent;
   - Connection owned provider capabilities and Bybit wire knowledge;
   - OHLCV services owned preflight, download, validation handoff, and persistence.
2. Bybit capability population was already local and network-free. `provider_names`,
   `supported_markets`, and `supported_timeframes` create an adapter and read its
   static capability methods without opening a provider session.
3. The manager auto-selected the first registered provider because the exchange
   combo contained no leading blank item.
4. The limit field opened with `0` instead of a blank user-input state.
5. The preflight window was shown only after provider/local planning completed.
   Full-history Bybit preflight may perform several API probes to discover the
   oldest available candle, so the UI could appear to ignore Start while work was
   actually running.
6. The presenter discarded the preflight task ID. Closing or dismissing the window
   therefore could not cancel the in-flight preflight or suppress stale callbacks.
7. Closing the Historical Download Manager did not reset user fields.
8. The old working Bybit adapter and the Light V2 adapter use the same relevant
   knowledge model: adapter-owned market/timeframe/interval maps, provider-owned
   page limits, server-time queries, oldest-candle probing, and rate-limit pacing.
   No GUI-owned Bybit data was required or restored.

### Affected authorities

- GUI local state: `HistoricalDownloadManagerWindow`
- GUI workflow coordination: `HistoricalDownloadPresenter`
- Provider capability truth: unchanged, Connection Area
- Preflight and download truth: unchanged, OHLCV Area
- Task lifecycle: unchanged, `TaskManager` / `CoreRunner`

### Risk

Low. No persisted schema, provider wire behavior, storage path, download
mathematics, Research Suite file, or Core lifecycle behavior changed.

## Update

### Files changed

- `src/leonardo/gui/windows/historical_download_manager_window.py`
- `src/leonardo/gui/windows/ohlcv_download_preflight_window.py`
- `src/leonardo/gui/presenters/historical_download_presenter.py`
- `tests/connection_test/test_provider_registry.py`
- `tests/gui_test/test_historical_download_wiring_static.py`
- Task 1001 evidence and merge-note documents

### Behavior changed

- Exchange, market, symbol, start, end, limit, and timeframe state now open blank.
- Bybit remains available but is no longer preselected.
- Closing the manager resets all local fields, selections, status text, and Start state.
- The preflight shell opens immediately after valid request collection.
- While planning runs, Start Download remains disabled and the window shows a
  preparing status plus a full-history probe notice when applicable.
- Provider/preflight failures remain visible in the preflight window.
- The presenter tracks the preflight task ID.
- Closing the preflight window cancels an active preflight and invalidates stale
  result/progress callbacks.
- Closing the manager cancels only active preflight work. It does not create GUI
  ownership of download task lifecycle.
- The confirmed-download path hides the reusable preflight shell rather than
  triggering its user-dismissal cancellation path.

### Preserved behavior

- Adapter-owned Bybit capabilities and interval translation
- Non-mutating preflight
- Full-history oldest-candle discovery
- Sequential timeframe execution
- Progress, cancellation, persistence, preliminary validation, and audit
- GUI shell separation from Connection and OHLCV implementation code
- All unused Task 1000 GUI widgets
- Research Suite source

## Validation

### Commands

```text
python -m compileall -q src tests tools
python -m pytest -q tests/connection_test tests/ohlcv_test \
  tests/gui_test/test_historical_download_wiring_static.py \
  tests/core_test/test_blocking_work_boundary.py
python -m pytest -q
git diff --check
```

### Results

```text
Focused: 21 passed
Full: 48 passed, 1 skipped
Compilation: PASS
Diff check: PASS
```

The skipped GUI runtime test requires PySide6, which is unavailable in the audit
container. Local visual smoke remains required.

## Original-Code Comparison

- Old Bybit capability ownership was preserved behaviorally.
- Old GUI/backend coupling and audit polling were not restored.
- No Research Suite implementation file changed.
- No unrelated refactoring or formatting churn was found.

## Remaining risks

- A real local Bybit smoke test is still required to distinguish provider/network
  failure from successful preflight on the user's workstation.
- Full-history range discovery may legitimately take several API probes.
- The developer launcher still requires the previously identified local-source
  import-path correction; it is outside Task 1001.
