# Leonardo Light V2

Leonardo Light V2 is a modular desktop application for historical market data,
financial research, persisted analytical artifacts, and future analysis and
trading workflows.

The application is a modular monolith with:

- one `LeonardoApp` composition root;
- one shared Core runtime for long-running and concurrent work;
- Area-owned business logic;
- a replaceable PySide6 GUI shell;
- canonical persisted data and lineage;
- runtime tracking for tasks, processes, connections, windows, actions, and
  audit evidence.

This document describes the current repository state as of **2026-08-02**. Old
task reports remain useful historical evidence, but they are not a substitute
for the current source, tests, and the authoritative documents listed below.

## Active governance

```text
LEONARDO_LIGHT_V2_ARCHITECTURE_GUIDELINE.md
AGENTS.md
RICK_PROTOCOL_12_COMMANDMENTS.md
RICK_CODEX_EXECUTION_PROTOCOL.md
```

These authorities supersede the retired Heavy V2 contract-first, Object Map,
strict NSRR, handwritten GUI metadata, and duplicated-runtime doctrines.

The governing architectural rule is:

> Every critical truth, invariant, canonical identity, persisted object family,
> financial decision, and mutable runtime-state family has one canonical
> authority and one controlled write path.

## Current authoritative documentation

- [Documentation authority map](docs/README.md)
- [Core runtime](docs/core_docs/LIGHT_V2_RUNTIME.md)
- [Connection Suite and historical download](docs/connection_docs/CONNECTION_SUITE.md)
- [Research Suite](docs/research_docs/RESEARCH_SUITE.md)
- [GUI shell](docs/gui_docs/LIGHT_V2_GUI_SHELL.md)
- [GUI theme system](docs/gui_docs/GUI_THEME_SYSTEM.md)
- [Application GUI smoke](docs/gui_docs/LIGHT_V2_APPLICATION_SMOKE.md)

## Current product status

### Core

Implemented and shared application-wide:

- application startup and ordered shutdown;
- background asyncio event loop;
- bounded worker pool for blocking operations;
- canonical task lifecycle, progress, cancellation, results, and failures;
- controlled external-process lifecycle;
- coarse connection and websocket-channel summaries;
- window lifecycle tracking;
- application-wide action registration where justified;
- operational logging;
- in-memory and optional JSONL audit evidence;
- structured error routing;
- Runtime Manager snapshots.

### Connection and OHLCV

Implemented:

- owner-local provider registry;
- Bybit v5 historical REST provider;
- historical capability discovery;
- provider-session lifecycle and coarse runtime connection tracking;
- historical OHLCV preflight;
- new, update-latest, and custom-range downloads;
- multi-timeframe batch execution;
- bounded retries, rate-limit handling, progress, and cancellation;
- canonical OHLCV persistence;
- validation, repair, sidecar reconstruction, and controlled deletion;
- cache invalidation after accepted OHLCV mutations.

The top-level Connection Suite window remains a presentation shell. The real
historical workflow is exposed through Historical Download Manager and OHLCV
Maintenance. Private accounts, credentials, websocket feeds, live market data,
and trading connections are not implemented.

### Research

The restored production Research Suite is implementation-complete and accepted
for freeze, with the separate Data Manager user-acceptance gate deferred.

Implemented:

- accepted-OHLCV catalog and full dataset loading;
- resident chart slices and refill;
- up to eight chart slots;
- Scroll 4 and Fit 8 workspace modes;
- chart create, close, detach, dock, and slot compaction;
- mixed-timeframe UTC navigation and Pan Anchor;
- Autoscale and Go To controls;
- 25 Research Financial Tools;
- Study Apply, Edit, Save, style, visibility, and removal;
- canonical Recipe and calculated Artifact persistence;
- Study Environments;
- Workspace Snapshots;
- Research Notebooks and annotations;
- clear-and-reuse Research lifecycle;
- Core task integration;
- long-lived Research window tracking.

`dynamic_binning` remains globally available to the Financial Tools domain for
future Analysis use, but is deliberately excluded from the Research catalog,
Research Study workflow, and Study Environments.

### Data Manager, Analysis, and Trading

- Data Manager domain/application services exist and share the canonical
  Artifact and OHLCV authorities. Its final user workflow and acceptance are
  handled separately from the Research freeze.
- Analysis and Trading currently expose GUI suite shells only. Their domain
  workflows are not complete.

## Runtime data

The following repository-root directories are permanent user data:

```text
historical_data/
research_notebooks/
study_environments/
workspace_snapshots/
```

They must never be deleted, reset, normalized, or treated as disposable test
output. Tests must use temporary or injected roots.

## Developer launch

Activate the project environment, then run:

```powershell
conda activate py312_Leo
cd "C:\Users\gmina\Documents\Python Project\Github_rep\Leo_V2"
$env:PYTHONPATH = "$PWD\src;$PWD"
python tools/dev_launch_gui.py
```

The supported project environment is currently:

```text
Python 3.12.12
PySide6 6.10.2
```

## Validation

Compile source, tests, and tools:

```powershell
python -m compileall -q src tests tools
```

Focused suites:

```powershell
python -m pytest -q tests/core_test
python -m pytest -q tests/connection_test tests/ohlcv_test
python -m pytest -q tests/research_test
python -m pytest -q tests/gui_test
```

Full suite:

```powershell
python -m pytest -q
```

GUI tests require PySide6. A zero-test run is not a pass.
