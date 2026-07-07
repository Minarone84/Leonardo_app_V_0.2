# Object Map Protocol

The Object Map protocol defines read-only report and query contracts for future
traceable object inspection. It describes how future object-family owners may
expose summaries, relationships, legends, and relationship definitions.

The contracts live in `leonardo.contracts.object_map`.

## Scope

The module exports immutable data contracts only. It does not implement a live
Object Map service, provider implementation, provider registry, runtime
discovery, filesystem scanning, Runtime Manager section, GUI behavior, Download
execution, adapter behavior, storage writer, Data Manager behavior, Analysis
Suite behavior, or trading behavior.

The Object Map protocol does not own objects. It does not mutate objects. It
does not execute commands. It does not replace domain owners.

## Contract Shapes

`ObjectMapProviderDescriptor` describes a future read-only provider's declared
scope. It identifies provider ID, owner, object kinds, family IDs,
relationship types, read capabilities, related contracts, docs, tests, metadata,
and extra data. It defaults to `read_only=True` and
`mutation_forbidden=True`.

`ObjectMapSection` is a read-only report section emitted by a future provider.
It may contain object summaries, relationship references, family legends,
relationship definitions, warnings, blockers, errors, metadata, and extra data.

`ObjectMapSnapshot` aggregates read-only sections and provider descriptors. It
owns no object truth and performs no discovery.

`ObjectMapQuery` is a read-only query shape for future Object Map consumers. A
broad empty query is valid. Query flags select summaries, relationships,
legends, relationship definitions, provider descriptors, docs, and tests.

`ObjectMapQueryReport` is a read-only query result. It carries the query,
sections, summaries, relationships, legends, relationship definitions, provider
descriptors, warnings, blockers, errors, metadata, and extra data.

## Related Contracts

The protocol uses existing traceability contracts:

- `TraceableObjectSummary`
- `TraceableRelationshipRef`
- `ObjectFamilyLegend`
- `ObjectRelationshipDefinition`

Static family descriptors remain in `leonardo.contracts.object_family_legends`.
Static relationship descriptors remain in
`leonardo.contracts.object_relationships`. Actual object summaries and
relationship instances must come from future family owners.

## Ownership Boundary

Core owns the common traceability vocabulary, canonical family descriptors,
canonical relationship descriptors, and read-only Object Map protocol
contracts. Core does not own every domain object. Each object owner remains the
truth source for its own object family.

Runtime Manager remains read-only and snapshot-based. GUI remains shell, intent,
display, and local Qt object lifetime. Download Manager, Data Manager, Analysis
Suite, adapters, storage writers, and trading behavior remain outside this
protocol.

The first concrete GUI window family trace helper is documented in
`docs/contracts_docs/WINDOW_FAMILY_TRACE.md`. It emits read-only sections from
static window metadata without creating a live Object Map service.

The concrete GUI action family trace helper is documented in
`docs/contracts_docs/ACTION_FAMILY_TRACE.md`. It emits read-only sections from
static action metadata and static GUI action definitions without registering a
provider or executing actions.

## Validation

Focused tests live in `tests/contracts_test/test_object_map_contracts.py`.
