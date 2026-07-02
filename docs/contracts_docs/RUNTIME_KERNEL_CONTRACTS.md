# Runtime Kernel Contracts

The runtime kernel contracts define the minimal structured data used by the
Core runtime foundation.

Included contracts:

- identity: `UserRef`, `SessionContext`, roles, permissions, and actor origin;
- audit: structured audit events and optional error payloads;
- runtime: current app and service runtime state;
- services: service descriptors and service kind;
- errors: structured error reports.

The development Administrator identity is temporary runtime identity for local
development. It does not implement authentication, passwords, credential
storage, or external identity providers.

Audit events represent historical truth. Runtime state contracts represent
current truth and are not event history.

This phase does not include async task contracts, process contracts,
connection/websocket contracts, GUI/window/action/operation contracts, Data
Manager contracts, financial-tool contracts, or old-code reuse.
