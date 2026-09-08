# Leonardo Light V2 Rick–Codex Execution Protocol

**Document ID:** `LEO-LV2-RICK-CODEX-EXECUTION-PROTOCOL-002`
**Version:** `2.5`
**Status:** Approved handoff protocol
**Primary execution surface:** Codex CLI in PowerShell
**Supersedes:** version 2.4 and all earlier versions

---

## 1. Purpose

This protocol defines only the execution handoff between:

- Rick;
- Codex/Goblin;
- Jack;
- the active Leonardo repository;
- bounded audit packages.

It does not restate the complete Leonardo architecture or implementation rules.

Those authorities live in:

```text
LEONARDO_LIGHT_V2_ARCHITECTURE_GUIDELINE.md
AGENTS.md
RICK_PROTOCOL_12_COMMANDMENTS.md
```

The permanent control loop is:

```text
Jack + Rick decide
    ↓
Rick freezes one task card
    ↓
Codex CLI executes literally
    ↓
Codex validates and packages evidence
    ↓
Rick audits independently
    ↓
Jack performs native/visual acceptance where required
    ↓
Rick closes task
```

---

## 2. Role division

### Rick owns

```text
product interpretation
architecture
canonical authority decisions
persistence semantics
GUI workflow and visual requirements
scope/file boundaries
workplans
task cards
acceptance criteria
Codex admission
package audit
final task verdict
workflow ledger
```

### Codex owns

```text
literal implementation
mechanical migration
bounded code/test edits
validation execution
local renders required by the task
audit-package creation
literal-conformance reporting
```

Codex does not choose product behavior or architecture.

### Jack owns

```text
product priorities
approval of architecture/workplans
intentional changes from previous behavior
native/visual acceptance
approval of exceptions
Git integration requests
```

---

## 3. Decision entropy

A task has zero unresolved decision entropy when:

- the user outcome is accepted;
- the architecture/source of truth is fixed;
- critical authorities are named;
- durable data effects are known;
- allowed files are explicit;
- objective validation is defined.

Codex may receive only zero-decision-entropy tasks.

If Codex must choose between materially different behaviors, owners, persistence meanings, GUI results, APIs, or file boundaries, the task is not ready.

Codex stops. Rick decides.

---

## 4. Codex admission gate

Before handoff, Rick confirms:

### Gate 1 — accepted outcome
One user-visible/structural result is frozen.

### Gate 2 — authority known
Each affected critical truth/write path has an accepted authority.

### Gate 3 — durable data known
Any persisted schema/identity/migration effect is explicit.

### Gate 4 — exact transformation
The card says what becomes what, which files may change, and what must remain unchanged.

### Gate 5 — objective acceptance
Tests, renders, package checks, and/or native smoke can prove the result.

### Gate 6 — bounded failure radius
Failure cannot silently corrupt unrelated Areas or persisted data.

### Gate 7 — no hidden visual/product decision
Codex is not asked to make subjective product choices.

If any blocking gate fails, Rick keeps the task.

---

## 5. Codex CLI execution surface

The default Leonardo implementation surface is Codex CLI launched from:

```text
C:\Users\gmina\Documents\Python Project\Github_rep\Leo_V2
```

with the accepted Python environment active and repository source on `PYTHONPATH`.

Interactive CLI is the default for new/complex tasks because stop conditions and permission requests remain visible.

One-shot `codex exec` may be used later for tasks whose execution pattern has already proved stable and fully self-contained.

The preferred filesystem policy is workspace write for the repository plus narrow authorized access to the audit output root.

Audit output root:

```text
C:\Users\gmina\Documents\Python Project\Github_rep\Leo_V2_Task_Packages
```

If the CLI sandbox blocks this external audit root, Codex requests the smallest additional filesystem write permission for exactly that path. It must not relocate audit material into the repository as a workaround.

---

## 6. Project instructions

`AGENTS.md` is the permanent Codex implementation authority and is automatically consumed by Codex CLI when applicable.

Leonardo keeps root `AGENTS.md` intentionally concise. Do not add nested `AGENTS.md` / `AGENTS.override.md` files unless a concrete scoped need is explicitly approved.

The task card should not order Codex to read the Architecture Guideline, Rick Protocol, full workplan, continuation history, README, or historical task packages unless that specific task genuinely requires one of them as evidence.

