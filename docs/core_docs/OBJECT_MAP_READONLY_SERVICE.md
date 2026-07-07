# Object Map Read-Only Service

`leonardo.core.object_map_service` provides the first Core Object Map
aggregation service. It builds `ObjectMapSnapshot` and `ObjectMapQueryReport`
values from explicit provider entries supplied by a caller.

## Scope

The service is read-only aggregation only. A provider entry binds one
`ObjectMapProviderDescriptor` to one callable that returns an `ObjectMapSection`.
The service stores the constructor-supplied provider list, invokes those
callables to build a snapshot, and filters the resulting snapshot through the
existing `ObjectMapQuery` fields.

The service does not discover providers, scan files, register global providers,
read source managers directly, repair malformed output, mutate source objects,
wire Runtime Manager, execute commands, or continue Download Manager behavior.

## Provider Inputs

Provider entries are explicit constructor inputs. Existing trace helpers can be
adapted by passing their descriptor builder result and a small callable around
their section builder. This keeps ownership with the source helper or object
family owner.

Core trace helpers that can be consumed this way include:

- `leonardo.core.task_operation_trace`
- `leonardo.core.runtime_registry_trace`
- `leonardo.core.process_connection_trace`
- `leonardo.core.audit_event_trace`

The static GUI window/action trace helpers can also be supplied explicitly when
a caller wants those metadata sections. The Core service module itself does not
import GUI modules.

## Snapshot Behavior

`ReadOnlyObjectMapService.build_snapshot()` returns an `ObjectMapSnapshot` with
provider descriptors, emitted sections, aggregate counts, and diagnostics. The
service preserves provider and section provenance through the existing
descriptor and section IDs.

Provider callable failures are captured as bounded, redacted snapshot errors so
other providers can still contribute sections. Failure diagnostics include the
exception type and a short sanitized message preview, but they do not include
tracebacks, raw payloads, or common secret/token/credential values. Duplicate
section IDs and duplicate object IDs are reported as warnings. Source sections
and summaries are not mutated or deduplicated by the service.

## Query Behavior

`ReadOnlyObjectMapService.query()` builds a fresh snapshot and filters it using
the fields currently present on `ObjectMapQuery`:

- `object_id`
- `object_kind`
- `family_id`
- `owner_domain`
- `provider_id`
- `relationship_type`

The query include flags control summaries, relationships, legends, relationship
definitions, and provider descriptors. Source/target-specific relationship
filters, section ID filters, and cross-provider interrogation routing require a
future contract extension and are intentionally not implemented here.

## Ownership Boundary

Object Map aggregation owns only the aggregation and query surface. TaskManager,
OperationRegistry, StateStore, AuditLog, ProcessManager, ConnectionRegistry,
GUI metadata helpers, and every future domain owner remain authoritative for
their own read models and mutation behavior.

Runtime Manager remains read-only. `RuntimeManagerBackend` can display a compact
`object_map_summary` when an app-level composition boundary injects a callable
that returns an `ObjectMapSnapshot`. Runtime Manager does not construct this
service, register providers, call provider entries directly, read source
managers for Object Map data, repair failed providers, retry providers, or
control Object Map output.

## Validation

Focused tests live in
`tests/core_test/test_object_map_readonly_service.py`.
