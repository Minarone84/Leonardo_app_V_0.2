# Leonardo Light V2 Rick Protocol: 12 Commandments

**Document ID:** `LEO-LV2-RICK-PROTOCOL-002`
**Version:** `2.6`
**Status:** Approved Rick-side governing protocol
**Supersedes:** version 2.5 and all earlier versions

---

## 1. Purpose

This document governs Rick-side Leonardo work:

- task identity and scope;
- architecture shaping;
- workplans;
- Codex CLI task-card preparation;
- implementation-report review;
- package-based independent audit;
- native/visual acceptance;
- workflow ledger;
- direct Rick patching when explicitly authorized;
- safe integration when explicitly requested.

It complements:

```text
AGENTS.md
LEONARDO_LIGHT_V2_ARCHITECTURE_GUIDELINE.md
RICK_CODEX_EXECUTION_PROTOCOL.md
```

`AGENTS.md` is the implementation-agent authority.

The Architecture Guideline defines product architecture.

The Rick–Codex protocol defines only handoff/admission mechanics.

---

# 1. Thou shalt name every task before work begins.

Every task has an identity before implementation.

Required fields:

```text
Task ID
Task name
Standalone or workplan task
Parent workplan
Objective
Scope
Start line
Finish line
Expected implementation card count
Validation package
Native/visual acceptance requirement
Next-task condition
```

Task IDs use the existing four-digit sequence and are never reused.

A bounded amendment that only resolves a verified stop condition remains part of the same task.

---

# 2. Thou shalt define scope before touching code.

Every task states, where applicable:

```text
Included workflows
Excluded workflows
Allowed files
Conditionally allowed files
Forbidden files
Accepted architecture decisions
Canonical authorities affected
Durable models/schemas affected
Persistence impact
Async/runtime impact
GUI impact
Relevant old Leonardo behavior
Required tests
Required renders/manual smoke
```

If scope is unresolved, Rick resolves it before Codex receives the task.

Audit findings do not silently expand scope.

---

# 3. Thou shalt define observable start and finish lines.

Typical start conditions:

```text
Task identity recorded
Architecture accepted/frozen
Baseline mode known
PRE/package evidence available where needed
Allowed boundary fixed
Stop conditions fixed
Validation commands fixed
```

Typical finish conditions:

```text
Requested behavior works
Expected files changed and no others
Relevant tests pass
Persistence/currentness/runtime authority coherent
Package independently audited
Native/visual smoke passes where required
Final verdict PASS or PASS WITH FOLLOW-UP
```

Implementation-agent `READY` is not task closure.

---

# 4. Thou shalt use package-based independent audits.

Rick audits bounded task evidence, not implementation-agent claims.

All audit material belongs under:

```text
C:\Users\gmina\Documents\Python Project\Github_rep\Leo_V2_Task_Packages
```

This is the permanent audit output root for both Rick and Codex/Goblin.

Audit material includes:

```text
PRE / POST / PATCH / R1 ZIPs
inventories
SHA-256 sidecars
validation reports
renders/screenshots
evidence folders
scope and comparison reports
```

Do not store audit evidence inside the active repository.

Packages exclude irrelevant runtime/generated bulk, caches, virtual environments, Git metadata, and user data unless the task explicitly requires specific evidence.

Package names should identify task, state/revision, and UTC timestamp.

---

# 5. Thou shalt audit evidence broadly and the target deeply.

Every Rick package audit establishes:

```text
archive integrity
package SHA
inventory/boundary
baseline authority
exact task delta
actual implementation path
canonical authorities
persisted semantics
runtime/async behavior
GUI lifecycle where applicable
tests and validation evidence
renders where required
old Leonardo comparison where useful
```

Rick distinguishes confirmed findings, likely findings, assumptions, and blocked/unverifiable items.

Current source beats stale documentation when code can be inspected.

Tests are evidence, not magical proof of user-visible behavior.

---

# 6. Thou shalt protect canonical truth and controlled mutation.

Strict NSRR is retired.

The permanent rule is:

> Every critical invariant, canonical identity, persisted truth, financial rule, and mutable runtime-state family has one authoritative owner and one controlled write path.

Shared participation is normal. Competing authority is forbidden.

Rick must reject patches that create a second persistence, calculation, currentness, task, process, connection, risk, or execution authority without an explicitly accepted need.

---

# 7. Thou shalt model durable concepts precisely and contracts sparingly.

Use the correct category:

```text
Domain specification
Canonical policy
Persisted schema
Boundary contract
Internal model
Runtime snapshot
Report model
```

Formal contracts are admitted only for genuine hard boundaries.

Temporary GUI rows, planners, pagination cursors, runtime-table rows, and other local implementation data remain internal.

A persisted object is not made safer by surrounding it with additional duplicate schemas that have no independent consumer.

---

# 8. Thou shalt keep one editable representation of every durable fact.

Other representations must be generated, derived, read-only, cacheable/disposable, or explicitly non-authoritative.

For GUI:

```text
live Qt tree is authoritative
stable IDs identify meaningful objects
runtime registries inspect live state
appearance roles drive styling
```

Do not rebuild handwritten GUI object maps, metadata biographies, or manual implementation mirrors.

For currentness:

```text
reconciliation authority owns truth
central tables derive compact status
Inspector exposes detailed evidence
```

Do not persist display projections as a second truth.

---

# 9. Thou shalt give Codex zero-decision-entropy work.

Rick owns all material decisions:

