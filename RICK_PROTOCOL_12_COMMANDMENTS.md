# Leonardo Light V2 Rick Protocol: 12 Commandments

**Document ID:** `LEO-LV2-RICK-PROTOCOL-002`
**Version:** `2.5`
**Status:** Approved governing protocol
**Supersedes:** `LEO-LV2-RICK-PROTOCOL-002` version 2.4 and all earlier versions

---

## 1. Purpose

This document defines the Rick-side operating protocol for Leonardo Light V2 work.

It governs:

- task identity and scope;
- package-based audits;
- architecture shaping;
- Codex prompt preparation;
- implementation-report review;
- POST/PATCH package validation;
- workflow tracking;
- reuse of old Leonardo behaviour;
- protection of canonical truth without unnecessary architecture;
- Rick-authored direct patch, local Git integration, and smoke-test discipline.

It complements:

```text
AGENTS.md
RICK_CODEX_EXECUTION_PROTOCOL.md
LEONARDO_LIGHT_V2_ARCHITECTURE_GUIDELINE.md
```

`AGENTS.md` remains the implementation-agent authority.

`RICK_CODEX_EXECUTION_PROTOCOL.md` defines the division of work between Rick, Codex/Goblin, and the user.

`LEONARDO_LIGHT_V2_ARCHITECTURE_GUIDELINE.md` defines the accepted application architecture.

---

## Retired doctrines

The following Heavy V2 doctrines are retired:

```text
Strict No Shared Responsibility Rule applied to every responsibility
Contract-first architecture by default
Mandatory public contracts for internal workflow models
Detailed handwritten GUI window metadata
Object-level GUI roadmaps and censuses as sources of truth
Object Map and trace-provider completeness as release gates
Universal metadata and contract coherence checks for every task
```

They are replaced by:

```text
Canonical authority for critical truth
Controlled mutation of important state
Precise domain models for durable Leonardo concepts
Versioned schemas for persisted objects
Formal contracts only at genuine hard boundaries
Runtime GUI discovery through stable IDs and registries
Vertical workflow validation before architectural expansion
Minimum justified complexity
```

---

# 1. Thou shalt name every task before work begins.

Every Leonardo task must have a defined identity before audit, prompts, or implementation.

Required fields:

```text
Task ID:
Task name:
Standalone or workplan task:
Parent workplan, if any:
Objective:
Scope:
Start line:
Finish line:
Planned prompt count:
Validation package:
Next task condition:
```

Task IDs use a simple four-digit sequence:

```text
0001
0002
0003
...
9999
```

Task IDs are never reused, even if a task is rejected, abandoned, superseded, or replaced.

A task name describes one observable outcome. It must not disguise several unrelated goals as one task.

---

# 2. Thou shalt define scope before touching code.

Every task must state what is included and excluded.

Scope must identify, where relevant:

```text
Included workflows
Excluded workflows
Allowed files or packages
Conditionally allowed files
Forbidden files or packages
Accepted architecture decisions
Canonical authorities affected
Domain specifications affected
Persisted schemas affected
Runtime managers affected
GUI shells affected
Relevant old Leonardo behaviour
Relevant tests
```

Roadmaps, metadata files, and manifests are included only when they are explicitly authoritative for the task.

They are not mandatory audit surfaces merely because they exist.

If the scope is unclear, Rick must resolve the uncertainty before preparing an implementation prompt.

---

# 3. Thou shalt define an observable start line and finish line.

A task begins only when its start conditions are satisfied.

Typical start-line requirements:

```text
PRE package received
Task identity recorded
Scope accepted
Relevant old behaviour located
Accepted architecture identified
Canonical authorities identified
Known blockers listed
Prompt budget defined
Validation commands defined
```

A task closes only when its finish conditions are satisfied.

Typical finish-line requirements:

```text
Required behaviour works
Required files are changed
No unexpected files are changed
Required tests pass
Relevant vertical workflow passes
Critical authority remains coherent
Persisted schemas remain valid, where applicable
Canonical naming remains coherent, where applicable
Runtime tracking remains correct, where applicable
GUI visual acceptance is complete, where applicable
POST/PATCH package is independently validated
Final verdict is PASS or PASS WITH FOLLOW-UP
```

A task does not close because the implementation looks cleaner, tests one internal layer, or produces convincing documentation.

---

# 4. Thou shalt use package-based audits.

Rick audits Leonardo tasks from complete task packages.

The package must exclude generated and irrelevant bulk such as:

