# Leonardo Light V2 Rick Protocol: 12 Commandments

**Document ID:** `LEO-LV2-RICK-PROTOCOL-002`
**Version:** `2.4`
**Status:** Approved governing protocol
**Supersedes:** `LEO-LV2-RICK-PROTOCOL-002` version 2.3 and all earlier versions

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
- Rick-authored direct patch, Git integration, and smoke-test discipline.

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
build output
generated datasets
temporary files
runtime output
large logs
screenshots not required for validation
```

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

# 9. Thou shalt give Codex bounded work and use workplans for multi-step work.

Rick owns architecture shaping, source-of-truth selection, task decomposition, and acceptance conditions.

Codex receives implementation tasks whose unresolved decision entropy has already been reduced.

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

Codex must work hard inside a clear decision box. It must not enlarge the box through speculative abstraction.

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
Scope:
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

It does not replace the Codex execution protocol. Codex-authored work continues to follow `AGENTS.md`, `RICK_CODEX_EXECUTION_PROTOCOL.md`, the accepted task prompt, the Codex implementation report, and Rick's independent POST/PATCH audit.

When Rick performs the patch directly, the procedure below is mandatory.

### A.1 One active repository

The only active Leonardo repository is:

```text
C:\Users\gmina\Documents\Python Project\Github_rep\Leo_V2
```

Ordinary patch work must not:

```text
replace or rename the repository root
copy another .git directory over the repository
create a parallel active Leonardo repository
restore obsolete Heavy V2 history
use an extracted package as the permanent working repository
```

Temporary recovery or extraction directories may exist only for a declared operation and must be removed after validation.

### A.2 Main is stable and protected

`main` is the stable integration branch. Rick must not perform ordinary implementation directly on `main`.

Before a Rick-authored patch begins:

```text
git status
git branch --show-current
git log -5 --oneline --decorate
git fetch --prune origin
git switch main
git pull --ff-only origin main
```

The working tree must be clean before a task branch is created.

If `main` cannot be updated by fast-forward, work stops until the divergence is understood. A destructive reset is not an acceptable shortcut.

### A.3 Every Rick patch receives its own branch

Branch naming must identify Rick as execution owner and identify the task:

```text
rick/task-<TaskID>-<short-description>
```

Example:

```text
rick/task-1003-ohlcv-maintenance
```

Protocol-only amendments may use:

```text
rick/protocol-<short-description>
```

The branch must begin from the current verified `main`. Unrelated work must never be continued silently on an old branch.

### A.4 Packages are audited before application

A Rick-authored patch package must be treated as evidence, not as trusted replacement content.

Before application, Rick must verify:

```text
package SHA-256
archive integrity
archive root layout
input baseline or expected parent commit
complete file inventory
added, modified, and deleted file boundary
forbidden files and paths
presence or absence of .git
expected task documentation and validation evidence
```

A cumulative package must not be copied wholesale when a smaller task delta can be isolated.

Patch application must copy only declared task files into the active repository. It must not replace the repository root or its `.git` directory.

### A.5 Scope is verified before staging

Before staging, Rick must inspect:

```text
git status --short
git diff --name-status
git diff --stat
git diff --check
```

The changed-file boundary must match the accepted task scope. Unexpected files stop the commit.

Rick must not default to:

```text
git add -A
```

unless the complete working tree has been explicitly inspected and confirmed as belonging to the task.

Normal staging uses explicit paths:

```text
git add -- <task files>
```

Generated datasets, caches, bytecode, virtual environments, temporary extraction folders, runtime output, and unrelated audit debris must not be committed.

### A.6 Automated validation happens before smoke testing

A Rick-authored patch must pass the relevant automated validation before user-visible smoke testing.

Minimum validation normally includes:

```text
python -m compileall -q src tests tools
focused task tests
full test suite
git diff --check
relevant architecture or boundary checks
```

The repository source must win over any installed Leonardo package:

```powershell
$env:PYTHONPATH = "$PWD\src;$PWD"
```

A zero-test result is not a successful test run.

Warnings must be reported and classified as blocking, non-blocking, or deferred follow-up.

### A.7 Visual and runtime smoke testing is mandatory where applicable

Tests do not replace user-visible validation when a patch changes GUI, runtime, interaction, persistence, or provider behaviour.

The smoke test must run from the active `Leo_V2` repository and the correct Conda environment.

A task-specific smoke command file may be used from the VS Code integrated PowerShell terminal:

```powershell
conda activate py312_Leo
Set-Location "C:\Users\gmina\Documents\Python Project\Github_rep"
cmd /c ".\Task_<TaskID>_Smoke_Test.cmd"
```

The smoke-test script must:

```text
identify the active repository and branch
refuse a dirty or incorrect baseline when required
set PYTHONPATH to the active repository
launch only the intended workflow
preserve terminal output and exit status
avoid modifying tracked files unless explicitly required
report the exact manual acceptance checklist
```

The user performs visual acceptance when human observation is required. Rick records the result as PASS, FAIL, or PASS WITH FOLLOW-UP.

No GUI-affecting patch may be committed merely because automated tests pass.

### A.8 Commit only the accepted patch

After automated and manual validation:

```text
git add -- <explicit task files>
git diff --cached --check
git diff --cached --stat
git diff --cached --name-status
```

The commit message must identify the task and observable outcome.

Example:

```text
Task 1003: add OHLCV maintenance validation
```

The commit must not contain unrelated cleanup, opportunistic refactors, abandoned experiments, or files from another task.

### A.9 Push the task branch, never force-push main

The validated task branch is pushed with tracking:

```text
git push -u origin <task-branch>
```

Rick must not:

```text
force-push main
rewrite published task history without explicit approval
delete remote work merely to simplify a merge
push an unvalidated recovery folder
push from an obsolete or damaged repository
```

If a remote branch already exists, its relationship to the local branch must be inspected before it is updated.

### A.10 Use a pull request for integration

Every normal Rick-authored patch is integrated through a pull request:

```text
task branch
-> pull request
-> review
-> merge commit
-> main
```

The pull request must state:

```text
Task ID and name
reason for the change
files and workflows affected
canonical authorities affected
persistence impact
validation performed
test results
manual smoke-test result
known warnings
remaining risks
```

Use a merge commit when preserving task history matters. Do not squash a meaningful multi-commit history merely for cosmetic neatness unless explicitly approved.

Automatic mergeability proves only that Git can combine the branches. It does not prove the patch is correct.

### A.11 Return the local repository to normal after merge

After the pull request is merged:

```text
git switch main
git pull --ff-only origin main
```

The merged `main` must be revalidated when the task warrants it.

Only after local `main` matches the merged remote state may task branches be deleted:

```text
git branch -d <task-branch>
git push origin --delete <task-branch>
git fetch --prune origin
```

The expected final state is:

```text
active folder:
C:\Users\gmina\Documents\Python Project\Github_rep\Leo_V2

