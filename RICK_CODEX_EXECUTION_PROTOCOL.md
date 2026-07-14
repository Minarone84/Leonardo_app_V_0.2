# Leonardo Light V2 Rick–Codex Execution Protocol

**Document ID:** `LEO-LV2-RICK-CODEX-EXECUTION-PROTOCOL-002`
**Version:** `2.4`
**Status:** Approved governing protocol
**Supersedes:** `LEO-LV2-RICK-CODEX-EXECUTION-PROTOCOL-002` version 2.3 and all earlier versions

---

## 1. Purpose

This document defines how Leonardo Light V2 work is divided between:

- Rick;
- Codex/Goblin;
- the user;
- the repository’s code, tests, domain specifications, persisted schemas, and validation packages.

It complements:

```text
AGENTS.md
RICK_PROTOCOL_12_COMMANDMENTS.md
LEONARDO_LIGHT_V2_ARCHITECTURE_GUIDELINE.md
```

It does not replace those documents.

`AGENTS.md` remains the implementation-agent authority.

`RICK_PROTOCOL_12_COMMANDMENTS.md` remains the Rick workflow and governance authority.

`LEONARDO_LIGHT_V2_ARCHITECTURE_GUIDELINE.md` remains the accepted application architecture.

This protocol defines:

- who decides;
- who implements;
- what Codex may be asked to do;
- when a task is too ambiguous to send to Codex;
- how implementation is validated independently.

---

## 2. Prime operating rule

```text
Rick resolves every architecture, product, scope, ownership, naming,
persistence, GUI, testing, and workflow decision.
Codex executes the accepted instructions literally.
Codex has zero authority to improve or reinterpret them.
Rick validates the result independently.
The user accepts product behaviour and visual outcomes.
```

Codex is not restricted to small tasks.

Codex is restricted to tasks with **zero unresolved decision entropy at handoff**.

Task size, file count, and implementation complexity are not the primary risks.

The primary risks are:

```text
unresolved product intent
competing sources of truth
unclear critical authority
unstable durable data meaning
hidden persistence changes
unbounded failure radius
speculative abstraction
subjective visual decisions
unsolicited improvement
```

### 2.1 Zero-freedom law

Codex/Goblin has no design freedom, no improvement freedom, no cleanup freedom, and no authority to reinterpret intent.

The accepted task is a closed instruction set. Codex may:

```text
inspect the required evidence
perform the exact stated transformations
run the exact required validation
report the exact result
stop on any unresolved decision
```

Codex may not, unless the exact action is stated:

```text
improve
refactor
rename
restyle
reorganise
optimise
modernise
standardise
generalise
add compatibility
fix adjacent defects
broaden or reduce scope
change tests or acceptance criteria
substitute a preferred implementation
```

“Helpful,” “obvious,” “cleaner,” “safer,” “more consistent,” and “best practice” do not grant permission.

Mechanical syntax that is strictly equivalent is permitted only when it follows the current local pattern and leaves no material implementation choice. When two materially different valid implementations remain, Codex stops and asks Rick to decide.

---

## 3. Retired Heavy V2 execution doctrines

The following doctrines are retired:

```text
Strict NSRR as a universal task gate
Contract-first implementation sequence
Public contracts for internal workflow records
GUI implementation driven by detailed window manifests
Mandatory GUI object metadata and object-level roadmaps
Object Map and trace-provider completeness as acceptance gates
Universal contract, metadata, and census coherence checks
```

They are replaced by:

```text
Canonical authority over critical truth and mutable state
Precise domain specifications for durable concepts
Versioned schemas for persisted objects
Formal contracts only at genuine hard boundaries
Direct typed Python inside application areas
Runtime GUI discovery through stable IDs and registries
Vertical workflow validation
Minimum justified complexity
```

---

## 4. Decision entropy

### 4.1 Definition

Decision entropy is the amount of unresolved architectural, behavioural, authority, persistence, workflow, or product judgement inside a task.

A task has zero unresolved decision entropy at Codex handoff when:

- the requested user outcome is accepted;
- the implementation boundary is understood;
- critical authorities are known;
- durable data structures are defined where needed;
- persistence effects are known;
- acceptance tests are objective.