The normal handoff input is:

```text
applicable AGENTS.md
+
current self-contained Rick task card
+
explicitly named source/specification evidence
```

More governance text is not more safety.

---

## 7. Mandatory task-card contents

Every Codex card contains, where applicable:

```text
zero-discretion statement
Task ID/name
parent workplan
architecture status
baseline mode
branch/HEAD/origin/environment
PRE hashes/new-path absence gates
objective
accepted authorities
persistence impact
async/runtime impact
GUI boundary
allowed files
forbidden files
exact transformations
forbidden improvements/non-goals
validation order
render/native smoke requirements
audit package destination
stop conditions
final report format
```

The card must state decisions, not invite design.

Bad:

```text
Improve Data Manager currentness architecture.
```

Good:

```text
Add this exact callback, trigger the existing reconciliation path,
map these existing statuses to these user-facing labels, modify only
these files, and run these tests.
```

---

## 8. Stop behavior

Codex stops when:

```text
baseline/hash gate differs
index state violates task
a required new path already exists unexpectedly
allowed-file boundary is insufficient
a canonical authority is unclear
persistence semantics are unresolved
task conflicts with current evidence
a protected test disproves the frozen design
a forbidden production file is required
required runtime/dependency is unavailable
visual evidence required by the task cannot be produced
a materially different implementation choice remains
```

A stop is success when it prevents unauthorized design.

Rick decides whether the result requires:

```text
clarification
bounded amendment
R1 correction
architecture review
new task
```

A bounded test-only amendment that reconciles an obsolete protected expectation does not automatically constitute a new design cycle.

Repeated production correction does trigger reassessment.

---

## 9. Validation and evidence

Codex validates in the order stated by the task.

Typical evidence includes:

```text
compileall
focused tests
vertical tests
protected compatibility tests
broader Area/GUI regressions
git diff --check
empty index gate
render evidence
exact package boundary
SHA-256
```

Codex reports exact counts, not merely `PASS`.

The implementation report is Phase-A evidence only.

Rick independently audits package/source bytes before product acceptance.

---

## 10. Audit package

Anything intended for Rick audit goes under:

```text
C:\Users\gmina\Documents\Python Project\Github_rep\Leo_V2_Task_Packages
```

The active source repository is not an audit-output directory.

A normal package contains only the bounded task code/tests plus explicitly required evidence such as renders, inventory, validation, scope comparison, and SHA sidecars.

Runtime persistence, user data, caches, Git metadata, extracted workspaces, and unrelated cumulative dirty files are excluded unless explicitly required as evidence.

When the working tree is cumulatively dirty, package PRE hashes and prior accepted package bytes may be used as the exact task-delta authority.

---

## 11. One writer and Git integration

One working tree has one writer.

Codex and Rick must not modify the same checkout concurrently.

Implementation does not imply Git integration.

Default finish:

```text
Codex validates
→ packages
→ reports READY/BLOCKED
→ Rick audits
→ Jack smokes if required
→ task closes
```

Staging, commit, push, pull, merge, reset, clean, restore, stash, and other Git writes occur only under an explicit current instruction.

---

## 12. Native/visual acceptance

Automated GUI tests and offscreen renders prove structure/state transitions, not final visual quality.

A GUI-bearing task closes only after the task's required native smoke.

Native smoke runs from the accepted repository/environment and verifies the actual user workflow.

Deferred subjective layout work must remain deferred if the current functional task does not authorize it.

---

## 13. Direct Rick patching

Rick direct patching is exceptional and requires explicit user authorization plus a narrow accepted transformation.

When authorized, Rick follows the same principles:

```text
bounded scope
one writer
baseline evidence
validation
package/evidence
native smoke where required
explicit Git integration only
```

Rick direct patching must not become a shortcut around the Codex admission discipline.

---

## 14. Permanent operating model

```text
Rick decides.
Codex executes.
Rick audits.
Jack accepts.
```

Codex technical complexity is not the risk.

Unresolved decisions are the risk.

A self-contained task card plus lean applicable `AGENTS.md` is preferred over feeding Codex the entire history of Leonardo governance.

The purpose of the protocol is not ceremony. It is to keep one writer working inside one closed decision box with evidence strong enough for independent audit.
