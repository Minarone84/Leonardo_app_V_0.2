# Leonardo Light V2 — Agent Instructions

**Document ID:** `LEO-LV2-AGENTS-003`
**Version:** `3.0`
**Status:** Approved implementation-agent authority
**Primary execution surface:** Codex CLI in PowerShell
**Supersedes:** `LEO-LV2-AGENTS-002` version 2.4 and all earlier versions

---

## 1. Purpose and authority

This file defines how Codex/Goblin must work inside the Leonardo Light V2 repository.

It is intentionally self-contained because Codex CLI automatically loads the applicable `AGENTS.md` project instructions. Do not require Codex to read Rick-only governance documents unless the current task explicitly names one.

Operational precedence for implementation work is:

```text
1. Explicit current user instruction
2. Accepted current Rick task card / amendment
3. Applicable AGENTS.md
4. Explicitly named canonical specifications or persisted schemas
5. Current implementation and tests
```

If two applicable authorities conflict materially, stop and report the exact conflict. Do not invent a compromise.

`Rick Protocol` and `Rick–Codex Execution Protocol` govern Rick's workflow and handoff discipline. They are not automatic implementation inputs.

The word `Codex` includes `Goblin` unless a task states otherwise.

---

## 2. Zero-discretion execution law

Codex has **zero product, architecture, cleanup, or improvement authority** inside a Leonardo task.

The accepted task card is a closed execution specification. Codex may inspect, implement, validate, render, package, and report. It may not decide what would be better.

Unless the task explicitly authorizes the exact action, Codex must not:

```text
improve
refactor
clean up
modernise
optimise
simplify
standardise
reorganise
rename
restyle
redesign
extend
generalise
add compatibility
fix adjacent defects
change tests to prefer another behaviour
replace an accepted implementation with a preferred alternative
```

Mechanical syntax choices are allowed only when they are behaviorally and structurally equivalent, follow the nearby accepted pattern, and do not alter scope, architecture, ownership, APIs, persistence, naming, GUI behaviour, validation meaning, tests, or acceptance criteria.

If more than one materially different valid implementation remains possible, stop and report the missing decision.

No file outside the explicit allowed boundary may be changed. If the boundary is insufficient, stop.

---

## 3. Leonardo architectural baseline

Leonardo Light V2 is a modular desktop financial research, analysis, backtesting, and trading application.

The permanent high-level model is:

```text
LeonardoApp
    composition root
        ↓
Core runtime + Areas + Stores/Adapters + GUI services
```

Core owns shared domain-neutral infrastructure:

```text
application lifecycle
background execution
task lifecycle
progress and cancellation
process lifecycle
generic runtime tracking
coarse connection summaries
window tracking
audit and operational logging
error routing
safe shutdown
```

Areas own financial and business meaning.

The GUI is a replaceable shell. It owns interaction and presentation, not persistence, financial calculations, validation truth, database construction, analysis logic, trading logic, or task lifecycle.

Long-running work uses the shared Core. Trivial GUI operations remain direct.

---

## 4. Canonical authority rule

Strict NSRR is retired.

The governing rule is:

> Every critical invariant, canonical identity, persisted truth, financial rule, and mutable runtime-state family has one authoritative owner and one controlled write path.

Multiple components may participate in a workflow, validate defensively, derive display state, cache disposable read models, emit audit evidence, or coordinate calls. They must not create competing truth or a second mutation authority.

Representative authorities include:

| Truth/state | Authority |
|---|---|
| Application lifecycle | `LeonardoApp` |
| Task lifecycle | `TaskManager` |
| Process lifecycle | `ProcessManager` |
| Detailed provider/API/websocket state | Connection Area |
| Window state | `WindowRegistry` |
| Historical audit evidence | `AuditLog` |
| Canonical market identity | `MarketId` authority |
| OHLCV persistence | OHLCV Store |
| OHLCV validity | OHLCV Validator |
| Financial Tool definitions | Financial Tools specification authority |
| Artifact naming | Canonical naming policy |
| Database persistence | Database Store |
| Risk approval | Risk Service |
| Order execution | Trading Gateway |

The current task identifies the exact affected authorities.

---

## 5. Durable concepts and internal models

Use the correct vocabulary.

### Domain specification
Defines an important Leonardo concept and its semantics.

### Canonical policy
Defines deterministic rules such as naming, compatibility, or normalization.

### Persisted schema
Defines data that is saved now and must be loaded later. Persisted schemas are explicit, validated, and versioned.

### Boundary contract
Used only for a genuine hard boundary requiring independent stability, such as a durable persisted format, an external wire format, or a financially dangerous operation.

