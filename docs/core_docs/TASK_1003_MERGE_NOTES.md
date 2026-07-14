# Task 1003 Merge Notes

Task 1003 is OHLCV logic-only. It does not change Research or GUI production
files.

## Shared-file merge point

### `src/leonardo/core/app.py`

Task 1003 adds composition of:

```text
CanonicalOHLCVValidator
OHLCVMaintenanceService
OHLCVMaintenanceApplicationService
```

Preserve the existing Historical Download and Research service composition. The
Maintenance service uses the same `OHLCVStore` as Historical Download and the
same `CoreRunner` as the other long-running workflows.

## Area-local files

The remaining production changes are limited to:

```text
src/leonardo/ohlcv/**
```

Research production code must remain unchanged. Acceptance is proved through
the existing `AcceptedDatasetCatalog` behaviour and Research tests.

## Integration order

```text
1. Preserve all accepted Research composition already present on main.
2. Add the Task 1003 OHLCV Area files.
3. Reconcile only the additive CoreContext and LeonardoApp Maintenance wiring.
4. Run focused OHLCV and Research admission tests.
5. Run the complete suite.
```

The later Maintenance GUI task may consume
`OHLCVMaintenanceApplicationService`; it must not duplicate validation or
persistence logic in Qt code.
