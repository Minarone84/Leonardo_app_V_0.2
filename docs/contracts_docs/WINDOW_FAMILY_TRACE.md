# Window Family Trace

Window family trace exposes static GUI window metadata as read-only traceable
object summaries and Object Map sections.

The helper lives in `leonardo.gui.metadata.window_trace`.

## Scope

The helper reads existing GUI metadata documents and builds shared traceability
contracts:

- `TraceableObjectRef`
- `TraceableObjectSummary`
- `TraceableRelationshipRef`
- `ObjectMapProviderDescriptor`
- `ObjectMapSection`
- `ObjectInterrogationReport`

It does not implement a live Object Map service, provider registry, Runtime
Manager section, GUI behavior, window layout, Qt widget construction, window
opening, action execution, metadata mutation, Download execution, Data Manager
behavior, Analysis Suite behavior, adapters, storage writers, or trading
behavior.

## Provider Descriptor

The window trace descriptor uses:

- `provider_id`: `gui.window.trace`
- `owner_domain`: `gui`
- `object_kinds`: `window`
- `family_ids`: `window`
- `relationship_types`: `contains_action`, `opens_window`
- `read_only`: `true`
- `mutation_forbidden`: `true`

The descriptor declares the read-only trace surface only. It is not a live
provider implementation.

## Window Summaries

Each summary is built from a `GuiMetadataDocument` loaded from static TOML
metadata. The object ID is the metadata `window_id` when present, otherwise the
metadata ID. The object kind is `window`, owner domain is `gui`, lifecycle status
is `defined`, and runtime/persistence classification is `static_metadata`.

Summary metadata preserves stable static fields such as:

- `metadata_id`
- `window_id`
- `object_name`
- `title`
- `label`
- `owner_area`
- `instance_policy`
- `settings_present`
- `action_ids`
- `region_ids`
- `table_ids`
- `report_ids`
- `metadata_ref`

## Relationships

Window trace creates static `contains_action` relationship references from a
window to the actions declared in that window's metadata. This does not
execute actions.

The Object Map section includes the existing `window` family legend and the
relevant static relationship definitions for `contains_action` and
`opens_window`.

The concrete read-only Action family trace helper is documented in
`docs/contracts_docs/ACTION_FAMILY_TRACE.md`.

## Interrogation

`interrogate_window_trace()` returns a read-only `ObjectInterrogationReport` for
one static window object. Missing objects are reported as blockers. The helper
does not query runtime window state.

## Validation

Focused tests live in `tests/gui_test/test_window_family_trace.py`.
