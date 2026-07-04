# GUI Metadata Management

GUI metadata management is a declarative layer for describing GUI profiles
without constructing widgets or executing behavior.

Metadata describes source defaults for one window, dialog, or report profile:

- stable metadata identity;
- metadata kind and schema version;
- title and label defaults;
- geometry, display, and style defaults;
- action, region, and widget identity references;
- table and report descriptors;
- safe settings exposure paths.

Metadata does not define callbacks, Python code, executable expressions,
business logic, Core mutations, persistence workflows, data loading, async
behavior, network behavior, or domain behavior.

## Source Defaults

Source metadata is loaded from TOML with standard library TOML reading. Source
metadata is the default profile.

## Dummy Metadata Test Window

Phase 001B adds `dummy_metadata_test.window` as the first metadata-only dummy
window. The dummy metadata is a test surface only. No PyQt window, Main Window
metadata, or Runtime Manager metadata exists in this phase.

The dummy window validates that layout regions, actions, widgets, tables,
structured reports, and safe settings exposure can be described before the Main
Window and Runtime Manager pilots.

## Dummy Override And Reset Validation

Phase 001C validates override and reset behavior against the dummy metadata
file. User overrides remain changed-only records, and reset removes override
entries instead of writing metadata defaults back into override data.

The resolver reports stale override paths and invalid override values without
making them effective. Settings exposure defines which profile values are
user-customizable. No production override file persistence, PyQt dummy window,
settings inspector, Main Window metadata, or Runtime Manager metadata exists in
this phase.

## Dummy Qt Metadata Consumer

Phase 001D adds a test-only PySide6 dummy window that consumes the effective
`dummy_metadata_test.window` profile. The window uses metadata-resolved titles,
action labels, widget identities, and table column labels to build a local GUI
surface.

The dummy window has no Core behavior and does not represent the Main Window or
Runtime Manager. Metadata still describes the surface; Python and Qt code own
widget construction and local dummy button behavior. No settings inspector,
production override persistence, Main Window metadata, or Runtime Manager
metadata exists in this phase.

## Dummy Settings Inspector

Phase 001E adds a dummy-only settings inspector for
`dummy_metadata_test.window`. The inspector reads metadata-declared settings
exposure, displays only safe exposed settings, previews local presentation
changes, and saves changed values into an in-memory changed-only override
document.

Reset removes override entries instead of writing metadata defaults into
override data. No production override persistence, final settings manager, Main
Window customization, or Runtime Manager customization exists in this phase.

## Main Window Metadata Pilot

Phase 001F adds `main_window.window` as the first metadata-only profile for the
real Leonardo application shell identity. The profile defines shell identity,
layout regions, descriptive action IDs, style defaults, geometry defaults, and
safe settings exposure.

This phase does not create or wire a Main Window class. It does not create
Runtime Manager metadata, open Runtime Manager, or add production override
persistence.

## Main Window Shell Consumer

Phase 001G adds a minimal PySide6 `LeonardoMainWindow` shell that consumes the
effective `main_window.window` profile. The shell applies metadata-derived
title, object name, style defaults, and menu action labels.

The shell actions are local and inert except for local close behavior. Runtime
Manager, Core behavior, full application startup, production override
persistence, and the final settings manager are not wired in this phase.

## Runtime Manager Metadata Pilot

Phase 001H adds `runtime_manager.window` as a metadata-only profile for a
future read-only Runtime Manager inspection view. The profile defines
descriptive identity, geometry, style, region, action, diagnostic table,
structured report, and safe visual settings defaults.

This phase does not create or wire a Runtime Manager view. It does not call
`RuntimeManagerBackend`, does not wire the Main Window to open Runtime Manager,
does not add full application startup, and does not add production override
persistence or the final settings manager.

## Runtime Manager View Consumer

Phase 001I adds a minimal read-only PySide6 Runtime Manager view that consumes
the effective `runtime_manager.window` profile. The view applies metadata
identity and presentation defaults, builds metadata-defined action buttons and
tables, and renders snapshot rows from an injected read-only snapshot provider
or backend.