A task is not admissible when Codex must choose any materially different architecture, workflow, authority, product behaviour, file boundary, naming rule, persistence effect, GUI result, or test meaning.

### 4.2 Zero-decision-entropy examples

```text
Connect this accepted GUI shell action to this application service.
Replace the metadata-driven window title with this explicit code value.
Make TaskManager expose this accepted read-only snapshot.
Implement this accepted persisted schema and migration.
Port this old Leonardo calculation without changing its semantics.
Apply this deterministic naming policy.
Delete these trace-only modules after their consumers are removed.
Add the exact vertical tests listed below.
```

### 4.3 Nonzero-decision-entropy examples

```text
Design the best architecture.
Decide whether this object needs a contract.
Choose which of several models is canonical.
Determine which layer should own this critical truth.
Invent the GUI workflow.
Decide whether old behaviour should be preserved.
Create abstractions where useful.
Make the GUI better without accepted visual requirements.
Simplify the entire repository without a keep/delete policy.
```

Nonzero-decision-entropy work remains with Rick until every material decision is resolved and frozen.

---

## 5. Permanent role division

### 5.1 Rick owns

Rick permanently owns:

```text
product architecture
system boundaries
critical-authority decisions
canonical source-of-truth selection
domain-specification policy
persisted-schema policy
formal-contract admission
GUI workflow definition
GUI-shell boundary
visual acceptance requirements
old-version interpretation
migration sequence
task identity and scope
workplan design
Codex prompt preparation
implementation-report review
POST/PATCH package validation
final architectural verdict
workflow ledger
```

Rick must not delegate unresolved architecture or product interpretation to Codex.

Rick must not require a contract, port, registry, metadata system, or adapter merely because one could exist.

### 5.2 Codex/Goblin owns

Codex/Goblin owns literal bounded execution:

```text
deterministic implementation of the exact accepted transformation
mechanical migration
accepted domain-model implementation
accepted persisted-schema implementation
accepted boundary implementation
internal model construction
repository-wide consistency updates
GUI shell construction from exact accepted requirements
signal and service wiring
runtime registration
vertical test construction
fixture construction where tests require it
local GUI rendering
validation execution
diff reporting
original-code comparison
```

Codex may perform large or technically complex work when the complete target design, file boundary, behaviour, and validation are fixed.

Codex must not silently broaden scope, reduce scope, improve adjacent code, alter tests, or invent new architectural layers.

### 5.3 The user owns

The user owns:

```text
product priorities
workflow acceptance
visual acceptance
intentional changes from old behaviour
task-order changes
approval of architecture direction
approval of exceptions
authorisation for direct Rick patching
final acceptance
```

### 5.4 One-writer working-tree rule

One working tree has one modification owner at a time.

Codex may work while Rick audits only when Rick remains read-only. Parallel modification requires separate declared worktrees or repositories and an explicit merge plan. Shared-checkout parallel editing is forbidden.

---

## 6. Light V2 architectural execution model

Leonardo Light V2 is a modular asynchronous application.

```text
GUI shell
    collects intent and presents state

Presenter / controller
    translates GUI intent and presentation state

Area application service
    coordinates the workflow and execution policy

Domain service
    owns financial or business logic

Core
    runs and supervises long work

Provider or store
    communicates externally or persists results
```

### Core owns

```text
application lifecycle
async runner
task lifecycle
progress and cancellation
process lifecycle
generic runtime identifiers
coarse operational connection summaries supplied by Connection
window runtime state
application-wide discoverable actions registered only when shared invocation, shortcuts, automation, audit, or AI access require them
configured local actor identity exposed for audit correlation
historical actor evidence owned by AuditLog
coherent logging
audit events
structured error routing
Runtime Manager snapshots
safe shutdown
```

Core does not own provider, API, or websocket semantics. Connection owns their detailed behaviour and state; Core may expose only generic runtime identity and coarse operational summaries.

### Areas own

```text
financial meaning
provider, API, and websocket behaviour
validation semantics
calculation semantics
research workflows
data preparation
analysis logic
backtesting logic
trading and risk logic
```

Suites are user-facing GUI groupings. They do not define code ownership.

### GUI owns

```text
windows and widgets
layouts
user interaction
local presentation state
display formatting
appearance
navigation
focus and selection context
```

