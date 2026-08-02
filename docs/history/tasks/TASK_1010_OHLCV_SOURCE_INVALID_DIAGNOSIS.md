# Task 1010 — Explicit OHLCV `source_invalid` Repair Diagnosis

## Objective

Restore the Old Leonardo distinction between a failed repair mechanism and a provider-backed replacement that was successfully fetched but remains invalid at the reviewed validation anchor.

## Accepted behavior

A repair result is classified as `source_invalid` only when all of the following are true:

1. the provider returned one or more replacement rows for the reviewed range;
2. downloaded coverage includes a reviewed validation anchor;
3. canonical post-repair validation still reports an error at that same timestamp.

The result records:

- `source_invalid = True`;
- the exact `source_invalid_anchors`;
- the canonical validation issues;
- an explicit warning that no local correction was applied.

A post-repair defect outside the reviewed anchor remains `validation_failed`.

## Preserved authorities

- The provider supplies replacement candles.
- `OHLCVStore` owns persistence.
- `CanonicalOHLCVValidator` owns final quality truth.
- Maintenance owns repair diagnosis and orchestration.
- Research remains read-only and admits only canonical `ok` datasets.

## Explicit non-goals

- no local source correction;
- no `modified` validation status;
- no sidecar schema change;
- no Research admission change;
- no batch validation;
- no GUI redesign;
- no provider architecture change.

## Validation

The task adds regression coverage for:

- provider replacement remaining invalid at the reviewed anchor;
- exact `source_invalid_anchors` reporting;
- detailed canonical issue preservation;
- Research exclusion;
- unrelated post-repair errors remaining `validation_failed`;
- presenter status text stating that provider source remains invalid and no local correction was applied.
