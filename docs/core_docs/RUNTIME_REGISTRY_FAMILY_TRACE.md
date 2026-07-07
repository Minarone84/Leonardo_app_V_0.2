# Runtime Registry Family Trace

`leonardo.core.runtime_registry_trace` exposes read-only trace summaries for
Core runtime registry-style families: app runtime, current session, registered
services, registered contract descriptors, and explicit error reports.

## Scope

The helper reads existing public APIs only:

- `StateStore.runtime_snapshot()`
- `SessionManager.current_session`
- `ServiceRegistry.list_services()`
- `ContractRegistry.list_contracts()`
- explicit `ErrorReport` values supplied by a caller

`ErrorRouter` does not currently retain routed reports behind a public read API,
so the helper does not inspect private error-router state. Error report
visibility remains limited to explicit `ErrorReport` values until a future
retained read model is approved.

The helper does not mutate runtime state, register providers, route errors,
emit audit events, change service lifecycle, wire Runtime Manager, or introduce
an Object Map service.

## Summaries

The helper builds read-only `TraceableObjectRef`, `TraceableObjectSummary`,
`TraceableRelationshipRef`, `ObjectMapProviderDescriptor`, `ObjectMapSection`,
and `ObjectInterrogationReport` values for:

- `app_runtime`
- `session`
- `service`
- `contract_descriptor`
- `error_report`

Summaries are derived from existing Core owner read APIs or explicit caller
inputs. Missing optional objects do not create placeholder summaries.

## Ownership

StateStore remains the owner of current app and service runtime state.
SessionManager remains the owner of current session identity. ServiceRegistry
remains the service registration owner. ContractRegistry remains the contract
descriptor owner. ErrorRouter remains the routing owner, while this helper only
summarizes explicit `ErrorReport` values.

## Relationships

When identifiers are present, the helper emits read-only relationships such as:

- app runtime to current session;
- app runtime to registered services;
- registered services to related contracts;
- error reports to related tasks, operations, services, sessions, or contracts.

Missing optional identifiers do not create fake relationships.

## Runtime Manager And Object Map Consumption

The helper can be supplied explicitly to `ReadOnlyObjectMapService` through an
`ObjectMapProviderEntry`. Runtime Manager may see the resulting aggregate only
through an injected `ObjectMapSnapshot` provider and compact
`object_map_summary`. Runtime Manager does not import or call this helper
directly.

## Validation

Focused tests live in `tests/core_test/test_runtime_registry_family_trace.py`.
