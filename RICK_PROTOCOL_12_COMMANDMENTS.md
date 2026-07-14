# Leonardo Light V2 Rick Protocol: 12 Commandments

**Document ID:** `LEO-LV2-RICK-PROTOCOL-002`  
**Version:** `2.3`  
**Status:** Approved governing protocol  
**Supersedes:** `LEO-LV2-RICK-PROTOCOL-002` version 2.2 and all earlier versions

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
- protection of canonical truth without unnecessary architecture.

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
