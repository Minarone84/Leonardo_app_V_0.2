# Task 1005 — Explicit OHLCV Repair Workflow

## Objective

Add a reviewed, provider-backed repair workflow to OHLCV Maintenance without
creating a second validation or persistence authority.

## Accepted workflow

```text
canonical validation findings
→ read-only repair plan
→ explicit GUI confirmation
→ stale-plan check under the downloader dataset lock
→ provider redownload of reviewed ranges
→ store-owned repaired persistence/provenance
→ canonical post-repair validation
→ Research admission only when validation_status == "ok"
```

## Canonical authorities

- `CanonicalOHLCVValidator` owns final validity.
- `HistoricalDownloadService` owns provider-backed OHLCV download execution and
  the per-dataset async lock.
- `OHLCVStore` owns CSV and sidecar persistence, including the transition to
  `persistence_status="repaired"`.
- `OHLCVMaintenanceService` owns repair planning and outcome classification.
- The Maintenance presenter/window collect intent, show plans and findings, and
  request explicit confirmation. They contain no validation, provider, or
  persistence logic.

## Supported repair findings

Task 1005 derives provider-redownload ranges only for timestamp-addressable,
parseable data findings:

- missing timeframe intervals;
- duplicate timestamps;
- out-of-order timestamps;
- invalid OHLC envelopes;
- negative volume;
- non-finite values with a valid timestamp anchor.

Malformed headers, missing columns, row-width failures, unparseable timestamps,
unparseable numeric fields, missing evidence, and unsupported structural defects
remain non-actionable. Task 1005 does not delete rows, fabricate values, rebuild
metadata, or apply local source correction.

## Safety

- Planning is read-only.
- Plans contain exact CSV and sidecar fingerprints.
- Execution refuses non-actionable or stale plans.
- The stale-plan check runs after acquiring the same per-dataset lock used by
  ordinary downloads, and that lock remains held across all planned ranges.
- Partial failure or cancellation cannot publish final acceptance.
- Repair provenance is appended to sidecar lineage.
- `mark_repaired` resets validation to `unknown` before canonical post-repair
  validation.
- Research remains read-only and admits only final `ok` evidence.

## Explicit exclusions

- automatic repair;
- local candle source correction;
- metadata reconstruction;
- deletion;
- Research production changes;
- new persisted-schema versions;
- Contract Registry, Object Map, CoreBridge, or GUI-owned domain logic.
