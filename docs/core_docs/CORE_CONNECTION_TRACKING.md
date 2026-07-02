# Core Connection Tracking

`ConnectionRegistry` is the CORE-12 backend service for connection and
WebSocket channel tracking.

Responsibilities:

- register connection definitions;
- reject duplicate connection identifiers;
- register WebSocket channel definitions under known connections;
- reject duplicate channel identifiers;
- reject channels for unknown connections;
- delegate current runtime state to `StateStore`;
- emit audit history through `StateStore` lifecycle transitions;
- expose defensive connection and channel snapshots;
- provide Runtime Manager backend readback through connection summaries.

Runtime state is current or last-known truth. Disconnected and failed
connections remain visible because connection definitions are long-lived
observability identities. WebSocket channel states remain visible while
registered, with last-known counters and status. Audit log history is historical
truth.

Runtime Manager backend summarizes:

- registered/current connection count;
- connected, degraded, failed, and disconnected counts;
- WebSocket channel count;
- received, sent, and error counters.

The connection section is neutral when empty. Runtime health degrades when a
tracked connection is degraded or failed.

This Core phase does not open sockets, authenticate, reconnect, store
credentials, subscribe to streams, implement exchange/broker adapters, perform
market data ingestion, or add Runtime Manager GUI behavior. Real connection
adapters are future work and must be introduced by a later scoped phase.