The GUI does not own domain execution or persistence policy.

Local GUI interactions normally call their presenter/controller directly. A global action registry is used only for operations requiring application-wide discovery, shared invocation, shortcuts, automation, audit policy, or future AI access. It must not become the mandatory path for ordinary widget behaviour or the owner of business validation.

Strict NSRR is not used.

The governing authority rule is:

> Every critical invariant, canonical identity, persisted truth, financial rule, and mutable runtime-state family has one authoritative owner and one controlled write path.

Multiple components may participate in one workflow.

---

## 7. Codex task admission gate

A task may be sent to Codex only when all applicable gates pass.

### Gate 1: Accepted user outcome

There is one accepted behavioural or structural result.

Codex is not choosing between product alternatives.

### Gate 2: Canonical source per affected fact

The prompt identifies the authority for each affected durable fact.

Typical authorities include:

```text
accepted Light V2 architecture
old Leonardo working behaviour
canonical domain specification
canonical naming policy
persisted schema
current implementation
vertical behaviour test
```

Handwritten metadata, roadmaps, or descriptors are not assumed authoritative.

### Gate 3: Critical authority known

The task identifies the authority and write path for any affected:

```text
critical invariant
canonical identity
persisted truth
financial rule
runtime-state family
```

The task does not need an exclusive owner for every workflow step.

### Gate 4: Exact transformation

The implementation is described deterministically and leaves no material choice to Codex:

```text
X becomes Y
A calls B through method C
file D is added with the stated responsibility
file E is modified only in the named functions
file F is removed after the named consumers are removed
G preserves old behaviour through H
```

### Gate 5: Objective acceptance

The result can be validated primarily through:

```text
vertical workflow tests
domain-rule tests
persistence and migration tests
async progress/cancellation/failure tests
runtime snapshot tests
provider-adapter tests
GUI smoke tests
manual visual acceptance
diff inspection
dependency checks
```

Contract or schema tests are required only where genuine contracts or persisted schemas exist.

### Gate 6: Bounded failure radius

A failed implementation cannot silently corrupt unrelated Areas, persisted objects, runtime state, or financial behaviour.

### Gate 7: No hidden product or visual decision

Codex is not deciding:

- user workflow;
- financial semantics;
- intentional changes from old behaviour;
- subjective visual hierarchy;
- whether a temporary model should become a public contract;
- whether a new abstraction should exist.

### Gate 8: Complexity is justified

Every new public abstraction, registry, adapter, schema, or formal contract has an accepted concrete purpose.

“Useful in the future” is not sufficient.

### Admission result

```text
All applicable gates pass and no material implementation decision remains:
Codex task allowed.

Any blocking gate fails or any material choice remains:
Task returns to Rick for an explicit decision. Codex does not choose.
```

---

## 8. Task suitability matrix

| Task type | Codex suitability |
|---|---|
| Small and deterministic | Excellent |
| Large and repetitive | Excellent |
| Complex but fully specified | Good |
| Cross-layer with fixed behaviour and authorities | Good in bounded slices |
| GUI shell from exact accepted layout, states, IDs, and behaviour | Good |
| Exact prescribed internal refactor with no durable meaning change | Good |
| Persisted-schema implementation from an accepted schema | Good |
| Literal port of the exact behaviour selected by Rick | Good |
| Architecturally ambiguous | Reject |
| Competing candidate sources of truth | Reject |
| Requires critical-authority invention | Reject |
| Subjective visual design without acceptance criteria | Reject |
| Open-ended abstraction design | Reject |
| Broad product interpretation | Reject |
| Repository-wide simplification without a classification policy | Reject |

The governing rule is:

> Give Codex only zero-decision-entropy work, regardless of technical complexity or size.

---

## 9. GUI-specific execution policy

GUI work is separated into shell design, service connection, and visual acceptance.

### 9.1 Rick defines

Rick defines:

```text
window purpose
visible user workflow
required GUI states
layout hierarchy
responsive behaviour
font and theme expectations
stable meaningful window/action IDs
editable appearance requirements
which actions are direct
which actions create async jobs
application service called by each action
manual visual acceptance conditions
```

Rick does not need to define handwritten widget trees, parent maps, GUI metadata manifests, object censuses, or object-level roadmaps.

