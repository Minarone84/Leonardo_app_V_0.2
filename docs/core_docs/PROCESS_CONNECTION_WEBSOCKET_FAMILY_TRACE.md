# Process Connection WebSocket Family Trace

`leonardo.core.process_connection_trace` exposes Core process, connection, and
WebSocket channel read models through the shared traceability and Object Map
contracts.

## Scope

The helper builds read-only `TraceableObjectRef`, `TraceableObjectSummary`,
`TraceableRelationshipRef`, `ObjectMapProviderDescriptor`,
`ObjectMapSection`, and `ObjectInterrogationReport` values for the `process`,
`connection`, and `websocket_channel` families.

It reads existing state from:

- `ProcessManager.active_processes()`
- `ConnectionRegistry.connection_states()`
- `ConnectionRegistry.websocket_channel_states()`
- `ConnectionRegistry.list_connections()`
- `ConnectionRegistry.list_websocket_channels()`
- `StateStore` process, connection, and channel state methods
- `RuntimeSnapshot` process, connection, and channel tuples
- explicit state tuples supplied by tests or callers

The helper does not change process lifecycle, connection lifecycle, channel
lifecycle, current runtime state, audit history, Runtime Manager wiring, Object
Map registration, provider/client behavior, transport behavior, or domain
behavior.

## Sensitive Fields

Process summaries expose only the first command token and token count. Process
environment values are never exposed. Connection summaries expose endpoint label
and protocol only; endpoint address fields are redacted. WebSocket summaries do
not include raw message payloads.

## Relationships

When identifiers are present, the helper emits:

- `process -> operation` via `references`
- `process -> task` via `references`
- `connection -> websocket_channel` via `owns_channel`
- `websocket_channel -> connection` via `references`

Missing optional identifiers do not create placeholder relationships.

## Validation

Focused tests live in
`tests/core_test/test_process_connection_websocket_family_trace.py`.
