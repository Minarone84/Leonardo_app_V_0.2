# Traceable Objects

Leonardo V2 traceable object contracts define the shared vocabulary for
identifiable, inspectable, relationship-aware objects. They are contract models,
not runtime services.

## Scope

The contracts live in `leonardo.contracts.traceable_object` and define:

- `TraceableObjectRef`
- `TraceableRelationshipRef`
- `TraceableObjectSummary`
- `ObjectFamilyLegend`
- `ObjectInterrogationRequest`
- `ObjectInterrogationReport`

These contracts do not implement an Object Map provider, Runtime Manager
behavior, GUI behavior, Download Manager execution, adapters, storage writers,
Data Manager behavior, Analysis Suite behavior, or trading behavior.

## Ownership Policy

Core defines the common traceability vocabulary. Each object family defines its
own legend later. Each owning service, store, or registry remains the mutation
owner for its own object family.

The future Object Map is read-only. Runtime Manager remains read-only and
snapshot-based. StateStore remains current runtime truth. AuditLog remains
historical truth. GUI remains shell, intent, display, and local Qt object
lifetime.

## Contract Roles

`TraceableObjectRef` identifies one object by stable object ID, object kind, and
owner domain. Optional owner component, schema version, label, and metadata may
add display or family context.

`TraceableRelationshipRef` links two object references with a relationship type
such as `triggers`, `creates_operation`, `schedules_task`, `uses_connection`,
`owns_channel`, `creates_plan`, `writes_dataset`, `derives_from`, `produces_artifact`,
`validates`, `supersedes`, `owns`, `references`, or `depends_on`.

`TraceableObjectSummary` is the common trace envelope emitted by an object owner.
It carries lifecycle, runtime/persistent classification, metadata references,
relationship refs, permission refs, audit refs, operation refs, task refs,
source refs, correlation refs, and family-specific extra data.

`ObjectFamilyLegend` describes one object family's ownership and interrogation
contract. It identifies mutation owner, read provider, truth source, identity
fields, metadata fields, lifecycle statuses, allowed actions, permissions,
audit event types, relationships, related contracts, docs, and tests.

Canonical static family descriptors live in
`leonardo.contracts.object_family_legends` and are documented in
`docs/contracts_docs/OBJECT_FAMILY_LEGENDS.md`.

Canonical static relationship descriptors live in
`leonardo.contracts.object_relationships` and are documented in
`docs/contracts_docs/OBJECT_RELATIONSHIPS.md`. These descriptors define
relationship rules. Actual observed relationships remain
`TraceableRelationshipRef` instances.

Read-only Object Map protocol and report contracts live in
`leonardo.contracts.object_map` and are documented in
`docs/contracts_docs/OBJECT_MAP_PROTOCOL.md`. They define future provider
descriptor, section, snapshot, query, and query-report shapes only.

The first concrete read-only GUI window family trace helper is documented in
`docs/contracts_docs/WINDOW_FAMILY_TRACE.md`. It emits window summaries from
static metadata and does not implement a live Object Map service.

The concrete read-only GUI action family trace helper is documented in
`docs/contracts_docs/ACTION_FAMILY_TRACE.md`. It emits action summaries from
static metadata and static GUI action definitions without executing actions.

`ObjectInterrogationRequest` and `ObjectInterrogationReport` define future
read-only interrogation shapes. They do not perform authorization, query state,
or mutate objects.

Relationship, summary, legend, request, and report contracts carry a
`schema_version` field for the traceability contract shape. `TraceableObjectRef`
also supports an optional `schema_version` for the referenced object's own
family schema when that information is known.

## Non-Goals

These contracts intentionally avoid:

- a rigid universal domain schema;
- a global object registry that owns every object;
- a base class that every object family must inherit from;
- Runtime Manager controller behavior;
- Object Map service/provider implementation;
- GUI, Download, Data Manager, Analysis Suite, adapter, storage, or trading
  behavior.

## Validation

Focused contract coverage lives in
`tests/contracts_test/test_traceable_object_contracts.py`.