### 9.2 Codex implements

Codex may:

```text
construct widgets and layouts directly
assign stable QObject.objectName values
assign semantic appearance roles
declare editable appearance properties
emit intent signals
connect controls to presenters/controllers
connect presenters/controllers to application services
bind async progress and results
register live windows and widgets
implement exact resize policies
write GUI smoke tests
capture screenshots
run local PySide6 validation
```

### 9.3 GUI shell boundary

The GUI may own:

```text
input collection
selection state
trivial usability checks
dialogs
enabled/disabled presentation state
progress display
result display
appearance and navigation
```

The GUI must not own:

```text
provider communication
financial calculations
canonical validation truth
persistence policy
database construction
analysis algorithms
backtest mathematics
risk decisions
order execution
async task lifecycle
```

### 9.4 GUI-first development

Accepted sequence:

```text
1. Build the shell.
2. Define visible states.
3. Assign stable IDs and appearance roles.
4. Emit intent signals or use explicitly labelled placeholders.
5. Implement the application/domain service.
6. Connect long work through Core.
7. Validate the vertical workflow.
8. Obtain user visual acceptance.
```

A shell is not complete functionality.

Fake backend behaviour must never be presented as production behaviour.

### 9.5 Visual acceptance

Tests may prove structure and state transitions.

They do not prove visual quality.

Final GUI acceptance requires:

```text
Codex local rendering
Rick structural validation
user visual smoke test
explicit user acceptance
```

---

## 10. Domain specifications, schemas, contracts, and internal models

Codex prompts must distinguish among:

### Domain specifications

Define durable Leonardo concepts, such as Financial Tools, artifacts, or custom indicators.

### Canonical policies

Define deterministic rules, such as naming or compatibility.

### Persisted schemas

Define saved objects that future Leonardo versions must load.

### Boundary contracts

Define stable communication across a genuine hard boundary.

### Internal models

Support one implementation and may change freely.

### Runtime snapshots

Expose read-only state from an existing manager.

### Report models

Represent structured analytical, validation, or execution outcomes.

A formal boundary contract may be introduced only for one of these accepted hard boundaries:

```text
versioned persisted data loaded by future Leonardo versions
external wire formats exchanged outside the application process
financially dangerous operations requiring stable validation and audit
```

Thread crossing, process supervision, provider replacement, GUI-to-presenter calls, ordinary cross-Area DTOs, and future AI capability ideas normally use owner-local typed models or local Protocols rather than formal contracts.

Every proposed formal contract must identify:

```text
Owner
Producer
Independent consumer
Boundary crossed
Versioning requirement
Failure prevented
Why owner-local typed code is insufficient
```

No Contract Registry, metadata mirror, or compatibility catalogue is required merely because a type exists.

---

## 11. Architecture-critical task decomposition

Architecture work must be decomposed into independently testable, reversible slices.

Each task or implementation branch should normally advance one primary vertical workflow. Parallel work is allowed only when branches have explicit boundaries, independent authorities, and a defined merge plan.

The default vertical sequence is:

```text
1. User workflow and acceptance criteria
2. GUI shell, when applicable
3. Canonical domain objects or policies, only where needed
4. Presenter or controller, when GUI-facing
5. Area application service
6. Domain implementation
7. Provider or persistence implementation
8. Core async integration, when needed
9. Structured result and runtime tracking
10. Vertical tests
11. Runtime and visual validation
```

A task must not combine all of the following unless every decision is already accepted:

```text
new domain semantics
new persisted schema
new external provider wire format or provider behaviour
Core lifecycle changes
GUI workflow redesign
visual redesign
repository-wide deletion
trading or risk behaviour
```

Do not introduce generators, registries, ports, schemas, or adapters before a concrete need is accepted.

---

## 12. Prompt construction rules

Every Codex prompt must include:

```text
Zero-discretion statement
Task ID
Task name
Parent workplan, if any
Accepted architecture decision
Objective
Starting Git/package evidence
Allowed files or packages
Conditionally allowed files
Forbidden files or packages
Critical authorities affected
Canonical data structures affected
Persistence impact
Async/runtime impact
GUI-shell boundary
Exact file-by-file implementation requirements
Explicit forbidden improvements and non-goals
Required tests
Required manual validation
Stop conditions
Required literal-conformance report format
Original-code comparison, where relevant
```