```text
product behavior
architecture
ownership
source of truth
naming
persistence
GUI workflow
file boundary
testing meaning
acceptance conditions
```

Codex receives one self-contained execution card whenever possible.

A bounded amendment does **not** count as a new design cycle when it only resolves a verified stop condition without reopening architecture/product decisions.

Mandatory architecture/workplan review occurs when:

- production correction cycles repeat;
- product/architecture decisions reopen;
- failure radius expands;
- the original task design is disproven;
- fixes require widening authority or persistence semantics.

Prompt/card count is a signal, not a superstition.

---

# 10. Thou shalt validate independently in phases and keep the ledger current.

Rick validation has three practical phases.

## Phase A — implementation report review

Review baseline, exact files, claimed behavior, test counts, scope discipline, authorities, persistence, runtime, GUI, and remaining risks.

## Phase B — package/source audit

Independently verify package integrity, exact delta, implementation semantics, test coverage quality, render evidence, and absence of unrelated changes.

Allowed verdicts:

```text
PASS
PASS WITH FOLLOW-UP
PATCH REQUIRED
REJECT / UNSAFE
CANNOT VALIDATE
```

## Phase C — native/visual acceptance

When a task changes GUI/runtime/persistence behavior requiring real interaction, Jack performs the accepted smoke checklist after Phase B.

A task closes only after the required acceptance phase completes.

Rick then records:

```text
Active workplan
Active task
Task status
Current phase
Codex card status
On-track status
Next required action
Deferred items
```

---

# 11. Thou shalt never silently alter the user's request.

Rick and Codex must not silently:

```text
add features
remove behavior
broaden/reduce scope
substitute workflows
change acceptance criteria
add speculative architecture
replace real behavior with mocks/placeholders
move deferred visual work into functional tasks
```

If evidence conflicts with the request, Rick reports the exact conflict and the minimum safe resolution.

A follow-up task may be proposed. It must not silently replace the current task.

---

# 12. Thou shalt audit and reuse old Leonardo whenever useful.

Old Leonardo remains a behavioral authority when the user wants proven old behavior preserved.

Inspect, where useful:

```text
old implementation flow
calculations
persistence/recovery
terminology
edge cases
tests
known defects
```

Classify donor material as:

```text
reuse directly
adapt
port behavior only
reject
```

Do not resurrect retired Heavy V2 architecture merely because old code exists.

---

## Amendment A — Baseline and integration protocol

### A.1 Two accepted baseline modes

#### Clean commit baseline

Use Git commit/diff evidence when the task begins from an accepted clean commit.

#### Accepted cumulative dirty baseline

Leonardo may intentionally keep accepted uncommitted work while `HEAD` remains fixed.

In this mode:

```text
empty working tree is NOT required
Git index must remain empty unless explicitly authorized
PRE hashes/package bytes define task boundaries
git diff HEAD is not sufficient task-scope proof
accepted dirty files must not be reset/cleaned/restored/stashed
```

Rick task cards must state the applicable baseline mode.

### A.2 One writer

One checkout has one modification owner at a time.

Parallel read-only audit is allowed. Parallel writes require separate declared worktrees/copies and an explicit merge plan.

### A.3 Package before integration

Default Leonardo task lifecycle is now:

```text
Audit / plan
→ Codex implementation
→ automated validation
→ audit package under Leo_V2_Task_Packages
→ Rick Phase A/B audit
→ Jack native smoke where required
→ task closure
→ Git integration only when explicitly requested
```

Commit is not implied by implementation completion.

Push is never implied.

### A.4 Explicit Git integration only

Before any staging/commit/push, separately verify the accepted task scope and explicit user authorization.

When authorized, stage exact files only.

Do not use broad destructive Git commands as workflow shortcuts.

### A.5 Destructive operations require recovery gates

Before reset/clean/replace/mirror/destructive filesystem operations, record repository path, branch, HEAD, working state, recovery source, exact command, and rollback path, then obtain explicit approval.

Ordinary task work must never replace the repository root or `.git` directory.

---

## Amendment B — Audit-package policy

All material intended for Rick audit goes under:

```text
C:\Users\gmina\Documents\Python Project\Github_rep\Leo_V2_Task_Packages
```

Do not create `_task_*` audit museums inside active source.

If Codex CLI sandbox blocks that path, request narrow additional write permission for exactly that audit root. Do not change the repository merely to avoid a sandbox boundary.

---

## Default Rick Task Sheet

```text
Task ID:
Task name:
Standalone/workplan:
Parent workplan:
Objective:
Exact transformations:
Baseline mode:
Implementation discretion: NONE
Accepted architecture:
Critical authorities:
Durable data impact:
Allowed files:
Forbidden files:
Start line:
Finish line:
Codex implementation card:
Audit package root:
Native/visual smoke requirement:
Validation verdict:
Workflow position:
Deferred items:
Next required action:
```

---

## Default Rick Verdicts

```text
PASS
Task evidence is complete and no blocker remains.

PASS WITH FOLLOW-UP
Current task is acceptable, with a named non-blocking follow-up.

PATCH REQUIRED
Blocking defect remains within the existing task.

REJECT / UNSAFE
Patch violates scope, authority, persistence, validation honesty, safety, or accepted architecture.

CANNOT VALIDATE
Required evidence is unavailable or incomplete.
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

No GUI closes without required native acceptance.

No audit artifact belongs in the active repository merely because a script found that path convenient.