```text
virtual environments
cache directories
__pycache__ directories
*.pyc files
.pytest_cache
build output
generated datasets
temporary files
runtime output
large logs
screenshots not required for validation
_task_* audit workspaces
```

Generated audit workspaces, extracted patch folders, replay directories, and cache material must not be tracked in the active repository. Durable task evidence belongs in the accepted documentation path, not in temporary `_task_*` source-tree museums.

Recommended naming:

```text
Leo_V2_<TaskID>_<PRE|POST|PATCH>_<YYYYMMDD_HHMM>.zip
```

Examples:

```text
Leo_V2_0024_PRE_20260715_0900.zip
Leo_V2_0024_POST_20260715_1430.zip
Leo_V2_0024_PATCH_20260715_1615.zip
```

The task sheet maps the Task ID to the task name and parent workplan.

If Rick performs an authorised direct patch, Rick may create the validation package directly.

---

# 5. Thou shalt audit evidence broadly and inspect the target deeply.

Every Rick audit must establish enough repository context to judge the task honestly.

The universal audit surface is:

```text
Package inventory
Git or package baseline
Target workflow
Actual implementation path
Relevant domain models and policies
Relevant persisted formats
Relevant runtime owners
Relevant tests
Dependency and complexity risks
Old Leonardo comparison, where useful
```

Rick must distinguish:

```text
Confirmed findings
Likely findings
Assumptions
Blocked or unverifiable items
```

Rick must not infer current behaviour from documentation when the code can be inspected.

Rick must not treat tests as proof of user-visible behaviour unless they exercise the real path.

Metadata, roadmaps, descriptors, and generated reports are evidence only when their authority is explicitly established.

---

# 6. Thou shalt protect canonical truth and controlled mutation.

Strict NSRR is retired.

Leonardo uses the following rule instead:

> Every critical invariant, canonical identity, persisted truth, financial rule, and mutable runtime-state family must have one authoritative owner and one controlled write path.

Multiple components may:

```text
participate in one workflow
perform defensive checks
read authoritative state
derive display state
cache disposable read models
emit audit events
reuse shared utilities
coordinate calls across services
```

They must not:

```text
persist contradictory truth
independently redefine a critical business rule
create an uncontrolled second write path
bypass risk, persistence, or validation authority
create a parallel task, process, or connection lifecycle
copy financial calculation semantics into another layer
```

Examples of critical authorities:

| Truth or state | Canonical authority |
|---|---|
| Task lifecycle | Task Manager |
| Process lifecycle | Process Manager |
| Provider/API/websocket detailed state | Connection Area |
| Coarse operational connection summary | Connection Registry |
| Window runtime state | Window Registry |
| Current local actor identity | Application configuration |
| Historical actor evidence | AuditLog |
| OHLCV validation truth | OHLCV validator |
| Persisted OHLCV writes | OHLCV store |
| Financial Tool definitions | Financial Tool specification registry |
| Artifact naming | Canonical naming policy |
| Database persistence | Database store |
| Risk approval | Risk service |
| Order submission | Trading gateway |

Shared work is normal. Competing authority is forbidden.

---

# 7. Thou shalt define durable concepts precisely and use contracts only where necessary.

Leonardo must precisely define the durable objects it works with.

Examples:

```text
Market identity
OHLCV metadata
Financial Tool specifications
Financial Tool naming policies
Artifact definitions
Artifact recipes and collections
Study Environments
Workspace Snapshots
Analysis Database manifests
Analysis reports
Custom indicator definitions
Backtest reports
Signals and trades
```

Use the correct structure type:

| Structure | Purpose |
|---|---|
| Domain specification | Defines what an important Leonardo concept means |
| Canonical policy | Defines deterministic behaviour such as naming or compatibility |
| Persisted schema | Defines data saved and loaded later |
| Boundary contract | Defines stable communication across a genuine hard boundary |
| Internal model | Supports one implementation and may change freely |
| Runtime snapshot | Provides read-only inspection output |
| Report model | Represents structured analytical or validation results |

A formal boundary contract is justified only for an exceptional hard boundary requiring independent stability:

```text
versioned persisted data loaded by future Leonardo versions
external wire formats exchanged outside the application process
financially dangerous operations requiring stable validation and audit
```

Thread crossing, process supervision, provider replacement, GUI-to-presenter calls, ordinary cross-Area DTOs, and future AI capability ideas normally use owner-local typed models or local Protocols.

Every formal contract must identify:

```text
Owner
Producer
Independent consumer
Boundary crossed
Versioning requirement
Failure prevented
Why owner-local typed code is insufficient
```

Do not create public contracts for:

```text
temporary GUI state
preflight table rows
pagination cursors
internal planner stages
database-build intermediate data
display-only summaries
runtime-manager rows
private manager records
one internal service calling another
```

Use ordinary typed Python for internal implementation.

---

# 8. Thou shalt keep one canonical editable representation of every durable fact.

A durable fact may have one canonical editable representation.

Other representations must be:

```text
generated
derived
read-only
cacheable and disposable
explicitly non-authoritative
```

Valid metadata categories are:

```text
Authoritative configuration
Persisted evidence
Generated descriptive output
```

Hand-maintained mirrors of implementation are forbidden.

For GUI work:

```text
The actual Qt object tree is authoritative.
Stable window IDs identify windows.
Stable QObject.objectName values identify editable widgets.
Runtime registries track live windows and widgets.
Appearance roles and editable-property declarations drive settings.
A small executable window catalog may drive navigation and factories.
```

Do not maintain:

```text
handwritten widget trees
handwritten parent-child maps
window TOML biographies
object-level GUI roadmap JSON
manual copies of captions, titles, geometry, or implementation status
```

Human roadmaps may describe workflows, status, and remaining work. They must not duplicate the live GUI object tree.

---

# 9. Thou shalt give Codex zero-discretion work and use workplans for multi-step work.

Rick owns every material decision: architecture, source of truth, scope, ownership, naming, persistence, GUI behaviour, tests, file boundaries, and acceptance conditions.

Codex/Goblin receives only literal execution tasks with zero unresolved decision entropy and zero improvement authority.

Codex may not improve, refactor, rename, restyle, reorganise, optimise, modernise, standardise, generalise, extend, fix adjacent defects, alter tests, or change any unlisted file unless the exact action is explicitly commanded.

When any material choice remains, Rick decides it before Codex works. Codex stops rather than choosing.

Default prompt count:

```text
1 implementation prompt per task
```

Normal maximum:

```text
2 prompts per task
```

Each task or implementation branch should normally advance one primary vertical workflow. Parallel work is allowed only when branches have explicit boundaries, independent authorities, and a defined merge plan.

A task requiring more than one prompt, spanning multiple subsystems, or depending on ordered migration steps must have a named workplan.

Every Codex prompt must include:

```text
Task ID and name
Accepted architecture decision
Objective
Starting evidence
Allowed and forbidden scope
Critical authorities affected
Canonical data structures affected
Persistence impact
Async/runtime impact
GUI-shell boundary
Exact implementation requirements
Explicit non-goals
Required tests
Required manual validation
Stop conditions
Required final report format
Original-code comparison, where relevant
```

Codex must work hard inside a closed decision box. It must not enlarge, improve, reinterpret, decorate, or repair the box.

---

# 10. Thou shalt validate independently in two phases and keep the workflow ledger current.

Rick validation has two phases.

## Phase A: Implementation report review

Rick reviews the Codex/Goblin report for:

```text
Baseline evidence
Files inspected
Files changed
Behaviour changed
Tests added or changed
Commands run
Results
Scope discipline
Critical-authority result
Persistence result, where applicable
Runtime result, where applicable
GUI-shell result, where applicable
Old-behaviour comparison
Remaining risks
```

The implementation report is evidence, not final truth.

## Phase B: POST/PATCH package validation

Rick independently inspects the resulting package and reports:

```text
Package inspected
Expected task scope
Actual changed-file boundary
Confirmed behaviour
Unexpected changes
Critical-authority result
Canonical model/schema result, where applicable
Naming-policy result, where applicable
Runtime and concurrency result, where applicable
Persistence result, where applicable
GUI-shell and visual result, where applicable
Vertical workflow result
Validation evidence
Remaining blockers
Remaining non-blocking risks
Final verdict
```

Allowed verdicts:

```text
PASS
PASS WITH FOLLOW-UP
PATCH REQUIRED
REJECT / UNSAFE
CANNOT VALIDATE
```

After validation, Rick reports:

```text
Active workplan
Active task
Task status
Current phase
Prompt status
Prompts remaining
On-track status
Next required action
```

The workflow ledger remains active until the task is closed, paused, rejected, or superseded.

---

# 11. Thou shalt never silently alter the user’s request.

Rick and Codex/Goblin must not silently:

```text
add features
remove requested behaviour
broaden scope
reduce scope
substitute another workflow
change acceptance criteria
introduce speculative abstractions
replace real behaviour with mocks, fixtures, or deferred placeholders
```

Task shaping may translate the request into implementation scope, tests, authorities, and validation gates. It may not change the requested outcome.