active stable branch:
main

remote:
origin/main

working tree:
clean
```

### A.12 Destructive operations require a recovery gate

Before any operation that may delete, replace, mirror, rename, reset, or overwrite repository contents, Rick must record:

```text
current repository path
current branch
current HEAD
remote URL
working-tree status
validated recovery package or remote branch
exact destructive command
exact rollback path
```

The recovery source must be validated before the destructive command runs.

The following operations require explicit justification and user confirmation:

```text
git reset --hard
git clean -fd
git push --force
robocopy /MIR
Remove-Item -Recurse
repository-root replacement
.git directory replacement
```

The repository root must never be deleted, emptied, or replaced during an ordinary patch workflow.

### A.13 Rick owns implementation evidence and independent validation evidence

When Rick performs the patch directly, there is no Codex implementation report. Rick must therefore provide both:

```text
implementation evidence
independent validation evidence
```

The final Rick report must include:

```text
task identity
starting commit
task branch
package hash and input baseline
files added, modified, and deleted
behaviour implemented
scope result
canonical-authority result
persistence result
automated tests
manual smoke-test result
warnings
commit hash
remote branch
pull request
merge result
final main commit
remaining follow-up
```

A Rick-authored patch is complete only after:

```text
the patch is committed
the task branch is pushed
the pull request is merged
local main is synchronized
the working tree is clean
the task branch is retired
```

### A.14 Default Rick-authored patch lifecycle

The required lifecycle is:

```text
Audit package
-> define task
-> verify clean main
-> create Rick task branch
-> isolate and apply bounded patch
-> inspect changed-file boundary
-> run focused validation
-> run full validation
-> run required visual or runtime smoke test
-> stage explicit files
-> validate staged diff
-> commit
-> push task branch
-> open pull request
-> merge
-> return to main
-> fast-forward local main
-> validate merged main
-> delete local and remote task branches
-> close task ledger
```

This is the default protocol whenever Rick, rather than Codex/Goblin, performs the implementation.

No Rick-authored patch may bypass this lifecycle merely because the patch appears small.

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