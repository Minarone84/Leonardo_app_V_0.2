# Core Runtime Manager Backend

`RuntimeManagerBackend` is the CORE-10 backend/read-model facade for the Runtime
Manager surface.

The backend aggregates current runtime truth from existing Core owners:

- `StateStore`
- `SessionManager`
- `ServiceRegistry`
- `TaskManager`
- `WindowRegistry`
- `ActionRegistry`
- `OperationRegistry`
- `AuditLog`
- `ContractRegistry`
- optional Object Map snapshot provider
- optional provider runtime summary provider
- optional suite runtime summary provider
- optional Download Data runtime summary provider

`snapshot()` returns a defensive `RuntimeManagerSnapshot`. The backend reads
current app lifecycle state, current session identity, service visibility, active
tasks, open windows, recent action triggers, active operations, retained audit
events, audit sink failures, contract registry counts, and an optional compact
Object Map summary when a read-only `ObjectMapSnapshot` provider is injected.
It may include an optional compact provider runtime summary when a read-only
`ProviderRuntimeSummary` provider is injected by app composition.
It may also include an optional compact suite/area runtime summary when a
read-only `SuiteRuntimeSummary` provider is injected by app composition.
It may include an optional compact Download Data runtime summary when a
read-only `DownloadDataRuntimeSummary` provider is injected by app composition.

Object Map integration is snapshot-only. Runtime Manager consumes an optional
injected callable that returns `ObjectMapSnapshot`. It does not own Object Map,
register providers, consume `ObjectMapProviderEntry`, call provider
`build_section` functions directly, read source managers for Object Map data, or
route Object Map interrogation.

Object Map diagnostics are sanitized and deduplicated before Runtime Manager
metadata is produced. Warning, error, and blocker counts represent the full
unique diagnostic totals, while the displayed diagnostic tuples are bounded and
redacted for read-only Runtime Manager display. GUI display must keep those
diagnostics read-only and must not repair, retry, execute, cancel, or control
Object Map provider output.

Provider runtime summary integration is explicit-injection only. Runtime
Manager consumes an optional callable returning frozen `ProviderRuntimeSummary`
values. It does not construct provider descriptors, import provider Object Map
helpers, register providers, discover providers, construct adapters, create
clients, open network transports, implement websocket behavior, execute
subscriptions, reconnect providers, or own provider behavior. The compact
`provider_runtime` section reports provider counts, capability/session/
subscription/message-trace totals, Object Map section totals, bounded
diagnostics, degraded/unavailable counts, and last activity metadata.

Provider runtime summaries must not carry credentials, tokens, secrets,
passwords, API keys, raw clients, sockets, raw payloads, full API responses, or
large data dumps. Diagnostics are sanitized, deduplicated, and bounded before
being exposed through Runtime Manager metadata.

Suite runtime summary integration is provider-only. Runtime Manager consumes an
optional injected callable returning frozen `SuiteRuntimeSummary` values. It
does not construct suite descriptors, scan modules, import concrete suite
packages, register suite providers, or own suite behavior. The compact
`suite_runtime` section reports visible suite and area counts, module totals,
active operation and task totals, Object Map section totals, bounded diagnostics,
degraded/unavailable counts, and last activity metadata.

Download Data runtime summary integration is explicit-injection only. Runtime
Manager consumes an optional callable returning frozen
`DownloadDataRuntimeSummary` values. It does not import Download Data Object Map
helpers, construct Download Data boundary contracts, call adapters or provider
clients, access network/API/websocket/subscription behavior, write storage,
cancel work, integrate Data Manager, discover providers, or own Download Data
behavior. The compact `download_data_runtime` section reports workflow,
selection, preflight, progress, completion, output, storage-target,
partial-persistence, step, bar, degraded/unavailable, diagnostic, and last
activity metadata.

Download Data runtime summaries must not carry credentials, tokens, secrets,
passwords, API keys, raw clients, sockets, raw payloads, full API responses,
provider objects, adapters, storage writers, handles, GUI objects, Data Manager
objects, runtime task objects, or large data dumps. Diagnostics are sanitized,
deduplicated, and bounded before being exposed through Runtime Manager metadata.

The backend does not own runtime state. It does not mutate `StateStore`, register
services, register windows or actions, execute actions, start or cancel tasks,
create audit files, own Object Map providers, own suite summary providers,
own provider summary providers, own Download Data summary providers, repair
Object Map output, route Object Map interrogation, transfer ConnectionRegistry
ownership, infer persisted OHLCV truth, or perform lifecycle transitions.

Runtime Manager display remains read-only. Runtime Manager controls, Object Map
interrogation routing, provider repair, lifecycle control, Data Manager
behavior, Analysis Suite behavior, Trading Suite behavior, provider transport,
suite execution, downloader execution, cancellation behavior, Download Data
continuation, concrete suite behavior, adapter code, storage writers, app startup
changes, AI helpers, and old Leonardo code reuse remain outside this backend.
