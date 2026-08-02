# Task 0046 — Freeze Light Baseline and Install Governance

## Task identity

```text
Task ID: 0046
Task name: Freeze Light baseline and install Governance 2.3 FINAL
Standalone or workplan task: Workplan task
Parent workplan: Leonardo Light V2 Fast-Track Reset
Execution owner: Rick
Decision entropy: LOW
Implementation agent: Rick-authorised direct patch
Architecture status: ACCEPTED
Durable data impact: NONE
```

## Objective

Create a clean Light V2 reset baseline from the verified Task 0011 source state, install the approved Governance 2.3 FINAL documents, preserve the donor archive and Git history, and record the exact starting inventory before architecture removal begins.

## Accepted baseline

```text
Donor archive: Leo_V2_0011_FINAL_GUI_AUDIT_20260709_2231(2).zip
Canonical Git commit: fb3be75b7ed462ccae9900d27d597db3e9aecf3b
Reset branch: light-v2-reset
```

The donor archive and commit were compared byte-for-byte after excluding generated cache files:

```text
Files compared: 258
Files only in archive: 0
Files only in Git checkout: 0
Content mismatches: 0
```

## Included scope

- preserve the untouched donor archive;
- reconstruct commit `fb3be75` from verified Git history;
- create branch `light-v2-reset`;
- install Governance 2.3 FINAL;
- remove the superseded `RICK_PROTOCOL_10_COMMANDMENTS.md` file;
- record the reset workplan and baseline inventory;
- run baseline non-GUI validation;
- produce a committed, clean baseline and validation package.

## Excluded scope

- no contract deletion;
- no Object Map deletion;
- no trace-provider deletion;
- no GUI metadata deletion;
- no Core or GUI implementation changes;
- no Download Data work;
- no dependency changes;
- no formatting or documentation cleanup outside the governance baseline.

## Canonical authorities affected

```text
Architecture governance: Governance 2.3 FINAL
Application behaviour: unchanged
Persisted schemas: unchanged
Runtime managers: unchanged
GUI shells: unchanged
```

## Starting inventory

### Source

```text
Tracked baseline files: 258
Python source files: 96
Python source lines: 42,766
Test modules: 88
Test lines: 27,891
Documentation files before Task 0046: 50
```

### Major source packages

| Package | Python files | Lines |
|---|---:|---:|
| `src/leonardo/contracts` | 25 | 12,503 |
| `src/leonardo/core` | 28 | 14,938 |
| `src/leonardo/gui` | 40 | 14,792 |
| `src/leonardo/connection` | 2 | 532 |

### Known Task 0047 removal targets

```text
Contract Registry and compatibility machinery
Object Map and Object Map contracts
Core trace-provider modules
strict NSRR-era boundary descriptors
public runtime-state contract families
GUI metadata package
11 window TOMLs
GUI roadmap JSON and schema
metadata loaders, resolver and override store
metadata-driven Settings Inspector
metadata-only tests and documentation
production dummy metadata windows/data
```

This inventory is descriptive evidence only. It is not an authority that must be maintained after cleanup.

## Start line

```text
Task 0011 donor archive available
Governance 2.3 FINAL available
Git history containing fb3be75 available
Workplan approved
Direct Rick execution explicitly authorised
```

## Finish line

```text
Task 0011 archive verified against fb3be75
light-v2-reset branch created
Governance 2.3 FINAL installed
old 10-commandment file removed
reset workplan recorded
baseline inventory recorded
baseline non-GUI tests pass
compile validation passes
no product code changed
branch committed
working tree clean
POST package and hash produced
```

## Validation baseline

```text
Contracts + Core: 636 passed
Full GUI suite: not executed in Rick environment because PySide6 is unavailable
GUI code changes: none
```

GUI validation remains a Task 0048 acceptance gate. Task 0046 changes governance and baseline records only.

## Next task condition

Task 0047 begins only from the clean committed `light-v2-reset` branch created by this task.
