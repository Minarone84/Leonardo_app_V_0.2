# Leonardo Light V2 Fast-Track Reset Workplan

**Document ID:** `LEO-LV2-FAST-TRACK-RESET-WORKPLAN-001`
**Status:** In progress
**Architecture authority:** `LEONARDO_LIGHT_V2_ARCHITECTURE_GUIDELINE.md`
**Governance authority:** `AGENTS.md`, `RICK_PROTOCOL_12_COMMANDMENTS.md`, `RICK_CODEX_EXECUTION_PROTOCOL.md`

## Objective

Remove the Heavy V2 contract, trace, Object Map, and GUI metadata bureaucracy while preserving reusable Core execution and GUI shell behaviour. Freeze a lean Light V2 baseline before resuming product development.

## Execution model

```text
Rick performs the reset tasks directly unless the user changes execution ownership.
The user approves product and visual outcomes.
Package-based validation remains mandatory.
```

## Task sequence

### 0046 — Freeze Light baseline and install Governance 2.3 FINAL

**Status:** PASS / completed

**Execution owner:** Rick
**Objective:** Reconstruct the accepted Task 0011 baseline, create the Light reset branch, install Governance 2.3 FINAL, record the starting inventory, and produce a clean frozen baseline.

### 0047 — Remove Heavy V2 machinery and repair Core + GUI

**Status:** PASS / completed

**Execution owner:** Rick
**Objective:** Delete Contract Registry, Object Map, trace providers, unnecessary contract families, GUI metadata/TOMLs/roadmap, and repair active Core and GUI consumers using ordinary typed Python and direct runtime snapshots.

**Keep:**

```text
AuditEventV1
MarketId
OHLCVSidecarV1
CoreRunner
TaskManager
ProcessManager
ConnectionRegistry
WindowRegistry
AuditLog
ErrorRouter
Qt runner
theme system
existing useful GUI shells and layouts
stable objectName and action IDs
```

**Do not build:**

```text
replacement Contract Registry
replacement Object Map
replacement GUI metadata system
compatibility facades for abandoned internal APIs
speculative plugin or AI contract frameworks
```

### 0048 — Validate and freeze the Light V2 baseline

**Status:** Ready to start

**Execution owner:** Rick
**Objective:** Prove startup, shutdown, async jobs, progress, cancellation, failure, runtime tracking, audit, Runtime Manager snapshots, multi-window responsiveness, GUI smoke, and complete absence of retired Heavy V2 imports.

## Superseded workflow

The earlier cautious cleanup sequence is superseded before implementation. Previously assigned task IDs remain retired and are not reused.

## Prime reset rule

```text
Archive exists
→ delete known bureaucracy
→ repair active consumers
→ validate real surviving behaviour
→ freeze the lean baseline
```