### Internal model
Implementation-local structured data that may change with its owner.

### Runtime snapshot
Read-only projection from an authoritative manager.

### Report model
Structured analytical, validation, or execution evidence.

Do not promote disposable internal dataclasses into public contracts merely because they are structured.

Do not create registries that merely describe other registries.

---

## 6. Data Manager durable semantics

Preserve the accepted Data Manager model unless the task explicitly changes it.

```text
Accepted OHLCV
├──→ Database Seed
│    └──→ Database base revision
│
└──→ Financial Tool calculations
     ├──→ managed Artifact
     └──→ portable Recipe definitions / Recipe Collections

Saved Artifacts / Artifact Collections
        ↓ explicit reviewed import
Database revisions
        ↓
Analysis
```

Permanent rules:

- Recipes are global definitions of how to create results.
- Managed Artifacts are market/source-specific persisted calculated objects.
- Artifacts are not runtime-owned by portable Recipes.
- Recipe Collections and Artifact Collections are independent persistence families.
- A Database owns fixed explicitly reviewed imported membership.
- Importing an Artifact Collection does not make the Database follow later Collection edits.
- Database membership changes only through explicit reviewed Database operations.
- Raw current-dataset Construct inputs are Open/High/Low/Close only; raw Volume is prohibited.
- Reconciliation/currentness is read-only truth discovery. Persistent updates remain explicit user actions.
- Existing per-tool update policies remain mathematical authority unless a task explicitly changes them.

Do not create parallel Recipe, Artifact, Collection, Database, currentness, or update authorities.

---

## 7. GUI policy

The GUI owns:

```text
windows
widgets
layouts
selection state
input collection
display formatting
enabled/disabled state
dialogs
progress presentation
visual errors/reports
appearance
navigation
focus
```

The GUI does not own:

```text
provider communication
background task lifecycle
financial calculations
OHLCV validation truth
persistence rules
database construction
analysis algorithms
backtest mathematics
risk decisions
order execution
```

Background code must not mutate Qt widgets directly. Use the existing queued GUI update path.

The live Qt object tree is the GUI source of truth. Do not recreate handwritten widget trees or metadata mirrors.

Stable `objectName`, action IDs, and appearance roles are appropriate for meaningful controls.

Subjective visual redesign belongs only in tasks that explicitly authorize it.

---

## 8. Execution protocol: Audit → Literal Update → Validation

Every implementation task follows:

```text
Audit
→ Literal Update
→ Validation
→ Audit package/report
→ Stop
```

### Audit
Before editing:

- verify baseline and index state;
- verify pre-edit hashes when provided;
- inspect relevant code/tests;
- identify the actual workflow and authorities;
- confirm allowed/forbidden boundaries;
- record additional findings without fixing them.

Audit findings do not create permission to change additional files.

### Literal Update
During implementation:

- implement only the accepted transformations;
- preserve behavior outside scope;
- preserve durable semantics and compatibility unless explicitly changed;
- do not add dependencies without approval;
- do not perform unrelated formatting;
- do not alter protected tests unless explicitly authorized.

### Validation
After implementation:

- run the exact focused gates from the task;
- run relevant vertical tests;
- run broader regression gates required by the task;
- run `compileall` where required;
- run `git diff --check`;
- verify the index remains empty unless the task explicitly authorizes staging;
- inspect the complete task diff against the accepted baseline/package.

A zero-test run is not a pass.

Do not weaken tests, suppress failures, or claim success without evidence.

---

## 9. Baseline modes

Leonardo supports two legitimate task baselines.

### Clean commit baseline
The task begins from a clean accepted commit. Git diff may serve as the primary byte boundary.

### Accepted cumulative dirty baseline
The working tree intentionally contains accepted prior work while `HEAD` remains unchanged.

In this mode:

- an empty working tree is **not** required;
- the Git index must remain empty unless explicitly authorized;
- task PRE hashes/package bytes define the task boundary;
- do not infer task scope solely from `git diff HEAD`;
- do not reset, clean, restore, or stash accepted cumulative work.

The current task card states which baseline applies.

---

## 10. One writer per working tree

Only one agent may modify one working tree at a time.

Other agents may audit read-only. Parallel modification requires a separate declared worktree/repository copy and an explicit merge plan.

Never allow two implementation agents to edit the same checkout concurrently.

---

## 11. Git safety

Read-only Git commands are allowed when useful:

```text
git status
git diff
git diff --stat
git log
git branch
git remote -v
git show
git ls-files
```

Do not run Git write/destructive commands unless the current task explicitly authorizes that exact operation:

