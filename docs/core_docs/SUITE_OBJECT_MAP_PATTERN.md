# Suite Object Map Pattern

`leonardo.core.suite_boundary_trace` exposes suite boundary descriptors to the
read-only Object Map protocol.

This pattern converts explicit descriptor inputs into Object Map provider,
section, summary, and relationship contracts. It does not implement concrete
suites, suite runtime behavior, Runtime Manager suite summaries, GUI behavior,
provider/client behavior, Download Data execution, or a mutable suite registry.

## Scope

The helper consumes only explicit descriptor objects supplied by the caller:

- `AreaDescriptor`
- `SuiteDescriptor`
- `SuiteModuleDescriptor`
- `SuiteCommandDescriptor`
- `SuiteQueryDescriptor`

It does not scan files, inspect modules, import concrete suite packages, query
Runtime Manager, read provider clients, call Core runtime submission, create
tasks, create operations, or mutate descriptors.

## Provider Descriptor

`build_suite_boundary_trace_provider_descriptor()` returns an
`ObjectMapProviderDescriptor` with provider ID `core.suite_boundary.trace`.

The descriptor declares read-only support for these object kinds:

- `area`
- `suite`
- `suite_module`
- `suite_command`
- `suite_query`

The provider descriptor is static metadata. It does not register itself with
`ReadOnlyObjectMapService`. A future composition boundary may supply it through
an explicit `ObjectMapProviderEntry`.

## Summary Behavior

The helper exposes one `TraceableObjectSummary` per supplied descriptor.

Area summaries include safe descriptor fields such as area ID, area kind,
lifecycle status, version, suite ID, module IDs, command IDs, query IDs, object
family IDs, permissions, audit categories, docs, tests, warnings, and blockers.

Suite summaries include suite ID, lifecycle status, version, area IDs, module
IDs, supported command and query IDs, object family IDs, permissions, audit
categories, docs, tests, warnings, and blockers.

Module summaries include module ID, suite ID, area ID, lifecycle status, object
family IDs, command IDs, query IDs, permissions, audit categories, object map
section ID, docs, tests, warnings, and blockers.

Command summaries include command ID, suite ID, area ID, module ID, command
kind, required permission, operation/task expectations, cancellation policy,
audit category, schema refs, related GUI action IDs, object family IDs, allowed
callers, docs, tests, warnings, and blockers.

Query summaries include query ID, suite ID, area ID, module ID, query kind,
required permission, read model kind, schema refs, object family IDs, cache
policy, audit policy, allowed callers, docs, tests, warnings, and blockers.

Summaries do not include payloads, provider handles, client state, raw data, or
runtime execution state.

## Relationship Behavior

`suite_boundary_relationships_from_descriptors()` emits relationships only when
the referenced descriptor exists in the explicit inputs.

The helper uses existing relationship types:

- `references`
- `has_permission`

Descriptor relationships may connect suites to areas, areas to suites, areas to
modules, modules to commands and queries, commands or queries to their owning
module/area/suite, commands to referenced GUI action IDs, descriptors to object
family IDs, and commands/queries/descriptors to permission refs.

Missing referenced descriptor IDs are reported as section warnings. Missing
optional IDs do not produce synthetic target objects.

## Section Behavior

`build_suite_boundary_trace_section()` builds one `ObjectMapSection` with
section ID `core.suite_boundary`.

The section contains summaries, relationships, relationship definitions for
`references` and `has_permission`, aggregate counts, descriptor warnings, and
descriptor blockers.

Formal `ObjectFamilyLegend` values for `area`, `suite`, `suite_module`,
`suite_command`, and `suite_query` remain future work. The section reports that
future promotion as a warning rather than modifying family legends in this
phase.

## Interrogation

Object interrogation is not implemented in this pattern. Future interrogation
should remain read-only and should consume explicit descriptor inputs or Object
Map section material without introducing registry behavior.

## Ownership Boundary

Core owns Object Map aggregation and traceability vocabulary. Suite descriptors
own static suite-boundary metadata only. Future suites own their own domain
behavior.

Runtime Manager remains read-only and must not construct suite Object Map
providers, register providers, scan modules, or expose suite controls.

Download Data remains workflow/module metadata, not a top-level suite.

Provider/Connection remains infrastructure/capability metadata, not a suite.

## Validation

Focused tests live in
`tests/core_test/test_suite_boundary_object_map_pattern.py`.

The next phase should be:

`LEO-V2-POST-CORE-SUITE-OBJECT-MAP-PATTERN-AUDIT-001`
