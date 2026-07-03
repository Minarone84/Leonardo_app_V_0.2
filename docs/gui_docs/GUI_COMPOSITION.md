# GUI Composition

GUI composition is the GUI-layer boundary that connects an existing Core
context to GUI-owned Qt windows.

The composition root receives a Core context object after Core has been
constructed elsewhere. It does not create `LeonardoApp`, start Core lifecycle,
create `QApplication`, or launch the application.

## Responsibilities

The GUI composition root:

- constructs the metadata-driven Main Window;
- injects a Runtime Manager window factory into the Main Window;
- passes `context.runtime_manager.snapshot` as a read-only snapshot provider;
- optionally loads changed-only GUI override documents before window creation;
- resolves production settings-inspector metadata through a GUI allowlist;
- installs opt-in top-level window tracking for composed windows.

The Runtime Manager snapshot provider is passed as a callable. It is not called
during Main Window construction.

## Persisted Overrides

Phase 003D allows composition to receive an optional
`GuiMetadataOverrideStore`. When supplied, composition loads persisted
changed-only JSON overrides for `main_window.window` and
`runtime_manager.window`, resolves effective profiles, and passes those
profiles into `LeonardoMainWindow` and `RuntimeManagerWindow`.

Corrupt, mismatched, or structurally invalid override files do not block normal
window construction. The affected window falls back to source metadata defaults,
and composition retains the override load result so diagnostics remain
inspectable.

Composition does not derive the override root from Core in this phase. The
store remains injected by the caller, and production app startup wiring remains
future work.

Phase 003F adds a persisted settings pilot for `main_window.window` and
`runtime_manager.window`. The pilot verifies that changed-only visual overrides
saved in an injected `GuiMetadataOverrideStore` are applied to the real windows
after composition construction and Runtime Manager handoff. Reset and reload
restore source defaults without mutating source TOML files.

The pilot does not create a production settings UI, persist session state,
hardcode production override paths, create application startup integration, or
add Runtime Manager control behavior.

Phase 003J lets composition provide the Main Window settings-inspector dialog
factory when a `GuiMetadataOverrideStore` is injected. Composition loads the
Main Window source metadata, creates the `GuiSettingsInspectorViewModel`, and
constructs `SettingsInspectorWindow` at the GUI boundary. Main Window receives
only the factory and owns local show, raise, and activate behavior.

Runtime Manager settings wiring, live refresh, session-state persistence,
global settings management, production override path derivation, and Core
ownership changes remain out of scope.

Phase 003L1 introduces a GUI settings profile provider at the composition
boundary. The provider is an explicit allowlist, not directory discovery. The
current production settings-inspector factory resolves only
`main_window.window` through this provider before constructing the existing
single-profile viewmodel and dialog.

`runtime_manager.window` remains a future candidate and is not exposed through
the provider in this phase. `dummy_metadata_test.window` remains a test-only
metadata surface and is not part of production settings inspection.

## Window Tracking

The GUI window tracking adapter observes explicitly provided top-level Qt
windows. It reports stable window identifiers and lifecycle state through the
Core window registry public API:

- registered window definition;
- opened;
- focused;
- close requested;
- closed.

The adapter never passes `QWidget`, `QMainWindow`, `QDialog`, or other Qt
objects to Core. Core receives only IDs and registry-safe metadata.

## Ownership Boundaries

Core owns runtime state, audit history, lifecycle state, and the window
registry.

GUI owns Qt widgets, menus, buttons, tables, dialogs, object lifetime, and local
interaction behavior.

Composition owns wiring between those layers. It does not own Core lifecycle,
domain behavior, business logic, task execution, process control, connections,
or persistence.

## Out Of Scope

This phase does not add:

- application startup entry point;
- `QApplication` creation;
- action tracking;
- operation tracking;
- Runtime Manager control actions;
- production settings manager;
- session-state persistence;
- Data Manager, Analysis Suite, financial tools, historical downloader,
  connection adapters, or trading behavior.