Refresh reads only from the configured snapshot provider and updates local UI
state. The view has no task, process, connection, action execution, or Core
mutation controls. Main Window wiring, full application startup, production
override persistence, and the final settings manager are not added in this
phase.

## Main Window Runtime Manager Handoff

Phase 001J wires the metadata-driven Main Window shell to open Runtime Manager
through a GUI-only injected factory or read-only snapshot provider boundary.
The Main Window retains and reuses the local Runtime Manager window reference
so the view is not garbage-collected after handoff.

Runtime Manager remains read-only when opened from the Main Window. This phase
does not add full application startup, Core window tracking, registry
integration, Core mutation controls, production override persistence, or the
final settings manager.

## GUI Composition And Window Tracking

Phase 002B adds a GUI-layer composition root and a minimal top-level window
tracking adapter. The composition root receives an existing Core context,
constructs the metadata-driven Main Window, injects a Runtime Manager factory,
and passes the Core Runtime Manager snapshot method as a read-only provider.

Runtime Manager remains read-only. Core window tracking receives stable window
IDs and registry-safe lifecycle state only; Qt widgets remain owned by the GUI
layer and are never stored in Core. Application startup and production override
persistence remain future work.

## GUI Override Store

Phase 003B adds a pure Python GUI override store for durable user preference
overrides. The store is rooted at an injected path and writes one JSON file per
metadata profile:

```text
<metadata_id>.override.json
```

The JSON payload contains the override store schema version, metadata ID,
updated timestamp, and changed-only override values. It does not store source
metadata defaults, session state, Qt state, runtime snapshots, comments, source
metadata hashes, or application version metadata.

Reset keeps the changed-only contract. Resetting a field or section removes
override entries. Resetting the full profile deletes the override file. Saving
an empty override document also deletes the file. Missing override files load
as empty override documents.

Corrupt, mismatched, or structurally invalid override files return diagnostics
and an empty override document. Loading does not auto-delete or auto-repair
invalid files. Unsafe metadata IDs are rejected before any file path is
resolved.

The override store does not mutate source TOML metadata. It does not import Qt,
GUI windows, or Core services. Composition, Main Window, Runtime Manager,
production settings inspector integration, and session-state persistence remain
future phases.

## Composition Override Consumption

Phase 003D lets the GUI composition root optionally consume a
`GuiMetadataOverrideStore`. When a store is supplied, composition loads
changed-only JSON overrides for the Main Window and Runtime Manager, resolves
effective profiles, and passes those profiles into the window constructors.

Corrupt, mismatched, or structurally invalid override files fall back to source
metadata defaults and retain diagnostics on the composition root. Source TOML
metadata remains default truth and is not modified.

This phase does not add a production settings manager, session-state
persistence, application startup wiring, Runtime Manager controls, action
tracking, or operation tracking.

## Persisted Settings Pilot

Phase 003F verifies the persisted visual settings path for `main_window.window`
and `runtime_manager.window`. The pilot saves changed-only `style.font_size`
overrides through `GuiMetadataOverrideStore`, resolves them through
`GuiCompositionRoot`, and proves that the real Main Window and Runtime Manager
consume the effective profiles.

Reset remains changed-only. Resetting a field removes the stored override, and
resetting a profile deletes the override file. Reloading through composition
then restores source metadata defaults without modifying source TOML files.

This pilot does not add a production settings inspector, persist session state,
derive production override paths, wire application startup, add Runtime Manager
controls, or change Core behavior.

## Production Settings Viewmodel

Phase 003H adds a non-Qt production settings inspector viewmodel for
metadata-exposed GUI preferences. The viewmodel reads `settings` declarations
from a source metadata document, exposes rows with default, effective, and
override values, tracks local unsaved edits, validates candidate override
values through the metadata resolver, and persists changed-only overrides
through `GuiMetadataOverrideStore`.

The viewmodel supports save, reset field, reset section, and reset profile
operations without writing metadata defaults into override files. Reset removes
override entries or deletes the override file through existing override-store
semantics.

This phase does not create a Qt settings dialog, wire Main Window or Runtime
Manager actions, add live refresh, persist session state, mutate source TOML
metadata, derive production override paths, or change Core behavior.

