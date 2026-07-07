# Action Family Trace

Action family trace exposes static GUI action metadata and static GUI action
definitions as read-only traceable object summaries and Object Map sections.

The helper lives in `leonardo.gui.metadata.action_trace`.

## Scope

The helper reads existing GUI window metadata documents and
`TRACKED_GUI_ACTION_DEFINITIONS`. It builds shared traceability contracts:

- `TraceableObjectRef`
- `TraceableObjectSummary`
- `TraceableRelationshipRef`
- `ObjectMapProviderDescriptor`
- `ObjectMapSection`
- `ObjectInterrogationReport`

It does not implement a live Object Map service, provider registry, Runtime
Manager section, GUI behavior, Qt widget construction, window opening, action
execution, callback dispatch, Core command submission, metadata mutation,
Download execution, Data Manager behavior, Analysis Suite behavior, adapters,
storage writers, or trading behavior.

## Provider Descriptor

The action trace descriptor uses:

- `provider_id`: `gui.action.trace`
- `owner_domain`: `gui`
- `object_kinds`: `action`
- `family_ids`: `action`
- `relationship_types`: `contains_action`, `has_permission`, `triggers`
- `read_only`: `true`
- `mutation_forbidden`: `true`

The descriptor declares the read-only trace surface only. It is not a live
provider implementation.

## Action Summaries

Each summary is built from static GUI metadata and static action definitions.
The object ID is the stable `action_id`. The object kind is `action`, owner
domain is `gui`, lifecycle status is `defined`, and runtime/persistence
classification is `static_metadata`.

Summary metadata preserves stable fields such as:

- `action_id`
- `window_id`
- `metadata_id`
- `metadata_ref`
- `action_kind`
- `label`
- `required_permissions`
- `is_placeholder`
- `implementation_status`
- `sources`

Actions declared only in static action definitions are also summarized. They may
omit `window_id` and metadata references when no source metadata document owns
them yet.

## Relationships

Action trace creates static relationship references only:

- `contains_action` from an action summary back to its declaring window when a
  static window relationship exists;
- `has_permission` from an action summary to required permission references
  when static action definitions declare permissions.

The Object Map section includes existing relationship definitions for
`contains_action`, `has_permission`, and `triggers`. It does not emit
`creates_operation` relationships because static GUI action metadata does not
represent operation creation.

## Interrogation

`interrogate_action_trace()` returns a read-only `ObjectInterrogationReport` for
one static action object. Missing actions are reported as blockers. The helper
does not query runtime action state or execute actions.

## Validation

Focused tests live in `tests/gui_test/test_action_family_trace.py`.
