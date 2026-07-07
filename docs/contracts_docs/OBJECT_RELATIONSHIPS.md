# Object Relationships

Object relationship definitions describe the canonical static relationship
rules for traceable Leonardo V2 objects. They define allowed relationship
types, source and target object kinds, ownership, metadata expectations, related
contracts, docs, and tests.

The descriptors live in `leonardo.contracts.object_relationships`.

## Scope

The module exports immutable static `ObjectRelationshipDefinition` values only.
It does not implement an Object Map, provider protocol, runtime discovery,
Runtime Manager section, GUI behavior, Download execution, adapter behavior,
storage writer, Data Manager behavior, Analysis Suite behavior, or trading
behavior.

Actual observed relationship instances remain `TraceableRelationshipRef` values
from `leonardo.contracts.traceable_object`.

## Contract Shape

`ObjectRelationshipDefinition` records:

- `relationship_type`
- `source_object_kind`
- `target_object_kind`
- `source_family_id`
- `target_family_id`
- `direction`
- `lifecycle_statuses`
- `required_metadata_fields`
- `optional_metadata_fields`
- `owner_domain`
- `owner_component`
- `read_provider`
- `mutation_owner`
- `audit_event_types`
- `permission_refs`
- `related_contracts`
- `related_docs`
- `related_tests`
- `status`
- `schema_version`
- `extra`

Definitions are static rules. They do not create, discover, persist, execute, or
mutate relationships.

## Current Runtime Relationships

The current Core/runtime relationship types are:

- `triggers`
- `creates_operation`
- `schedules_task`
- `reports_progress`
- `produces_result`
- `fails_with`
- `cancelled_by`
- `uses_connection`
- `owns_channel`
- `records_audit`
- `described_by_contract`
- `has_permission`
- `opens_window`
- `contains_action`

These descriptors document current ownership boundaries between ActionRegistry,
OperationRegistry, TaskManager, ConnectionRegistry, WindowRegistry, UserPolicy,
ContractRegistry, ErrorRouter, and AuditLog. They do not move mutation
ownership into the relationship layer.

## Download Read-Model Relationships

The current Download read-model relationship types are:

- `creates_item`
- `creates_plan`
- `classified_by`
- `requires_capability`

These descriptors are marked read-model only. They do not imply Download
execution, adapter calls, provider network calls, or storage writers.

## Future Placeholder Relationships

The placeholder relationship types are:

- `derives_from`
- `produces_artifact`
- `has_metadata`
- `groups_artifact`
- `groups_recipe`
- `builds_database`
- `uses_dataset`
- `contains_study`
- `contains_chart_panel`
- `produces_report`
- `packages_report`
- `validates`
- `generates_signal`
- `creates_order_intent`
- `owns_subscription`
- `records_message`
- `supersedes`
- `references`
- `depends_on`

These descriptors are marked planned placeholders. They do not imply that Data
Manager, Analysis Suite, charting, adapters, provider sessions, websocket
transport, signal generation, order intent creation, or trading behavior exists.

## Helper Functions

The module provides deterministic read-only helpers:

- `all_object_relationship_definitions()`
- `object_relationship_definitions_by_type(relationship_type)`
- `object_relationship_definitions_for_source(object_kind)`
- `object_relationship_definitions_for_target(object_kind)`

The helpers return static in-memory descriptors. They do not inspect the
filesystem, query runtime services, discover objects, or mutate registries.

Read-only Object Map protocol contracts live in
`leonardo.contracts.object_map` and are documented in
`docs/contracts_docs/OBJECT_MAP_PROTOCOL.md`. Future Object Map sections may
carry relationship definitions, but relationship descriptors remain static
rules rather than live relationship instances.

## Ownership Boundary

Core owns the common traceability vocabulary and canonical relationship
descriptors. Each family owner remains responsible for mutation of its own
objects and relationship instances. A future Object Map may read these
descriptors, but it must remain read-only. Runtime Manager remains read-only and
snapshot-based. GUI remains shell, intent, display, and local Qt object
lifetime.

## Validation

Focused tests live in `tests/contracts_test/test_object_relationships.py`.