```text
git add
git commit
git push
git pull
git reset
git clean
git checkout
git restore
git merge
git rebase
git stash
branch/tag deletion
remote modification
```

Default implementation-agent finish is **not** commit.

The normal finish is:

```text
validated bounded implementation
→ bounded audit package/report
→ Rick audit
→ user native/visual smoke where required
→ later integration only when explicitly authorized
```

Never hide or overwrite user changes.

---

## 12. Audit-package authority

All files intended for Leonardo audit must be created under:

```text
C:\Users\gmina\Documents\Python Project\Github_rep\Leo_V2_Task_Packages
```

This includes:

```text
PRE / POST / PATCH / R1 ZIPs
inventory files
SHA-256 sidecars
validation reports
render/screenshots
evidence folders
scope reports
comparison evidence
```

Do not place audit evidence inside the active `Leo_V2` repository.

If Codex sandboxing blocks writes to `Leo_V2_Task_Packages`, request the narrow filesystem permission required for that exact directory. Do not work around the restriction by writing audit evidence into source control.

Generated audit material is never application source.

---

## 13. Runtime and user-data protection

Do not modify or delete user/runtime data unless the task explicitly requires that exact mutation.

Typical protected runtime/persistence families include:

```text
historical_data/
data_manager/
research_notebooks/
study_environments/
workspace_snapshots/
```

Tests must use temporary/injected roots where appropriate.

Do not package runtime persistence merely because it is present in the cumulative dirty tree.

---

## 14. Dependencies and environment

Supported Leonardo environment currently uses:

```text
Python 3.12.12
PySide6 6.10.2
```

Repository source must win over installed packages:

```powershell
$env:PYTHONPATH = "$PWD\src;$PWD"
```

Do not add or upgrade third-party dependencies without explicit approval.

Do not modify the user's Python environment unless requested.

Do not install globally.

---

## 15. Security and secrets

Do not print, copy, package, or commit secrets.

Do not inspect credential files unless the task explicitly requires it.

Do not add network calls outside scope.

Do not send project data to external services.

Trading, credential, and OpenAI runtime integration require their own explicit security and confirmation policies.

---

## 16. Error handling

- Fail clearly.
- Include actionable context.
- Validate at boundaries.
- Preserve one authoritative decision for each canonical fact.
- Do not silently continue after critical failure.
- Do not swallow broad exceptions except at a final routing boundary.
- Do not hide broken state with fallback behavior not authorized by the task.

A refusal backed by correct evidence is a valid implementation result.

---

## 17. Stop conditions

Stop and report when:

```text
the baseline is wrong
an expected PRE hash differs
the index is unexpectedly non-empty
an authorized new path already exists unexpectedly
an allowed-file boundary is insufficient
the task conflicts with accepted architecture
a canonical authority is unclear
a durable data meaning is unresolved
a hidden persistence change is required
a forbidden file/package must change
a required dependency/runtime is unavailable
a protected test proves the frozen design cannot work
visual validation required by the task cannot be produced
a materially different implementation choice remains
an unsolicited improvement appears desirable but is not authorized
```

Do not improvise around stop conditions.

---

## 18. Final report

Every implementation report must include:

### Baseline
Branch, HEAD, origin, environment, index, applicable hash gates.

### Files
Files inspected, changed, added, deleted.

### Implementation
Exact instructed behavior implemented and behavior intentionally preserved.

### Authority/persistence
Affected canonical authorities, persisted schemas, runtime boundaries, and explicit statement of any mutation behavior.

### Validation
Commands, exact counts, failures, warnings, renders/manual evidence where required.

### Original-code/package comparison
Exact task delta, unrelated changes found, compatibility intentionally preserved or changed.

### Audit output
Exact `Leo_V2_Task_Packages` evidence/package paths.

### Status
Exactly one of the task-defined final statuses, normally:

```text
READY FOR RICK PACKAGE AUDIT
BLOCKED
```

Do not claim final product acceptance. Rick audits independently and the user performs native/visual acceptance where required.

---

## 19. What done means

Codex implementation is done only when:

- instructions were followed literally;
- no unsolicited changes were made;
- the exact accepted scope is implemented;
- relevant tests and validation pass or a blocker is reported;
- the index remains in the required state;
- the task delta is bounded and reviewable;
- audit evidence is written only to `Leo_V2_Task_Packages`;
- no unauthorized Git integration occurred;
- the task is ready for independent Rick audit.

The permanent engineering rule is:

> Build Leonardo using the simplest architecture that preserves correctness, asynchronous safety, runtime visibility, durable evidence, canonical authority over critical truth, and explicit user control over persistent mutation.
