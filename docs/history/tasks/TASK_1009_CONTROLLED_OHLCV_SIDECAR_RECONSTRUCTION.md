# Task 1009 — Controlled OHLCV Sidecar Reconstruction and Orphan Handling

**Task ID:** `1009`
**Status:** Implemented and validated
**Parent area:** OHLCV Maintenance
**Starting baseline:** `f634464f938e349b0f1ee86b7c4469408d578455`

## Objective

Restore missing or defective `OHLCVSidecarV1` evidence without changing OHLCV candle bytes, inventing provider provenance, promoting partial persistence, or bypassing canonical validation.

## Canonical authorities

- `MarketId` owns canonical dataset identity.
- `OHLCVStore` owns the only sidecar write path.
- `CanonicalOHLCVValidator` owns final OHLCV quality truth.
- `OHLCVMaintenanceService` owns evidence classification and reconstruction planning.
- `OHLCVMaintenanceApplicationService` owns the locked reconstruction workflow and mandatory post-reconstruction validation.
- Research remains read-only and admits only canonically accepted datasets.

## Implemented workflow

```text
select canonical dataset
→ inspect CSV and sidecar evidence
→ classify evidence state
→ build a read-only reconstruction plan
→ show exact paths and proposed sidecar state
→ require explicit confirmation
→ acquire the shared per-dataset OHLCV operation lock
→ reject stale CSV or sidecar evidence
→ write SidecarV1 through OHLCVStore
→ source=maintenance_reconstruction
→ persistence_status=committed
→ validation_status=unknown
→ run canonical validation immediately
→ invalidate any resident Research cache entry
→ refresh Maintenance presentation
```

## Recoverable states

Reconstruction is allowed only when the CSV is stable, canonical, non-empty, and structurally parseable.

Supported sidecar states:

- missing sidecar;
- invalid or unsupported sidecar with stable file evidence;
- MarketId mismatch;
- stale CSV SHA-256;
- stale file-size or modification-time evidence;
- row-count mismatch;
- first-timestamp mismatch;
- last-timestamp mismatch.

CSV quality findings such as gaps, invalid OHLC envelopes, negative volume, duplicates, or ordering defects do not become accepted through reconstruction. They remain visible to canonical validation and may be handled by the existing explicit repair workflow where supported.

## Inspect-only states

The following states are deliberately not reconstructed:

- sidecar-only orphan with no `candles.csv`;
- partial persistence;
- unreadable sidecar that cannot be fingerprinted safely;
- sidecar or CSV that changes during planning;
- missing, empty, malformed, noncanonical, or structurally unparseable CSV;
- CSV whose first timestamp is later than its last timestamp and therefore cannot be represented safely by SidecarV1;
- noncanonical storage paths.

Noncanonical and orphan entries are reported. They are not moved, renamed, corrected, or deleted automatically.

## Persisted evidence

A reconstructed sidecar:

```text
source = maintenance_reconstruction
persistence_status = committed
validation_status = unknown
```

Its lineage records:

- reconstruction timestamp;
- reconstruction reason;
- whether an existing sidecar was replaced;
- the replaced sidecar SHA-256 when available;
- current CSV size and modification-time evidence.

No prior provider identity is copied from defective evidence. Canonical validation then publishes `ok`, `warning`, or `error` for the unchanged CSV.

## Concurrency and cancellation

Reconstruction uses the same per-`MarketId` operation lock as download, repair, and deletion.

A task may be cancelled while waiting or planning. Once confirmed reconstruction starts, the mutation and mandatory post-validation finish honestly even if a cancellation request arrives. The task must not report cancellation after the sidecar has already changed.

## GUI behavior

The Maintenance window now shows an `Evidence State` column and a `Rebuild Sidecar` action.

The confirmation dialog displays:

- canonical `MarketId`;
- classified evidence state;
- exact CSV path;
- exact sidecar path;
- whether the operation creates or replaces the sidecar;
- proposed `committed/unknown` state;
- explicit notice that candle values are unchanged.

## Explicit non-goals

Task 1009 does not:

- change CSV candle values;
- move or rename datasets;
- delete orphan files;
- promote partial persistence;
- preserve or invent provider provenance;
- mark reconstructed evidence directly as accepted;
- change `OHLCVSidecarV1` schema version;
- change Research admission rules;
- add batch operations;
- implement local source correction.

## Validation

Automated coverage includes:

- missing-sidecar reconstruction;
- invalid-sidecar replacement;
- stale-sidecar replacement;
- stale-plan rejection;
- partial-persistence refusal;
- sidecar-only orphan classification;
- malformed-CSV refusal;
- noncanonical-path reporting;
- mandatory canonical post-validation;
- Research-cache invalidation;
- cancellation honesty after mutation begins;
- presenter wiring and explicit confirmation.

A temporary-data GUI smoke launcher is provided at:

```text
tools/dev_launch_ohlcv_sidecar_reconstruction.py
```

## Next step

After Task 1009 closes, audit the completed Light V2 OHLCV Maintenance behavior against Old Leonardo. Classify old behavior as preserve, improve, reject, or still missing before scheduling additional Maintenance implementation.
