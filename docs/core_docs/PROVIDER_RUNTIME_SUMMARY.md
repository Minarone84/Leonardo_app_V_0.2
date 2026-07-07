# Provider Runtime Summary

`ProviderRuntimeSummary` is the first read-only Runtime Manager integration for
provider-boundary runtime read models.

Runtime Manager consumes optional injected `ProviderRuntimeSummary` values and
exposes one compact `provider_runtime` `RuntimeSectionSummary`. The injection
point is explicit composition input only.

## Scope

The summary reports provider runtime visibility:

- provider IDs and display names;
- provider status and optional provider kind;
- capability counts;
- session, active session, and connected session counts;
- subscription and active subscription counts;
- bounded message trace counts;
- Object Map section counts;
- warnings, errors, unavailable reasons, degradation state, and last activity.

The section is a read-only inspection surface. It is not a provider control
surface and does not create tasks, operations, sessions, subscriptions,
connections, or audit events.

## Boundaries

Runtime Manager does not own provider runtime truth. It consumes injected frozen
summaries and aggregates them into inspection metadata.

This phase does not add:

- provider registry behavior;
- automatic discovery;
- provider descriptor scanning;
- adapter implementation;
- client construction;
- network access;
- websocket transport;
- subscription execution;
- reconnect behavior;
- Runtime Manager controls or actions;
- Object Map service changes;
- ConnectionRegistry ownership transfer;
- Download Data continuation;
- Download Manager continuation;
- concrete suite behavior;
- storage writers.

Connection and websocket tracking remain owned by the Core connection-tracking
subsystem. Provider summaries may reference connection-related counts, but they
do not own connection state.

## Data Safety

Provider runtime summaries must remain compact and read-only. They must not
contain credentials, tokens, secrets, passwords, API keys, authorization
headers, bearer values, raw clients, sockets, raw payloads, full API responses,
or large data dumps.

Runtime Manager sanitizes and bounds provider diagnostics before exposing them
in section metadata. Provider summary metadata rejects sensitive key names at
every nesting level during contract construction. Provider summary metadata
values are limited to JSON-compatible safe values: null, booleans, integers,
finite floats, strings, lists or tuples of safe values, and string-keyed
mappings of safe values.

## Failure Handling

If no provider summary callable is injected, Runtime Manager emits an OK
`provider_runtime` section with `available=false` and message:

```text
Provider runtime summaries unavailable
```

If the injected callable raises or returns invalid output, Runtime Manager emits
a degraded `provider_runtime` section with bounded redacted diagnostics. Other
Runtime Manager sections remain readable.

## Validation

Focused tests live in:

```text
tests/contracts_test/test_runtime_inspection_contracts.py
tests/core_test/test_runtime_manager_backend.py
```
