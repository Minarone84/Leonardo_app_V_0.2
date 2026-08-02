# Task 1012 — Real-Provider Download and Repair Hardening

## Objective

Harden the real Bybit historical OHLCV path so provider failures are classified once, retried only when justified, cancelled honestly, and never multiplied across the provider adapter and downloader layers.

## Accepted behavior

### Provider authority

The Bybit adapter owns wire-level interpretation:

- HTTP status handling;
- Bybit `retCode` handling;
- rate-limit timing and bounded retry;
- malformed response detection;
- transport-failure classification;
- permanent versus retryable failure classification.

The adapter exposes `HistoricalProviderRequestError`, an owner-local typed exception carrying:

- provider;
- operation;
- retryable state;
- whether provider retries are already exhausted;
- optional HTTP status;
- optional provider code.

### Retry policy

- Permanent Bybit API errors, including invalid symbol errors, fail immediately.
- HTTP 429 and Bybit `retCode=10006` remain bounded inside the Bybit adapter.
- Transport errors and retryable HTTP errors remain bounded inside the adapter.
- Once the adapter exhausts its retry policy, the downloader must not start another retry loop.
- A retryable failure from another provider that has not exhausted its own policy may still use the downloader's bounded page retry.
- Cancellation propagates immediately through request pacing and retry backoff.

### Persistence safety

A provider failure before a successful replacement page must not mutate:

- `candles.csv`;
- `candles.meta.json`;
- validation truth;
- Research admission.

The existing Store, validator, shared dataset lock, repair plan, and post-repair validation remain authoritative.

## Real-provider smoke

`tools/dev_run_bybit_ohlcv_hardening.py` uses public Bybit REST only and a temporary directory. It performs:

1. server-time retrieval;
2. a three-candle real download;
3. canonical Maintenance validation;
4. deliberate removal of one temporary candle;
5. provider-backed gap repair;
6. canonical post-repair acceptance;
7. intentionally invalid-symbol classification as permanent and non-retryable.

The tool:

- reads no credentials;
- touches no configured Leonardo dataset;
- deletes its temporary directory on exit.

## Explicit non-goals

- no provider registry redesign;
- no new formal contract family;
- no retry configuration GUI;
- no Download Manager layout change;
- no Maintenance layout change;
- no source correction;
- no sidecar schema change;
- no Research admission change;
- no batch validation;
- no performance optimization.

## Validation

Required automated validation:

- Bybit response normalization;
- permanent API failure single-attempt behavior;
- rate-limit retry and reset-header behavior;
- bounded transient retry;
- cancellation during retry sleep;
- downloader retry of non-exhausted transient failures;
- downloader refusal to amplify exhausted provider retries;
- repair failure without CSV or sidecar mutation;
- complete repository suite;
- compileall and diff checks.

Required external validation:

```powershell
python tools/dev_run_bybit_ohlcv_hardening.py
```

The task may be committed only after the real-provider smoke prints:

```text
TASK 1012 REAL-BYBIT SMOKE: PASS
```
