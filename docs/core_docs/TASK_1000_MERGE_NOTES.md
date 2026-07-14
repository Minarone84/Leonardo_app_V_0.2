# Task 1000 Merge Notes

The user is developing Research Suite concurrently. Task 1000 intentionally
leaves the Research, Analysis, Data Manager and Trading Suite window sources
byte-identical to the Task 0048 baseline.

## Likely shared-file merge points

### `src/leonardo/core/app.py`

Task 1000 adds composition of:

```text
ProviderRegistry
ConnectionApplicationService
OHLCVStore
HistoricalDownloadService
HistoricalDownloadApplicationService
```

When merging, preserve any Research services added by the parallel branch and
retain both service families in `CoreContext`. Neither family should replace the
other.

### `src/leonardo/gui/composition.py`

Task 1000 adds only the Historical Download presenter construction and retention.
When merging, preserve parallel Research presenter/window wiring and keep the
Historical Download block in `_open_historical_download_manager`.

### `src/leonardo/core/__init__.py`

Task 1000 changes eager `LeonardoApp` imports to lazy exports to prevent package
initialization cycles after real Areas are composed. Preserve the lazy export
unless the merged package removes the cycle by another accepted design.

### `src/leonardo/data/market_id.py` and `src/leonardo/data/__init__.py`

Task 1000 adds canonical normalization and timeframe storage helpers. Research
code should import these shared policies rather than defining another market or
timeframe identity.

## Files that should merge without conflict

```text
src/leonardo/connection/**
src/leonardo/ohlcv/**
src/leonardo/gui/presenters/historical_download_presenter.py
tests/connection_test/**
tests/ohlcv_test/**
tests/core_test/test_blocking_work_boundary.py
```

## Research non-interference hashes

Task 0048 and Task 1000 contain identical bytes for:

```text
research_suite_window.py
analysis_suite_window.py
data_manager_suite_window.py
trading_suite_window.py
```

Exact SHA-256 evidence is stored in the Task 1000 validation directory.

## Merge order

```text
1. Merge Area-local Connection and OHLCV packages.
2. Merge shared MarketId policy.
3. Merge CoreRunner blocking boundary.
4. Reconcile LeonardoApp service composition.
5. Reconcile GUI composition.
6. Merge the three Download window changes and presenter.
7. Run both Research and Task 1000 test suites.
8. Perform GUI smoke tests for Research and Historical Download in one process.
```

Do not resolve conflicts by dropping either service family or by constructing
hidden services inside windows.
