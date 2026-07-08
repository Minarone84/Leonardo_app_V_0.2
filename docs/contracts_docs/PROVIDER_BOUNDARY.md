# Provider Boundary Contracts

`leonardo.contracts.provider_boundary` defines pure read-only descriptor
contracts for the Provider/Connection boundary.

This phase creates vocabulary only. It does not implement provider clients,
network transport, websocket transport, subscription execution, reconnect
behavior, Runtime Manager provider summaries, Object Map provider helpers,
Download Data behavior, GUI features, storage writers, concrete suites, mutable
provider registries, automatic discovery, filesystem scanning, or import-time
registration.

## Terminology

A provider is a stable external or internal capability source such as an
exchange, broker, file source, mock provider, local data source, or service
provider.

A provider adapter is a future implementation boundary. Adapters may later own
provider-specific API calls, session construction, pagination, reconnect
behavior, rate handling, and provider-specific error mapping. Adapter behavior
is not part of these contracts.

A provider capability describes what a provider can support. Examples include
historical market data, live streams, account reads, order submission, file
reads, data imports, websocket subscription capability, and metadata access.
Capabilities are static/read-model declarations, not executable adapters.

A provider session describes safe runtime metadata about a provider interaction.
It may reference a provider, connection, actor/session, and active capability
IDs. It must not include credentials, tokens, client handles, callbacks,
sockets, raw API responses, or raw provider payloads.

A connection is a Core-tracked communication identity. `ConnectionRegistry`
owns connection and websocket-channel tracking state only. It does not own
provider adapters, reconnect behavior, subscriptions, provider sessions, or
message payload storage.

A websocket channel is a Core-tracked channel under a connection. The channel
tracks identity, status, counters, timestamps, and safe metadata only.

A provider subscription descriptor records subscription intent or binding
metadata. It does not subscribe, unsubscribe, reconnect, or execute stream
behavior.

A provider message trace descriptor records bounded message metadata such as
direction, kind, size, and key names. It does not store raw message values,
full response bodies, or streams.

## Contract Shapes

`ProviderDescriptor` describes provider identity, owner, lifecycle status,
supported capability IDs, supported connection kinds, coarse transport support,
permissions, object families, docs, tests, metadata references, warnings, and
blockers.

`ProviderCapabilityDescriptor` describes one capability by stable capability ID,
provider ID, kind, label, required permission, connection and websocket
requirements, schema references, rate-limit reference, audit category, object
families, docs, tests, warnings, and blockers.

`ProviderSessionDescriptor` describes safe provider session metadata. It stores
provider/session identifiers, optional connection and actor/session references,
status, authentication-mode summary, activity timestamps, active capabilities,
counts, bounded warnings/errors, docs, tests, and read-only safe metadata.

`ProviderSubscriptionDescriptor` describes subscription identity and references:
provider, provider session, capability, connection, websocket channel, topic,
status, timestamps, counts, required permission, object families, docs, tests,
warnings, and errors.

`ProviderMessageTraceDescriptor` describes bounded message metadata: provider,
provider session, subscription, connection, websocket channel, direction,
message kind, observed time, payload kind, payload size, payload key count,
payload key names, correlation ID, counts, docs, tests, warnings, and errors.

All descriptor classes are frozen dataclasses. Sequence fields normalize to
tuples. Required IDs reject empty strings. Optional IDs reject blank strings
when present. Counts reject negative values. Session metadata is converted to
read-only mappings and rejects sensitive metadata key names.

## Ownership Model

Core owns runtime truth, task and operation lifecycle, state, audit,
permissions, runtime inspection, Object Map aggregation, process tracking, and
connection/websocket tracking.

The provider layer may later own provider descriptors, provider capability
descriptors, provider session descriptors, adapter interface boundaries,
subscription descriptors, safe provider read models, provider audit categories,
provider Object Map helpers, and provider Runtime Manager summary providers.

The provider layer must not own Core runtime startup or shutdown, TaskManager,
OperationRegistry, StateStore, AuditLog, RuntimeManagerBackend,
ReadOnlyObjectMapService aggregation, GUI widgets, suite domain behavior,
global permission policy, or storage writers unless a future phase explicitly
scopes storage writer ownership.

`ConnectionRegistry` remains the connection/channel tracking owner. It must not
become a provider adapter owner, reconnect engine, subscription executor,
message payload store, suite/domain owner, or Runtime Manager controller.

## Permission Strategy

Provider boundary descriptors use existing permission strings such as
`connection:view`, `connection:subscribe`, `download:view`, and other
established area namespaces.

This phase does not expand `leonardo.contracts.identity.Permission`.

Future provider-specific permission names may be added only after a focused
permission audit. Future suite commands that depend on providers should declare
their suite/domain permission and any required provider capability permission.
Denied provider actions must not create tasks, operations, connections,
sessions, subscriptions, or provider runtime handles.

## Audit And Sensitive Data Policy

Future provider audit facts should include bounded identifiers only:

- provider ID;
- provider session ID;
- capability ID;
- connection ID;
- websocket channel ID;
- subscription ID;
- operation ID;
- task ID;
- actor/session IDs;
- window/action IDs when GUI-originated;
- correlation ID;
- required permission;
- bounded payload summary;
- error metadata.

Provider boundary contracts and future audit records must not contain
credentials, tokens, secrets, passwords, raw client handles, callbacks, sockets,
raw websocket payload streams, full API responses, full environment values,
large datasets, account secrets, order secrets, or private runtime objects.

## Object Map Strategy

Provider Object Map exposure is read-only and descriptor-driven. Provider
Object Map helpers consume explicit descriptors and safe read models. They
produce read-only provider entries and sections through app composition. They
must not create a mutable provider registry, scan the filesystem, scan modules,
perform automatic discovery, or register at import time.

Likely provider object families are:

- `provider`;
- `provider_capability`;
- `provider_session`;
- `provider_subscription`;
- `provider_message_trace`.

Existing `download_capability` remains a Download-specific read-model family.
It is not a generic provider capability replacement.

## Runtime Manager Strategy

Runtime Manager provider summaries are compact, read-only, and provider-only
when supplied through the accepted summary boundary. They may include provider
ID, status, active session count, active subscription count, connection count,
websocket channel count, warnings, errors, last heartbeat, degraded status, and
unavailable reason.

Runtime Manager must not expose connect, disconnect, retry, reconnect,
subscribe, unsubscribe, credential, payload, or raw provider-control surfaces.

## Relationship To Suites

Provider/Connection is shared infrastructure, not a suite.

Suites should depend on provider capability IDs, safe read models, and approved
provider service interfaces. Suites must not receive raw provider clients or
silently own provider sessions. App composition may later inject approved
provider services into suite services through an explicit boundary.

## Relationship To Download Data

Download Data now has a sandboxed Bybit OHLCV execution path through the
Download Manager area. It consumes capability-style facts and safe read models;
it does not own provider sessions, raw clients, credentials, websocket
subscriptions, reconnect behavior, or provider registries.

The current default Download Data execution path is fixture-backed/offline and
writes only under an explicit sandbox root. Live Bybit public REST transport is
opt-in only and remains sandbox-only. Provider/Connection boundaries remain the
owners of provider capability and transport facts.

## Validation

Focused tests live in
`tests/contracts_test/test_provider_boundary_contracts.py`.

## Later Work

Concrete provider adapters, registries, discovery, transport sessions,
subscriptions, reconnect behavior, and provider-owned execution remain separate
future phases.
