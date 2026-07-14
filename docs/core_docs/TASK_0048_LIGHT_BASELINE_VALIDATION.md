# Task 0048 — Validate and Freeze the Light V2 Baseline

## Task identity

```text
Task ID: 0048
Task name: Validate and freeze the Light V2 baseline
Standalone or workplan task: Workplan task
Parent workplan: Leonardo Light V2 Fast-Track Reset
Execution owner: Rick
Decision entropy: LOW
Implementation agent: Rick-authorised direct patch
Architecture status: FROZEN FOR TASK
Durable data impact: NONE — retained schemas are unchanged
```

## Objective

Prove the lean Light V2 runtime and GUI shell baseline after the Heavy V2
amputation, repair only integration defects that block the accepted baseline,
and freeze the result before vertical product development resumes.

## Starting evidence

```text
PRE package: Leo_V2_0048_PRE_20260713_1257.zip
Branch: light-v2-reset
HEAD: 6913aa62b695dfb5302315b9e0b67768478b357b
Working tree evidence: clean
Task 0046: PASS
Task 0047: PASS
```

The PRE package SHA-256 matched its supplied record.

## Validation scope

- application startup and ordered shutdown;
- shared background runtime startup and shutdown;
- task progress, completion, cancellation and failure;
- process launch, polling, termination and forced-shutdown escalation;
- coarse connection and websocket-channel tracking;
- window and action tracking;
- structured audit persistence and runtime snapshots;
- operational logging;
- Runtime Manager direct manager snapshots;
- Main Window and Suite shell construction;
- multi-window tracking and responsiveness;
- retained theme loading and application;
- absence of retired Heavy V2 architecture;
- complete surviving test suite.

## Confirmed integration repair

The Task 0047 baseline had structured audit logging but no operational logging
implementation. Task 0048 added one shared standard-library `leonardo` logger at
the application composition root. It uses the host logging configuration when
present and installs a simple console configuration only when no host handler
exists.

Task and process lifecycle evidence was also completed without introducing a
new registry or contract family:

```text
task.submitted
task.cancel_requested
task.cancelled
task.completed
task.failed
process.started
process.termination_requested
process.terminated
process.completed
process.failed
```

`TaskManager` and `ProcessManager` remain the canonical mutable owners. Audit
records are historical evidence only.

Process shutdown now:

1. requests normal termination;
2. waits for settlement within the supplied timeout;
3. escalates remaining processes to forced termination;
4. raises a timeout if a managed process still cannot settle.

## Explicitly unchanged

- no GUI geometry, layout, font, object ID or action ID changed;
- no provider, Download Data, storage, Financial Tool, chart, analysis,
  backtest, risk or trading behaviour was added;
- no new dependency was added;
- `AuditEventV1`, `MarketId` and `OHLCVSidecarV1` were not changed;
- no replacement contract, Object Map, trace or GUI metadata system was added.

## Validation result

Rick environment:

```text
Full available suite: 27 passed, 1 skipped
Skipped module: PySide6 window smoke because PySide6 is unavailable here
Python compileall: PASS
Real subprocess launch/termination smoke: PASS
Retired-architecture source scan: PASS
Import-resolution scan: PASS
Git diff check: PASS
```

User environment evidence:

```text
Environment: py312_Leo with PySide6
Task 0047 installation: PASS
Local application/GUI operation reported working by the user
GUI source in Task 0048: unchanged
```

The existing PySide6 test module constructs the Main Window, Runtime Manager,
Connection, Research, Data Manager, Analysis, Trading and Download shells,
opens several windows, processes Qt events, verifies window tracking, renders a
direct Runtime Manager snapshot and applies the theme.

## Finish-line verdict

```text
Application lifecycle: PASS
Background runtime: PASS
Task lifecycle: PASS
Process lifecycle: PASS
Connection/window/action tracking: PASS
Operational logging: PASS after bounded repair
Structured audit: PASS
Runtime Manager direct snapshots: PASS
GUI shell/static gates: PASS
User local GUI report: PASS
Retired Heavy V2 absence: PASS
Task 0048: PASS
Fast-track reset workplan: COMPLETE
```

## Next condition

The Light V2 reset baseline is frozen. Future work must resume as named vertical
product workflows under Governance 2.3 FINAL. Heavy V2 remains donor evidence,
not architecture authority.
