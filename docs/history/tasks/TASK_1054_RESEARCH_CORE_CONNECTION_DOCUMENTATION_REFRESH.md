# Task 1054 — Research, Core, and Connection Documentation Refresh

## Task identity

```text
Task ID: 1054
Task name: Research, Core, and Connection Documentation Refresh
Standalone or workplan task: Standalone documentation task
Objective: Replace stale reset-era documentation with current implementation-backed operational documentation.
Implementation discretion: Documentation only; no production or test code changes.
```

## Starting evidence

Audited source package:

```text
Leo_V2_latest(28).zip
```

Embedded repository evidence:

```text
branch: main
HEAD: 1cb260566c9a7d0c6ce87bcb737d2d6b60ec2193
origin: https://github.com/Minarone84/Leonardo_app_V_0.2.git
index: empty
tracked working-tree state: accepted cumulative Research changes
```

## Scope

Updated current documentation for:

- Research Suite;
- Core runtime;
- Connection Suite and historical OHLCV workflow;
- repository README and documentation authority map.

Historical task records were not rewritten. They remain time-specific evidence.

## Source surfaces inspected

```text
src/leonardo/core/
src/leonardo/core/app.py
src/leonardo/connection/
src/leonardo/ohlcv/
src/leonardo/research/
src/leonardo/financial_tools/
src/leonardo/artifacts/
src/leonardo/gui/composition.py
src/leonardo/gui/runner.py
src/leonardo/gui/window_tracking.py
src/leonardo/gui/research/
src/leonardo/gui/presenters/
src/leonardo/gui/windows/
tests/core_test/
tests/connection_test/
tests/ohlcv_test/
tests/research_test/
tests/gui_test/
```

## Files changed

```text
README.md
docs/README.md
docs/core_docs/LIGHT_V2_RUNTIME.md
docs/connection_docs/CONNECTION_SUITE.md
docs/research_docs/RESEARCH_SUITE.md
docs/history/tasks/TASK_1054_RESEARCH_CORE_CONNECTION_DOCUMENTATION_REFRESH.md
```

## Key corrections

- Removed reset-baseline language claiming financial workflows were unfinished.
- Documented the production Research Suite and its accepted freeze status.
- Documented exact Research OHLCV refresh/reload and Artifact-lineage behavior.
- Documented Research Core task operations and long-lived window tracking.
- Documented Study style support versus missing application-wide appearance editing.
- Expanded Core documentation to match the actual composition root, CoreRunner,
  TaskManager, ProcessManager, registries, audit/error boundaries, and shutdown.
- Documented the implemented Bybit historical workflow and the deliberate
  presentation-only state of the top-level Connection Suite dashboard.
- Distinguished Connection provider semantics, Core connection summaries, and
  OHLCV persistence/validation authority.
- Added a documentation authority map separating current operational documents
  from historical task evidence.

## Persistence and runtime impact

```text
Production code: none
Persisted schema: none
Runtime behavior: none
User runtime data: untouched
```

## Finish line

```text
Current docs agree with current implementation and tests.
No code or test files changed.
All internal documentation links resolve.
Markdown files contain no stale reset-baseline claims for the documented areas.
Documentation package and hashes are produced for independent application.
```
