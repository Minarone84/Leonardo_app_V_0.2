# Object Family Legends

Object family legends define the first canonical Leonardo V2 family descriptor
layer. They describe ownership, identity fields, metadata fields, lifecycle
states, permissions, audit facts, relationships, and related docs/tests for each
family.

The descriptors live in `leonardo.contracts.object_family_legends`.

## Scope

The module exports immutable static `ObjectFamilyLegend` values only. It does
not implement an Object Map, provider protocol, runtime discovery, Runtime
Manager section, GUI behavior, Download execution, adapter behavior, storage
writer, Data Manager behavior, Analysis Suite behavior, or trading behavior.

## Current V2 Families

The current V2 family descriptors are:

- `app_runtime`
- `session`
- `service`
- `task`
- `operation`
- `process`
- `connection`
- `websocket_channel`
- `window`
- `action`
- `contract_descriptor`
- `audit_event`
- `error_report`
- `download_request`
- `download_preflight`
- `download_item`
- `download_execution_snapshot`
- `download_capability`

These descriptors document current ownership and read-model boundaries. They do
not move mutation ownership into the legend layer.

Download Manager read-model families are owned by the Connection Suite domain
`connection.download_manager`. GUI remains presentation-only, and Core remains
runtime infrastructure for any routed work.

## Future Placeholder Families

The placeholder descriptors are:

- `study`
- `study_environment`
- `chart_session`
- `chart_panel`
- `workspace_snapshot`
- `notebook`
- `artifact_recipe`
- `recipe_collection`
- `saved_artifact`
- `artifact_metadata`
- `artifact_collection`
- `analysis_database`
- `analysis_project`
- `analysis_run`
- `analysis_report`
- `saved_rule_package`
- `validation_scenario`
- `trading_signal`
- `trading_strategy`
- `order_intent`
- `provider_session`
- `websocket_subscription`
- `websocket_message_trace`

These descriptors are marked as future placeholders. They do not imply that the
corresponding domain behavior, storage behavior, adapters, analysis behavior, or
trading behavior exists.

## Helper Functions

The module provides deterministic read-only helpers:

- `all_object_family_legends()`
- `object_family_legend_by_id(family_id)`
- `object_family_legend_by_kind(object_kind)`

The helpers return static in-memory descriptors. They do not inspect the
filesystem, query runtime services, discover objects, or mutate registries.

Canonical relationship definition descriptors live in
`leonardo.contracts.object_relationships` and are documented in
`docs/contracts_docs/OBJECT_RELATIONSHIPS.md`. Family legends name relationship
types, while relationship definitions describe source and target object-kind
rules.

Read-only Object Map protocol contracts live in
`leonardo.contracts.object_map` and are documented in
`docs/contracts_docs/OBJECT_MAP_PROTOCOL.md`. Future Object Map sections may
carry family legends, but the Object Map remains a read-only consumer of family
ownership facts.

The concrete read-only window family trace helper is documented in
`docs/contracts_docs/WINDOW_FAMILY_TRACE.md`. It consumes the `window` legend
without transferring window ownership away from GUI metadata and registries.

The concrete read-only action family trace helper is documented in
`docs/contracts_docs/ACTION_FAMILY_TRACE.md`. It consumes the `action` legend
without transferring action execution, permission policy, or runtime trigger
ownership away from their existing owners.

## Ownership Boundary

Core owns the common traceability contracts and canonical family descriptors.
Each family owner remains responsible for mutation of its own objects. The
future Object Map may read these descriptors, but it must remain read-only.
Runtime Manager remains read-only and snapshot-based. GUI remains shell,
intent, display, and local Qt object lifetime.

## Validation

Focused tests live in `tests/contracts_test/test_object_family_legends.py`.