### 12.1 Mandatory zero-discretion clause

Every Codex prompt must state, in substance:

```text
You have zero authority to improve, refactor, rename, restyle,
reorganise, optimise, modernise, standardise, extend, fix adjacent
issues, alter tests, or change any file outside the explicit scope.
Implement only the exact instructions below. If any decision is
missing, stop and report it.
```

This clause is not optional shorthand. It is the default operating boundary.

### 12.2 Prompts state decisions, not invitations

Preferred:

```text
Replace the metadata-driven Research Suite window title and geometry
with explicit window code. Preserve the accepted visual result, stable
window ID, runtime registration, and all existing shell behaviour. Do
not add a replacement metadata layer.
```

Rejected:

```text
Simplify the GUI architecture and add abstractions where useful.
```

### 12.3 Prompt length is not a quality metric

A prompt is correct when it eliminates unresolved choices and protects the requested outcome.

A long prompt containing open architecture is unsafe.

A concise prompt with complete invariants may be sufficient.

### 12.4 Prompt count

Default:

```text
1 implementation prompt per task
```

Normal maximum:

```text
2 prompts per task
```

More than two prompts requires a workplan review and architecture reassessment.

Repeated correction caused by unclear design returns the task to Rick.

---

## 13. Codex stop conditions

Codex must stop and report when:

```text
the expected repository baseline is wrong
the working tree is unexpectedly dirty
the accepted source conflicts with current evidence
a critical authority or write path is unclear
the requested result requires an unapproved product decision
the requested result requires an unapproved durable data change
the allowed file boundary is insufficient
the task requires forbidden-package changes
tests prove the accepted design cannot work as written
old behaviour conflicts with the approved target
a runtime dependency is unavailable
visual validation cannot be performed where required
the task requires silent scope expansion
more than one materially different implementation remains possible
an unsolicited improvement appears desirable but is not instructed
the implementation would add speculative public architecture
the implementation would preserve or recreate a retired Heavy V2 system
```

Codex must not improvise around a stop condition.

---

## 14. Direct Rick implementation policy

Rick does not directly patch by default.

Direct Rick patching is permitted only when:

```text
the user explicitly authorises it
the change is narrowly isolated
the exact transformation is accepted
the affected boundaries are understood
the patch can be independently validated
```

Suitable examples:

```text
small documentation correction
isolated test repair
exact persisted-schema typo
narrow compatibility fix
small direct-code replacement of retired metadata plumbing
correction Codex repeatedly failed to implement
```

Direct Rick patching remains subject to:

- scope control;
- diff review;
- runtime validation;
- package validation;
- workflow ledger updates.

The default integration finish for a Rick-authored local task is:

```text
apply
→ validate
→ stage explicit files
→ local commit
→ clean working tree
→ stop
```

Push and pull request work occur only when the user or accepted task explicitly requests a remote checkpoint.

---

## 15. Separation of duties

Preferred control loop:

```text
Rick:
audit, architecture, and task shaping

User:
approve architecture, workflow, and visual direction

Rick:
prepare bounded Codex prompt

Codex:
implement and validate locally

Rick:
Phase A implementation-report review

Rick:
Phase B POST/PATCH package validation

User:
workflow and visual acceptance

Rick:
close task and update ledger
```

The implementation agent’s report is evidence, not final truth.

Passing unit tests is necessary but may not be sufficient.

---

## 16. Validation law

Every Codex task must produce:

```text
Baseline evidence
Files inspected
Files changed
Exact instructed behaviour changed
Canonical models or schemas changed, where applicable
Tests added or updated
Commands run
Results
Git diff checks and literal scope conformance
Remaining risks
Out-of-scope findings
Old-code comparison, where applicable
Final implementation status
```

Rick Phase B independently confirms:

```text
Package integrity
Expected baseline
Changed-file boundary
Actual behaviour
Vertical workflow result
Critical-authority result
Canonical model/schema result, where applicable
Persistence and migration result, where applicable
Async progress/cancellation/failure result, where applicable
Runtime tracking result, where applicable
GUI-shell and visual result, where applicable
Naming-policy result, where applicable
Full relevant test suite
Remaining blockers
```

