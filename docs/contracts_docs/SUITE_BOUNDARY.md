# Suite Boundary Contracts

`leonardo.contracts.suite_boundary` defines pure read-only descriptors for
future Leonardo areas, suites, modules, commands, and queries.

This phase creates vocabulary only. It does not implement concrete suites,
provider/client behavior, Runtime Manager suite summaries, Object Map suite
providers, Download Data behavior, GUI features, or a mutable suite registry.

## Terminology

An area is the generic architecture term.

A suite is a large user-facing product area such as Research Suite, Data
Manager Suite, Analysis Suite, or Trading Suite.

Download Data is a future workflow/module, not a top-level suite yet. It may
later belong under a Data Manager or Data Acquisition area after the
provider/session boundary is defined.

Provider/Connection is shared infrastructure, not a suite. Provider and
connection components provide capabilities that future suites may depend on,
but they do not become user-facing suites by name alone.

## Contract Shapes

`AreaDescriptor` describes any major architectural area, including suites,
infrastructure boundaries, workflows, modules, and capabilities.

`SuiteDescriptor` describes a large user-facing suite. It identifies its
modules, supported command and query IDs, object families, permissions,
documentation, tests, warnings, and blockers.

`SuiteModuleDescriptor` describes a coherent functional slice inside a suite or
area. A module must reference at least one suite or area owner. Modules do not
own runtime execution, GUI widgets, provider registration, or service startup.

`SuiteCommandDescriptor` describes a command capability. It is not a runtime
command instance. Runtime command execution still uses
`CoreRuntimeCommand` and `CoreRuntimeBridge` when a future command is routed
through Core.

`SuiteQueryDescriptor` describes a read/query capability. Cheap local read
model queries may later exist outside the Core runtime bridge. Expensive,
permission-sensitive, or cross-boundary queries may later use an explicit query
boundary. This descriptor does not run a query.

## Ownership Model

Core owns runtime truth, lifecycle, task supervision, operation lifecycle,
state, audit, permissions, runtime inspection, Object Map aggregation, and
Core runtime command/query envelopes.

Suites may later own domain services, domain read models, suite/module
descriptors, suite command/query descriptors, suite object families, suite
Object Map provider helpers, suite audit categories, and suite permission
requirements.

Suites must not own:

- Core runtime startup or shutdown;
- TaskManager;
- OperationRegistry;
- StateStore;
- AuditLog;
- RuntimeManagerBackend;
- ReadOnlyObjectMapService aggregation;
- GUI widgets;
- provider/client transport unless explicitly scoped;
- storage writers outside an approved storage boundary;
- global permission policy.

## Command And Query Policy

Command descriptors are static capability declarations. They may reference GUI
action IDs, object family IDs, object references, schema refs, and required
permissions, but those references do not transfer ownership.

Mutating, long-running, task-backed, or Core-routed command descriptors must
declare that they create operations. The descriptor does not create the
operation itself.

Query descriptors are static read capability declarations. They describe read
model kind, cache policy, audit policy, object families, allowed callers, and
schema refs. They do not read state or call services.

## Permission Naming Policy

Permission references use established area namespaces such as `download`,
`research`, `data_manager`, `analysis`, `trading`, `connection`, `runtime`,
and `audit`.

Descriptors must not mint dynamic suite-prefixed permission strings. Suite
identity belongs in descriptor fields and runtime metadata, not in ad hoc
permission namespaces.

## Audit Requirements

Future suite commands and permission-sensitive queries should emit bounded
audit facts with stable IDs:

- suite ID;
- area ID;
- module ID;
- command or query ID;
- window ID and action ID when GUI-originated;
- operation ID and task ID when runtime-backed;
- actor ID and session ID;
- required permission;
- correlation ID;
- object references.

Audit facts must not contain secrets, provider tokens, credentials, raw
provider payloads, raw dataframes, large market data payloads, or client
handles.

## Future Boundaries

Object Map provider pattern remains future work. The suite boundary contracts
do not create provider entries, register providers, scan modules, discover
suites, query source managers, or mutate mapped objects.

Runtime Manager suite summary remains future work. Runtime Manager remains
read-only and must not become a suite controller.

No mutable SuiteRegistry exists in this phase. Future registry or composition
work must be explicitly scoped and must not introduce import-time registration
or automatic filesystem/module scanning.

## Validation

Focused tests live in
`tests/contracts_test/test_suite_boundary_contracts.py`.

## Next Phase

If this contract phase is accepted, the next phase should be:

`LEO-V2-POST-CORE-SUITE-BOUNDARY-CONTRACTS-AUDIT-001`

Object Map suite provider pattern work should wait until after that audit is
accepted.
