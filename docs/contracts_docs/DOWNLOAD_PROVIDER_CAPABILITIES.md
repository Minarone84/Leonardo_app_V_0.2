# Download Provider Capabilities

This document defines the first Leonardo V2 provider capability contracts for
future Download Data execution. These contracts describe provider facts only.
They do not implement adapters, REST clients, WebSocket clients, catalog
loading, file output, storage writers, Runtime Manager controls, GUI behavior,
TaskManager execution, OperationRegistry lifecycle, Data Manager integration, or
old-code reuse.

## Ownership Model

Provider capability contracts describe what a provider market claims to support:

- provider identity;
- market identity;
- supported data kinds;
- canonical timeframe support;
- provider-native interval tokens;
- transport categories;
- request and page limits;
- non-live timeframe expansion policy.

Adapters will later own provider-specific execution behavior. Capability
contracts do not fetch, authenticate, subscribe, paginate, retry, or normalize
live provider responses.

## Capability Contracts Versus Adapters

The capability model is a read model. It can be used by future layered preflight
to decide whether a request is structurally compatible with known provider
facts.

Adapter implementations are a separate future boundary. They will be responsible
for provider API calls, source-specific symbols, range discovery, pagination,
rate-limit behavior, provider error mapping, and transport details. They must
not own GUI behavior, Runtime Manager state, storage policy, or Data Manager
cataloging.

## Market And Timeframe Semantics

`ProviderMarketCapability` groups provider facts for one market such as `spot`,
`futures`, `perp`, or `margin`. A market can be supported, unsupported, unknown,
or deprecated.

`ProviderTimeframeCapability` maps a Leonardo canonical timeframe such as `1m`,
`5m`, `1h`, or `1d` to the provider-native interval token. Supported timeframes
must declare a non-empty provider interval. Unsupported, unknown, or deprecated
timeframes are valid facts, but they are excluded from supported expansion.

Canonical timeframe validation follows the same shape as the OHLCV storage
policy: positive numeric amount plus unit `m`, `h`, `d`, or `w`.

## Transport Stance

The contracts can describe REST, WebSocket, file, and mock transports. Historical
OHLCV Download Data should not require WebSocket by default. WebSocket support is
a future-compatible capability fact for live or streaming workflows and for
providers that explicitly require it.

Transport declarations do not create sockets, clients, sessions, or connection
registry state.

## Rate And Page Limits

`ProviderRateLimitPolicy` and timeframe-level limits describe known request,
weight, and page-size constraints. Limits must be non-negative when present, and
maximum limits must be greater than or equal to default limits.

These contracts do not throttle requests or implement provider backoff. They are
input facts for future execution-cost estimates and preflight.

## Timeframe Expansion Policy

`expand_timeframes()` expands only from declared in-memory capability facts:

- `explicit` returns requested supported timeframes and reports unsupported
  requested values as issues.
- `all` returns every supported timeframe.
- `supported` returns every supported timeframe.
- `default` returns the deterministic `metadata.default_timeframes` set when
  declared, otherwise the first supported timeframe.

The helper never invents fake timeframes, performs live discovery, reads a
catalog, or calls an adapter.

## Future Layered Preflight

These contracts feed the future source/catalog capability preflight layer. The
expected later layering remains:

1. structural request preflight;
2. provider/source capability preflight;
3. connection readiness preflight;
4. storage/output path preflight;
5. conflict-policy preflight;
6. execution-cost and rate-limit estimate.

Runtime Manager should continue to display resulting read models only. It should
not execute capability checks or expose controls from this contract layer.

## Explicitly Out Of Scope

This phase does not add:

- provider adapters;
- REST, WebSocket, or file clients;
- network calls;
- process launching;
- file writes;
- storage writer behavior;
- static catalog loading;
- Core services;
- GUI behavior;
- Runtime Manager behavior;
- TaskManager wiring;
- OperationRegistry wiring;
- ProcessManager usage;
- Data Manager integration;
- dependency changes;
- CLI, app entry, or installer behavior;
- old Leonardo source import or copy.