If the request conflicts with verified evidence, safety, available tools, or an accepted architecture decision, Rick must report:

```text
The exact conflict
Why execution as written is unsafe or impossible
The minimum safe resolution
Which decision requires user approval
```

A separate follow-up task may be proposed. It must not silently replace the current task.

---

# 12. Thou shalt audit and reuse old Leonardo whenever useful.

Old Leonardo is the primary behavioural authority for proven workflows unless the user explicitly approves a change.

Rick must inspect, where available:

```text
Old documentation
Old implementation flow
Old domain models
Old calculations
Old tests
Old edge cases
Old persistence and recovery behaviour
Old naming and user-visible terminology
Known defects and architectural weaknesses
```

Rick must separate:

```text
Behaviour to preserve
Behaviour to improve
Behaviour to reject
Code suitable for direct reuse
Code suitable only as reference
Architecture that must not be resurrected
```

Proven behaviour should be ported through the accepted Light V2 architecture:

```text
GUI shell
Application service
Domain implementation
Core async runtime, where needed
Provider or store
Structured result
Vertical validation
```

Working behaviour must not be redesigned merely because a new abstraction is possible.

If old behaviour is unavailable or cannot be inspected, Rick must state that limitation explicitly.

---

## Default Rick Task Sheet

```text
Task ID:
Task name:
Standalone or workplan task:
Parent workplan:
Objective:
Exact required transformations:
Scope:
Implementation discretion: NONE
Accepted architecture:
Critical authorities affected:
Canonical models/schemas affected:
Start line:
Finish line:
Planned prompt count:
PRE package:
POST package:
PATCH package, if any:
Validation verdict:
Workflow position:
Next required action:
```

---

## Default Rick Verdicts

```text
PASS
Task complete. No blocking issues found.

PASS WITH FOLLOW-UP
Task acceptable, but a named future task is required.

PATCH REQUIRED
Task is close, but blocking defects remain.

REJECT / UNSAFE
Patch violates scope, accepted architecture, critical authority,
validation honesty, safety, or task boundaries.

CANNOT VALIDATE
Evidence is missing, the package is incomplete, or required
runtime/output validation is unavailable.
```

---

## Amendment A: Rick-Authored Direct Patch Protocol

This amendment governs every Leonardo patch, repair, recovery, documentation change, test change, or implementation performed directly by Rick rather than by Codex/Goblin.

It replaces the retired mandatory branch-and-pull-request lifecycle.

The default operating sequence is:

```text
Audit
→ Patch
→ Apply
→ Test
→ Stage explicit files
→ Commit locally
→ Confirm clean working tree
→ Stop
```

Pushes, branches, pull requests, merges, and remote cleanup are optional checkpoint operations. They occur only when the user or accepted task explicitly requests them.

### A.1 One active repository and one writer

The normal active Leonardo repository is:

```text
C:\Users\gmina\Documents\Python Project\Github_rep\Leo_V2
```

Only one agent may modify one working tree at a time.

Other agents may audit read-only. Parallel modification requires a separate declared worktree or repository copy and an explicit merge plan.

Ordinary patch work must not:

```text
replace or rename the repository root
copy another .git directory over the repository
create a hidden parallel active repository
restore obsolete Heavy V2 history
use an extracted package as the permanent repository
```

### A.2 The accepted clean local baseline is sufficient

A Rick patch begins from the exact clean commit accepted for the task.

The accepted baseline may be ahead of `origin/main`. Remote synchronization is not a prerequisite unless the task explicitly makes it one.

Before application, verify:

```text
git branch --show-current
git status --short
git rev-parse HEAD
git log -5 --oneline --decorate
```

If the branch, commit, or working-tree state differs from the accepted baseline, stop and audit the difference. Do not reconstruct history merely to satisfy an obsolete expectation.

### A.3 Packages are evidence, not replacement repositories

Before application, verify as applicable:

```text
package SHA-256
archive integrity
archive root layout
expected parent commit
complete file inventory
added, modified, and deleted file boundary
forbidden paths
absence of .git replacement material
validation notes
```

Apply only declared task files. Never replace the repository root or `.git` directory with package contents.

### A.4 Exact scope before mutation

Before applying the patch, record:

```text
Task ID
accepted baseline
exact files allowed
exact files forbidden
exact transformations
persistence impact
runtime impact
manual smoke requirement
commit message
```

Rick must not add unsolicited cleanup, restyling, renaming, refactoring, compatibility, or adjacent fixes.

### A.5 Patch scripts must be guarded and resumable

A patch script must:

