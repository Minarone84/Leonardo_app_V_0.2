# Download Data Execution Contracts

`leonardo.contracts.download_data_execution` defines immutable boundary
contracts for future Download Data execution. The contracts describe execution
commands, targets, provider page requests and normalized page results, storage
write requests and results, progress events, final results, errors, and plans.

This phase is contract-only. It does not implement transport, provider APIs,
Bybit calls, network clients, file writes, CSV persistence, metadata sidecar
writes, GUI behavior, Runtime Manager behavior, Object Map behavior, AI helper
behavior, app startup behavior, adapters, registries, discovery, or old
Leonardo code import.

## Ownership Split

Download Data execution is a boundary between multiple owners:

- Core may later route commands, supervise lifecycle, and correlate operation or
  task identifiers.
- Provider and exchange layers may later translate provider page requests into
  bounded transport calls and return normalized page results.
- Storage and data layers may later write accepted OHLCV outputs through their
  own storage policy.
- GUI surfaces may collect user intent and display read models, but must not own
  transport, storage writes, provider truth, or execution state.

The contracts do not create a Download Manager, Download Execution Manager,
Provider Registry, concrete adapter, storage writer, Runtime Manager control,
or Object Map helper.

## Execution Target

`DownloadDataExecutionTarget` identifies one exchange, market type, symbol,
timeframe, storage target reference, execution mode, and traversal direction.
It may also carry bounded timestamp facts from user intent, local state, or
provider capability facts.

Required identity fields must be explicit and non-blank. No default exchange,
market type, symbol, timeframe, or storage target is invented by the execution
contracts.

## Provider Page Request and Result

`DownloadDataProviderPageRequest` is a future adapter boundary input. It is not
a transport request object and carries no network client or provider handle.

Provider-specific facts are explicit:

- `category` is required because Bybit market endpoints can default to linear
  if category is omitted;
- `interval` is required as the provider-facing timeframe value;
- `limit` is bounded and defaults to a conservative value;
- `direction` describes forward update versus backward historical traversal.

`DownloadDataProviderPageResult` contains normalized candles and compact status
facts. It does not carry raw API responses, raw payloads, HTTP objects, sockets,
or client handles.

Before any real implementation, the Bybit documentation must be checked again,
including the `/v5/market/kline` endpoint, instrument metadata endpoint,
category handling, interval values, page limits, and returned sort order.
Bybit klines have historically returned reverse-sorted lists, so implementation
must normalize to the storage-required ascending candle order before writing.

## Normalized Candle

`DownloadDataNormalizedCandle` is the minimal canonical OHLCV candle row:

- timestamp in milliseconds;
- open;
- high;
- low;
- close;
- volume;
- optional turnover;
- optional source order.

The contract intentionally stores decimal-like values as JSON-friendly scalar
values and does not retain raw provider rows.

## Storage Write Request and Result

`DownloadDataStorageWriteRequest` is a future storage boundary input. It carries
relative POSIX CSV and metadata sidecar paths, normalized candles, write mode,
deduplication intent, sort order, and atomic-write intent.

The contract does not create directories, open files, write files, validate
files, or mark outputs accepted. It only describes a future storage boundary
call.

`DownloadDataStorageWriteResult` reports what the storage boundary did later.
Partial write results are explicitly not accepted, not loadable, and not
validated. Partial files may be useful for recovery or repair, but they are not
accepted clean data.

## Progress, Result, and Error Read Models

`DownloadDataExecutionProgressEvent` is a compact read model for later UI or
Runtime Manager display. It is read-only and contains no callbacks or controls.

`DownloadDataExecutionResult` aggregates target, progress, storage result, and
error facts. It computes written bar counts, partial counts, and failed counts
from read-model inputs. It does not execute, retry, cancel, resume, or submit
work.

`DownloadDataExecutionError` carries a bounded status, code, redacted message,
retryability flags, and compact metadata. It does not carry raw API responses,
raw payloads, provider handles, sockets, clients, credentials, or stack dumps.

## Metadata Safety

All metadata is compact and read-only. Metadata values are limited to
JSON-friendly scalar values, nested mappings, and sequences. Sensitive metadata
keys are blocked recursively. Non-finite float values are rejected recursively.

Blocked key terms include credential, credentials, token, secret, password,
api_key, authorization, bearer, client, socket, payload, raw_payload, response,
provider, adapter, writer, and handle.

Progress and error messages are bounded. Messages containing sensitive transport
or credential terms are redacted.

## First Smoke Recommendation

The first real smoke implementation should remain separate from these
contracts. Recommended shape:

- use a mock provider transport first;
- use a single explicit target such as Bybit spot BTCUSDT 1m;
- use a small bounded page limit;
- write only under an explicit sandboxed output root;
- create a new-file path only;
- keep partial writes unaccepted, unloadable, and unvalidated;
- recheck provider documentation immediately before real transport work.

No production or user data path should be used for the first smoke.

## Explicitly Out Of Scope

This contract phase does not add:

- real provider transport;
- Bybit or other exchange API calls;
- network calls;
- client, socket, websocket, or subscription behavior;
- storage writes;
- file reads;
- file validation;
- cancellation, resume, retry, or execution behavior;
- Runtime Manager controls or summaries;
- Object Map helpers or Object Map service changes;
- Download Manager or Download Execution Manager behavior;
- provider adapter implementation;
- discovery or registration;
- GUI behavior;
- Data Manager integration;
- AI helper behavior;
- old Leonardo source import;
- app startup changes.

## Validation

The contract is covered by:

```text
tests/contracts_test/test_download_data_execution_contracts.py
```
