# Task 1013 — OHLCV Maintenance Performance and Cancellation Hardening

## Objective

Measure large-dataset Maintenance behavior and change production code only where
measured evidence proves a current defect.

## Baseline findings

Synthetic canonical datasets established the following baseline in the audit
sandbox:

- discovery remained healthy at roughly 0.8 seconds for 1,000 datasets;
- validation used bounded memory, roughly 2 MiB of traced Python allocations;
- a 500,000-row validation read the complete CSV three times;
- median 500,000-row validation was roughly 1.24 seconds without tracing;
- cancelling the Core task did not cooperatively stop the worker thread, so a
  validation could continue after the GUI reported cancellation.

The measured defects were duplicate full-file hashing and non-cooperative
validation cancellation. Discovery did not justify production changes.

## Implemented

- canonical validation hashes `candles.csv` once instead of before and after the
  complete CSV scan;
- the Store publication gate still rechecks the exact expected hash and file
  fingerprint before changing durable validation evidence;
- large validation reports bounded row progress using the sidecar row count when
  available;
- canonical validation accepts a cooperative cancellation callback;
- SHA-256 capture and CSV scanning check cancellation at bounded intervals;
- Maintenance checks cancellation again before validation publication;
- the Maintenance application service owns per-validation cancellation events;
- GUI cancellation now sets the cooperative event before cancelling the Core
  task wrapper;
- cancelled validation cannot publish or rewrite sidecar evidence;
- a temporary-data performance tool measures validation throughput, memory,
  discovery, and cancellation latency.

## Measured result

On the same 500,000-row synthetic fixture in the audit sandbox:

- baseline median validation: approximately 1.24 seconds;
- Task 1013 median validation: approximately 1.10 seconds;
- improvement: approximately 11 percent;
- peak traced Python allocation: approximately 2 MiB;
- 500-dataset discovery: below 0.5 seconds;
- cooperative cancellation settlement: approximately 0.02 seconds.

These figures are evidence from one machine, not universal performance promises.
The handoff tool repeats the measurement in the user's active environment.

## Explicit non-goals

- no new streaming framework;
- no persisted-schema change;
- no validator-rule change;
- no Store write-path change;
- no provider or download behavior change;
- no Research admission change;
- no GUI layout change;
- no batch validation;
- no source correction;
- no optimisation of discovery because measurement did not justify it.

## Validation

- deterministic progress regression;
- direct cooperative-cancellation regression;
- full application-service cancellation regression;
- single-CSV-hash regression;
- file-change-during-validation regression;
- complete repository suite;
- temporary-data performance smoke in the user environment.
