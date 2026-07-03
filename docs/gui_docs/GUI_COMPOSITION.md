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
- installs opt-in top-level window tracking for composed windows.

The Runtime Manager snapshot provider is passed as a callable. It is not called
during Main Window construction.

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
- production override persistence;
- Data Manager, Analysis Suite, financial tools, historical downloader,
  connection adapters, or trading behavior.
