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
