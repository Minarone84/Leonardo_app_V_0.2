# Connection Runtime Contracts

Connection runtime contracts define the Core observability boundary for
connection and WebSocket channel tracking.

`ConnectionEndpoint` describes a labeled endpoint using protocol, host, port,
path, and metadata descriptors. It is descriptive state only and does not hold a
client, stream, socket, callback, or runtime handle.

`ConnectionDefinition` defines a stable connection identity. It includes the
connection identifier, label, kind, protocol, direction, optional endpoint,
optional service/process correlation, and metadata.

`ConnectionRuntimeState` represents current or last-known connection truth.
Connection definitions are long-lived, so disconnected and failed states remain
visible in runtime snapshots until a future owner explicitly removes or replaces
the definition. Audit history remains the historical truth.

`WebSocketChannelDefinition` defines a stable channel identity under a known
connection. `WebSocketChannelRuntimeState` tracks the channel lifecycle status,
last message timestamp, and received/sent/error counters.

`ConnectionEventRecord` describes one connection event as structured data. Core
audit logging is still the historical event owner.

These contracts do not open sockets, authenticate, reconnect, store credentials,
store message payloads, implement exchange/broker adapters, perform market data
ingestion, or define Runtime Manager GUI behavior.