## Production Qt Settings Inspector UI Pilot

Phase 003I adds a standalone PySide6 settings inspector dialog for production
metadata settings inspection. The dialog receives an injected
`GuiSettingsInspectorViewModel`, lists metadata-declared settings rows, exposes
field diagnostics, and delegates local edit, save, reset field, reset section,
and reset profile behavior to the viewmodel.

The dialog does not construct Core services, derive production override paths,
or duplicate metadata resolver and override-store ownership. It remains generic
for one metadata profile and can be tested independently of application
startup.

This phase does not wire Main Window or Runtime Manager actions, add live
refresh for open windows, persist session state, mutate source TOML metadata,
create a global settings manager, or change Core behavior.

## Main Window Settings Inspector Wiring

Phase 003J wires the existing Main Window settings action to the production
settings inspector through an injected dialog factory. The Main Window owns only
the shell action handler, retained dialog reference, and local show, raise, and
activate behavior.

Settings metadata loading, resolver use, override-store access, viewmodel
construction, parsing, diagnostics, save, and reset policy remain outside Main
Window. GUI composition may assemble the real dialog factory when it already
receives an injected `GuiMetadataOverrideStore`.

This phase does not wire Runtime Manager settings actions, add live refresh for
open windows, persist session state, mutate source TOML metadata, derive
production override paths in Main Window, create a global settings manager, or
change Core behavior.

## Settings Profile Provider

Phase 003L1 adds a GUI-layer settings profile provider for production settings
inspection. The provider exposes an explicit allowlist of inspectable metadata
profiles instead of scanning the metadata directory.

Phase 003M3 extends the provider allowlist to include `main_window.window` and
`runtime_manager.window`. Runtime Manager exposure is provider-only: no Runtime
Manager settings UI, Runtime Manager settings action, Runtime Manager
self-entry, profile selector, composition behavior change, or Core ownership is
added. Main Window settings behavior remains Main Window-only.

`dummy_metadata_test.window` remains test-only and must not be surfaced by the
production provider. The settings inspector dialog and viewmodel remain
single-profile components assembled by GUI composition.

This phase does not add a profile selector UI, Runtime Manager settings
inspection, live refresh for open windows, session persistence, source TOML
mutation, production override path derivation, or a global settings manager.

## Main Window Settings Apply Changes

Phase 003T1 adds a narrow live-apply path for saved Main Window settings. The
Settings Inspector receives an injected apply callback. `Apply Changes`
persists changed-only overrides through the existing viewmodel and then passes
the resolved effective profile to the callback so the currently open Main
Window can update safe visual settings.

Closing the Settings Inspector applies saved-but-not-yet-applied changes once.
Dirty unsaved edits are not silently saved on close. Live apply is limited to
`main_window.window` and safe visual fields such as `style.font_size`.

Runtime Manager settings remain provider-only. This phase does not add a
selector, multi-profile inspector, Runtime Manager settings UI, source TOML
mutation, session-state persistence, Core changes, runner changes, app-entry
changes, or production path-policy changes.

## User Overrides

User overrides are changed-only documents. They contain only profile paths that
differ from source metadata defaults.

Reset removes override entries. Reset does not write default values into the
override document.

## Session State

Session state is represented separately from persistent preferences. A session
value may affect an effective profile, but it is not part of the changed-only
override document.

## Effective Profiles

The resolver produces an effective profile by applying source defaults, then
changed-only user overrides, then optional session state. Each resolved value
can report whether it came from metadata defaults, a user override, session
state, missing state, or invalid state.

## Structured Diagnostics

The loader and resolver report structured issues for invalid metadata and
override data, including stale override paths, invalid override values,
forbidden executable metadata fields, duplicate IDs, and invalid settings
exposure paths.

## Runtime Boundary

The metadata package is pure Python and has no PyQt/PySide dependency. Qt code
may consume effective profiles outside the metadata package to construct
widgets and wire local UI behavior. Core remains the owner of runtime truth. The
metadata resolver does not call Core services, mutate Core registries, execute
actions, or create GUI windows.