Allowed Rick verdicts:

```text
PASS
PASS WITH FOLLOW-UP
PATCH REQUIRED
REJECT / UNSAFE
CANNOT VALIDATE
```

---

## 17. Evidence from Heavy V2

The Download Data and GUI repetition demonstrated:

1. The product scope was not the main problem.
2. The async Core was not the main problem.
3. Too many internal models were promoted to public contracts.
4. The same facts existed in code, metadata, manifests, roadmaps, and tests.
5. Strict NSRR converted collaborative workflows into ownership disputes.
6. GUI metadata became a handwritten second GUI.
7. Tests often proved structural paperwork rather than complete user workflows.
8. Codex was asked to resolve architecture while implementing it.
9. Large prompts did not remove unresolved decisions.
10. Feature size grew far beyond its behavioural value.

The corrective rules are:

```text
Close product and architecture decisions before implementation.
Model durable concepts precisely.
Formalise only genuine boundaries.
Keep internal models internal.
Use one canonical editable representation per durable fact.
Validate complete vertical workflows.
Make every abstraction earn its place.
```

This is a workflow and architecture correction, not a judgement that Codex cannot execute complex engineering.

---

## 18. Leonardo Light V2 permanent operating model

### Rick

```text
decides
specifies
decomposes
audits
validates
```

### Codex

```text
implements
migrates
ports
tests
renders
reports
```

### User

```text
prioritises
approves
accepts
authorises exceptions
```

---

## 19. Task ledger requirement

Every task records:

```text
Decision entropy at handoff:
ZERO / NONZERO

Implementation discretion:
NONE

Codex admission:
ALLOWED / BLOCKED

Reason:
Specific gates passed or failed

Architecture status:
OPEN / ACCEPTED / FROZEN FOR TASK

Critical authorities affected:
Named authorities and write paths

Durable data impact:
NONE / DOMAIN MODEL / PERSISTED SCHEMA / BOUNDARY CONTRACT

Implementation agent:
Codex / Rick-authorised direct patch / none
```

Codex may receive only tasks whose architecture status is:

```text
ACCEPTED
or
FROZEN FOR TASK
```

A NONZERO-decision-entropy task cannot be sent to Codex.

Rick must decompose or specify the task until the implementation slice has zero unresolved material decisions.

---

## 20. Enforcement rules

The following are protocol violations:

```text
asking Codex to design and implement a critical boundary in one step
asking Codex to choose among competing canonical sources
asking Codex to invent critical authority or persistence policy
accepting implementation claims without package review
closing GUI work without user visual acceptance
using prompt length as a substitute for accepted design
silently broadening or improving an implementation task
changing a file, test, name, layout, API, or behaviour not explicitly authorised
creating public contracts for disposable internal data
creating handwritten metadata mirrors of live code
rebuilding Object Map, GUI metadata, or contract-registry bureaucracy
allowing a derived representation to become a second write path
closing a feature on internal tests without a vertical workflow check
reusing a failed task ID
continuing repeated patch loops without architecture review
```

---

## 21. Prime laws

```text
Task size is not the risk. Unresolved decisions are the risk.

Codex has zero improvement authority. Literal execution is the law.

Shared workflow participation is normal.
Competing canonical authority is not.

Durable concepts deserve precise models.
Disposable plumbing does not deserve public architecture.

Contracts protect real boundaries.
They do not validate that our code agrees with itself.

The GUI is a shell.
Domain services own domain behaviour.
Core supervises long-running work.

Vertical behaviour outranks structural ceremony.

No task closes on implementation-agent claims alone.

No GUI closes without user visual acceptance.

No abstraction survives merely because it already exists.
```

---

## 22. Workflow position

```text
Protocol status:
APPROVED

Applies to:
All Leonardo Light V2 work after the governance reset

Relationship:
Complements AGENTS.md, RICK_PROTOCOL_12_COMMANDMENTS.md,
and LEONARDO_LIGHT_V2_ARCHITECTURE_GUIDELINE.md

Default execution model:
Rick decides every material detail → Codex executes literally → Rick validates → user accepts

Direct Rick patching:
Exceptional and explicitly authorised
```