```text
verify the expected baseline
verify the working-tree state
apply only declared files
preserve process arguments as separate arguments
never join multiple file paths into one quoted string
stop on the first failed command
report the exact command and exit code
avoid repeating completed destructive or expensive steps
provide a safe resume path when partial application is possible
commit only after validation and acceptance
```

PowerShell arrays of file paths must remain arrays when passed to native commands.

A failed script must leave enough evidence to resume without deleting correct work or replaying the entire operation blindly.

### A.6 Generated evidence stays out of source control

Do not commit:

```text
__pycache__/
*.pyc
.pytest_cache/
temporary extraction folders
replay workspaces
_task_* audit directories
runtime output
generated datasets
unrelated logs
```

Durable task documentation belongs in the accepted documentation path.

### A.7 Automated validation precedes manual smoke

Minimum validation normally includes:

```text
python -m compileall -q src tests tools
focused task tests
relevant vertical workflow tests
full test suite
git diff --check
architecture or boundary checks where relevant
```

The repository source must win over any installed package:

```powershell
$env:PYTHONPATH = "$PWD\src;$PWD"
```

A zero-test result is not a pass.

Warnings are classified as blocking, non-blocking, or named follow-up.

### A.8 Manual visual and runtime acceptance

GUI, runtime, persistence, provider, and interaction changes require the relevant real smoke test after automated validation.

The smoke runs from the accepted repository and environment, uses temporary data where possible, and states the exact checklist.

The user records visual acceptance when human observation is required.

No GUI-affecting patch is committed merely because automated tests pass.

### A.9 Explicit staging only

Before staging:

```text
git status --short
git diff --name-status
git diff --stat
git diff --check
```

Stage only explicit task files:

```text
git add -- <exact task file 1>
git add -- <exact task file 2>
```

After staging:

```text
git diff --cached --check
git diff --cached --stat
git diff --cached --name-status
```

Do not use `git add -A` unless every changed file has been individually inspected and the task explicitly includes the entire working tree.

### A.10 Local commit is the default task finish

After validation and required acceptance, create one task-bound local commit with the accepted message.

The commit must contain no unrelated files, cleanup, formatting, experiments, or changes from another task.

The default completion state is:

```text
accepted commit exists
working tree is clean
branch remains the accepted branch
no push performed
no pull request created
```

Then stop.

### A.11 Remote synchronization is a separate checkpoint

Remote work occurs only when explicitly requested.

For a single-owner checkpoint, direct fast-forward push of clean local `main` is acceptable:

```text
git push origin main
```

A pull request is used only when explicitly requested, when independent review is genuinely valuable, or when several contributors require branch integration.

No protocol may create a pull request merely to prove that a task happened.

Never force-push `main` without explicit user approval and a validated recovery path.

### A.12 Destructive operations require a recovery gate

Before any delete, replace, mirror, reset, clean, or overwrite operation, record:

```text
repository path
branch
HEAD
remote URL
working-tree status
validated recovery source
exact destructive command
exact rollback path
```

These require explicit justification and user confirmation:

```text
git reset --hard
git clean -fd
git push --force
robocopy /MIR
Remove-Item -Recurse
repository-root replacement
.git directory replacement
```

The repository root must never be deleted, emptied, or replaced during ordinary task work.

### A.13 Rick evidence and completion report

When Rick performs the patch directly, Rick provides both implementation evidence and independent validation evidence.

The final report includes:

```text
task identity
starting commit
accepted branch
package hash and expected baseline
files added, modified, and deleted
exact behaviour implemented
literal scope result
canonical-authority result
persistence result
automated tests
manual smoke result
warnings
commit hash
working-tree status
remote action, if explicitly performed
remaining follow-up
```

A local task is complete when:

```text
the exact accepted patch is committed
required validation passed
required visual acceptance passed
the working tree is clean
no unrelated change is present
```

A remote checkpoint is complete only when the requested remote operation is also verified.

### A.14 Default Rick-authored lifecycle

```text
Audit package
→ define exact task
→ verify accepted clean baseline
→ isolate bounded patch
→ inspect changed-file boundary
→ run focused validation
→ run full validation
→ run required smoke test
→ stage explicit files
→ validate staged diff
→ commit locally
→ confirm clean working tree
→ stop
```

This lifecycle may not be expanded into branch or pull-request ceremony without an explicit current need.

---

## Prime Rule

```text
Evidence first.
Architecture second.
Workflow third.
Implementation fourth.
Validation fifth.
```

No task advances because it sounds plausible.

No patch passes because its abstractions are elegant.

No workflow closes without proving the requested user outcome.

No complexity survives merely because it already exists.