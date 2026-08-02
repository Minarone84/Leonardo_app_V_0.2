# Task 0062: Accepted Dataset Catalog

## Task identity

```text
Task ID: 0062
Task name: Accepted Dataset Catalog
Parent workplan: Leonardo Light V2 Research Suite Rebuild
Execution owner: Rick
Architecture status: Frozen for task
Decision entropy: Low
```

## Objective

Provide the Research Area with a read-only catalog of OHLCV datasets whose
current CSV bytes are supported by accepted `OHLCVSidecarV1` evidence.

## Canonical authorities

| Truth | Authority |
|---|---|
| Market identity | `MarketId` and its canonicalization policy |
| OHLCV physical paths and writes | `OHLCVStore` |
| Durable dataset evidence | `OHLCVSidecarV1` |
| Canonical validation state | OHLCV validation/maintenance authority |
| Research availability projection | `AcceptedDatasetCatalog` |

The catalog is a disposable read projection. It never changes validation,
persistence, sidecars or CSV files.

## Admission policy

A dataset is visible to Research only when:

```text
storage path is canonical
candles.csv exists
candles.meta.json exists and parses as OHLCVSidecarV1
sidecar MarketId matches the storage path
persistence_status is committed or repaired
validation_status is ok
row_count is greater than zero
current candles.csv SHA-256 equals sidecar file_sha256
candles.csv remains unchanged during verification
```

Downloaded datasets with `validation_status="unknown"` remain blocked. Research
does not promote them or substitute preliminary download checks for canonical
OHLCV acceptance.

## Included scope

- deterministic storage discovery;
- immutable accepted dataset summaries;
- structured rejection codes and reasons;
- current CSV SHA-256 verification;
- canonical month-timeframe storage handling;
- read-only behavior tests.

## Excluded scope

- candle parsing;
- full dataset loading;
- resident slicing;
- Qt GUI changes;
- chart rendering;
- OHLCV validation or repair;
- persistence mutation;
- provider and download behavior.

## Old-code comparison

Preserved behavior:

- only accepted and current OHLCV datasets are loadable;
- missing, invalid or stale metadata blocks Research;
- month timeframe storage maps back to canonical `1M`-style identities;
- rejection evidence is explicit.

Rejected architecture:

- old `DatasetId` identity;
- old metadata contracts and registries;
- GUI-owned catalog traversal;
- automatic acceptance of download output.
