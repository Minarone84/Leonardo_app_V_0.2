# Leonardo V2 GUI Roadmap Metadata

`src/leonardo/gui/metadata/gui_roadmap.json` is the canonical machine-readable
GUI roadmap for Leonardo V2. It records GUI areas, suites, windows, actions,
major presentation objects, ownership boundaries, lifecycle ownership, shell
status, and AI-safe interaction metadata.

The roadmap is source metadata. It is not a runtime registry, widget factory,
domain executor, Object Map mutator, provider adapter, storage writer, or AI
agent implementation.

## Ownership Boundary

The roadmap enforces the No Shared Responsibility Rule for GUI planning:

- GUI owns presentation objects: windows, dialogs, menus, buttons, panels,
  tables, inputs, labels, local shell display state, and GUI action metadata.
- Core owns runtime foundation, registries, audit/action observation contracts,
  and lifecycle primitives.
- Domain suites are targets only in GUI metadata. A GUI object may point at a
  suite or module, but the reference does not transfer domain ownership to GUI.
- Runtime Manager remains generic and read-only.
- Planned windows are not treated as implemented windows.

## Relationship To TOML Metadata

Window TOML files under `src/leonardo/gui/metadata/windows/` remain the
declarative source for concrete window metadata. The roadmap references those
files for implemented and shell-only windows when a metadata document exists.

The roadmap adds cross-window planning information that individual TOML files do
not own: area/suite relationships, parent-child GUI object relationships,
future shell targets, AI-safe interaction policy, and explicit removed legacy
references.

## Traceability

Roadmap records use stable IDs for:

- `window_id`
- `object_id`
- `action_id`
- `suite_id`
- `area_id`

These IDs align with the GUI action observer where actions are already tracked.
New GUI phases that add or rename GUI surfaces must update the roadmap and the
focused roadmap tests in the same phase.

## AI-Agent Usage

Future AI helpers may use the roadmap to identify GUI objects and request safe
GUI interactions through approved GUI/action channels. Roadmap `ai_agent`
sections explicitly state whether a window or action is visible, referenceable,
requestable, clickable, read-only, or requires human confirmation.

AI helpers must not:

- mutate GUI metadata or widgets directly;
- call Core registries directly to simulate GUI workflows;
- call provider, storage, chart, analysis, trading, or domain services;
- treat shell-only or planned surfaces as operational implementations;
- bypass human confirmation for destructive, live, or future-domain behavior.

The default AI policy is metadata-reference-only and direct mutation is always
false.

## Maintenance Rule

Any phase that adds, removes, renames, or materially changes a GUI window,
action, shell surface, or planned target must update:

- `src/leonardo/gui/metadata/gui_roadmap.json`
- `src/leonardo/gui/metadata/gui_roadmap.schema.json` when the structure changes
- `tests/gui_test/test_gui_roadmap_metadata.py`

The roadmap must remain deterministic, hand-maintainable, and free of executable
callbacks or hidden domain control.
