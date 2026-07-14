# Leonardo Light V2 - Agent Instructions

**Document ID:** `LEO-LV2-AGENTS-002`  
**Version:** `2.3`  
**Status:** Approved implementation-agent authority  
**Supersedes:** `LEO-LV2-AGENTS-002` version 2.2 and all earlier versions

---

## 1. Purpose and authority

This document defines how Codex, Goblin, or any implementation agent must work inside the Leonardo Light V2 repository.

The primary goal is safe, focused, reviewable software work that advances complete Leonardo workflows without recreating unnecessary architecture.

The governing document order is:

```text
1. Explicit user instruction for the current task
2. LEONARDO_LIGHT_V2_ARCHITECTURE_GUIDELINE.md
3. AGENTS.md
4. RICK_PROTOCOL_12_COMMANDMENTS.md
5. RICK_CODEX_EXECUTION_PROTOCOL.md
6. Accepted task or workplan
7. Canonical domain specifications and persisted schemas
8. Current implementation and tests
```

If two authorities conflict, stop and report the exact conflict. Do not invent a compromise.

The word `Codex` in this document means the active implementation agent. When the user refers to `Goblin`, the same rules apply unless the task gives narrower instructions.

---

## 2. Leonardo Light V2 direction

Leonardo Light V2 is a modular desktop financial research, analysis, backtesting, and trading application with a shared asynchronous runtime for long-running and concurrent operations.

The active baseline begins with:

```text
Core
GUI shells
Runtime tracking
Logging and audit
Appearance control
```

Domain capabilities are introduced as complete vertical slices, including:

```text
Connection and historical download
OHLCV validation and repair
Research Suite
Financial Tools
Data Manager
Analysis
Custom indicators
Backtesting
Real-time operation
Paper trading
Live trading
AI assistance
```

Old Leonardo is the behavioural reference for proven workflows, calculations, terminology, and edge cases.

Heavy V2 is a donor-code archive. Existing Heavy V2 code is not automatically the architectural authority merely because it exists or has tests.

Do not revive an old subsystem wholesale. Reuse only the parts accepted by the current task after dependency, behaviour, and fit inspection.

---

## 3. Retired Heavy V2 doctrines

The following doctrines are retired and must not be recreated unless the user explicitly approves them as a new requirement:

```text
Strict No Shared Responsibility Rule applied to every responsibility
Contract-first architecture by default
A public contract for every structured internal model
Contract Kernel and Contract Registry as universal infrastructure
Detailed handwritten GUI window metadata
Object-level GUI roadmaps and censuses as sources of truth
Object Map and trace-provider completeness as release gates
Mandatory metadata and contract coherence checks for every task
One runtime identity for every decorative GUI object
Architecture expansion before a working vertical workflow
```

They are replaced by:

```text
Canonical authority for critical truth
Controlled mutation of important state
Precise domain models for durable Leonardo concepts
Versioned schemas for persisted objects
Formal contracts only at genuine hard boundaries
Private typed models for internal work
Stable GUI IDs with runtime discovery
Vertical workflow validation
Minimum justified complexity
```

---

## 4. Core architecture

Leonardo uses one shared asynchronous Core.

Core owns application-wide infrastructure:

```text
application startup and shutdown
async event-loop execution
background task lifecycle
progress and cancellation
process lifecycle tracking
generic runtime identifiers
coarse operational connection summaries supplied by Connection
window runtime tracking
application-wide discoverable actions registered only when shared invocation, shortcuts, automation, audit, or AI access require them
configured local actor identity exposed for audit correlation
historical actor evidence owned by AuditLog
operational logging
audit history
structured error routing
Runtime Manager snapshots
safe ordered shutdown
```

Connection owns detailed provider, API, and websocket behaviour and state. Core may track generic identities and coarse operational summaries, but must not define provider semantics.

Core must remain domain-neutral.

Core must not define:

```text
financial calculations
OHLCV validation semantics
database-building rules
analysis logic
backtest mathematics
trading or risk decisions
GUI layout or presentation
```

Core runs and supervises work. Domain areas define what the work means.

`LeonardoApp` is the composition root unless an accepted task explicitly changes that architecture.

Long-running operations use the shared async Core. Trivial operations remain direct calls.

Examples of long-running work:

```text
historical downloads
repairs
artifact batches
database materialisation
analysis runs
backtests
long provider operations
```

Examples of direct work:

```text
opening or focusing a window
changing a font
reading a simple setting
formatting display text
```

Do not route trivial GUI work through the async runtime merely for uniformity.

---

## 5. Area architecture

Each Area owns its financial or business behaviour.

A Suite is the user-facing GUI grouping through which an Area is presented. Suite navigation does not define code ownership.

An Area may contain:

```text
application services
domain services
internal models
provider adapters
stores
validation
reports
tests
```

Presenters, controllers, Qt adapters, and other view-binding code belong to the GUI/application-adapter layer. They may coordinate an Area without becoming part of its domain ownership.

Areas use Core for:

```text
async execution
progress
cancellation
generic runtime tracking
logging
audit
error routing
application lifecycle
```

Areas must not create independent replacements for:

```text
task management
process management
global action registration
window tracking
audit logging
application shutdown
```

Several Areas may operate simultaneously. One Area must not block, mutate, or corrupt another Area's work through hidden global state or shared mutable implementation details.

---

## 6. Canonical authority and controlled mutation

Strict NSRR is retired.

The governing rule is:

> Every critical invariant, canonical identity, persisted truth, financial rule, and mutable runtime-state family must have one authoritative owner and one controlled write path.

Multiple components may:

```text
participate in one workflow
perform defensive validation
consume authoritative results
derive presentation state
cache read-only views
emit audit events
reuse shared mechanisms
```

They must not:

```text
create competing persisted truth
independently redefine a critical business rule
bypass the authoritative mutation path
duplicate financial calculation semantics
create parallel persistence or execution paths
promote derived display state to canonical truth
```

Examples of canonical authorities:

| Critical truth or state | Expected authority |
|---|---|
| Task lifecycle | Task Manager |
| Process lifecycle | Process Manager |
| Provider/API/websocket detailed state | Connection Area |
| Coarse operational connection summary | Connection Registry |
| Window runtime state | Window Registry |
| Current local actor identity | Application configuration |
| Historical actor evidence | AuditLog |
| OHLCV validity | OHLCV validator |
| OHLCV persistence | OHLCV store |
| Financial Tool definitions | Financial Tools specification registry |
| Artifact naming | Canonical naming policy |
| Database persistence | Database store |
| Risk approval | Risk service |
| Order execution | Trading gateway |

This table is illustrative. The accepted task and architecture determine the actual authority.

A workflow may legitimately involve several areas. Do not force a whole workflow into one god service merely to claim exclusive ownership.

---

## 7. Data-structure vocabulary

Do not call every dataclass a contract.

Use these categories:

### 7.1 Domain specification

Defines an important Leonardo concept and its semantics.

Examples:

```text
Financial Tool specification
Artifact definition
Recipe definition
Custom indicator definition
Backtest configuration
```

Domain specifications are canonical and may have many consumers.

### 7.2 Canonical policy

Defines deterministic rules.

Examples:

```text
ft_naming
market identity normalisation
timeframe canonicalisation
artifact compatibility
database naming
validation-status policy
```

### 7.3 Persisted schema

Defines data saved now and loaded later.

Examples:

```text
OHLCV sidecar
artifact metadata
recipe file
Analysis Database manifest
Study Environment
Workspace Snapshot
analysis report
custom indicator package
backtest report
trade record
```

Persisted schemas require explicit validation and versioning appropriate to their lifespan.

### 7.4 Boundary contract

Defines communication across an exceptional hard boundary requiring independent stability.

Valid present-day boundaries are limited to:

```text
versioned persisted data loaded by future Leonardo versions
external wire formats exchanged outside the application process
financially dangerous operations requiring stable validation and audit
```

Thread crossing, process supervision, provider replacement, GUI-to-presenter calls, ordinary cross-Area DTOs, and future AI capability ideas normally use owner-local typed models or local Protocols.

### 7.5 Internal model

Supports one implementation and may change with it.

Examples:

```text
preflight table row
pagination cursor
internal planner stage
temporary GUI summary
database-build intermediate record
runtime manager display row
```

Internal models should normally remain beside their owner and may use private dataclasses.

### 7.6 Runtime snapshot

A read-only projection from an authoritative manager for inspection.

### 7.7 Report model

A structured result used for validation, analysis, display, persistence, or AI explanation.

Important Leonardo objects must remain explicit, typed, validated, and documented. Simplification does not mean unstructured dictionaries everywhere.

---

## 8. Contract policy

Formal contracts must be kept to the minimum required by real stability boundaries.

Before creating or modifying a formal contract, identify:

```text
Owner
Producer
Consumer
Boundary crossed
Reason stability is required
Persistence or compatibility requirements
```

If those facts cannot be stated clearly, use an internal model, normal method signature, local Protocol, or direct typed Python instead.

Do not create formal public contracts for:

```text
temporary GUI state
preflight table rows
local service results
pagination cursors
internal planner stages
database materialisation internals
runtime-manager rows
process records
window records
one service calling another inside the same area
```

Formal contracts are justified only for:

```text
versioned persisted schemas loaded by future Leonardo versions
external wire formats exchanged outside the application process
financially dangerous operations requiring stable validation and audit
```

Provider adapters should normally use local Protocols. Async/process messages and cross-Area DTOs should normally remain owner-local typed models. OpenAI capability schemas are introduced only when a real external assistant interface exists.

A formal contract must not duplicate a canonical domain model merely to satisfy architecture ceremony.

Do not add a Contract Registry, compatibility registry, descriptor registry, or contract census unless a concrete current requirement proves ordinary code and tests are insufficient.

---

## 9. GUI shell policy

The GUI is a shell around Leonardo capabilities.

The GUI owns:

```text
windows
widgets
layouts
user interaction
selection state
display formatting
enabled and disabled presentation state
dialogs
progress presentation
visual errors and reports
appearance
navigation
focus and selection context
```

The GUI does not own:

```text
provider communication
async execution
financial calculations
OHLCV validation truth
persistence policy
database construction
analysis algorithms
backtest mathematics
risk decisions
order execution
```

A normal local GUI control delegates to its presenter or controller, which calls the relevant application service.

Only operations requiring application-wide discovery, invocation, auditing, shortcuts, automation, or future AI access are registered globally. Local presentation behaviour such as changing tabs, clearing a preview, expanding a tree, or applying a local filter bypasses the global action registry.

A window may perform lightweight usability checks, such as detecting an empty required field. Authoritative validation remains in the relevant application or domain service.

Windows must remain editable and replaceable without changing domain implementations.

---

## 10. GUI-first development

GUI-shell-first development is accepted.

For a feature, the preferred sequence is:

```text
1. Define the user workflow and acceptance conditions.
2. Build the GUI shell.
3. Define empty, ready, running, failed, cancelled, and completed states.
4. Assign stable meaningful IDs.
5. Connect controls to intent signals or clearly labelled shell handlers.
6. Implement application and domain services.
7. Connect long-running work through Core.
8. Validate the complete vertical workflow.
```

A shell must not contain fake domain logic that silently becomes production behaviour.

A feature is not complete because its window exists.

Do not build broad fleets of empty windows ahead of validated workflows unless the user explicitly requests GUI shell restoration as the task.

---

## 11. GUI tracking and appearance

Do not maintain a second handwritten copy of the GUI in TOML, JSON, roadmaps, or object metadata.

Use:

```text
stable window IDs
stable Qt objectName values
runtime window and widget registries
semantic appearance roles
editable-property declarations
focused, hovered, or selected widget context
```

The actual Qt object tree is the source of truth for live GUI structure.

A small executable window catalog is allowed when needed for navigation and construction. It should contain only operational facts such as:

```text
window ID
display title
category
factory
optional permission
```

Appearance settings may support:

```text
global theme values
semantic component roles
window overrides
widget overrides
font family
font size
font weight
colours
spacing
dimensions where supported
```

Do not create public contracts for each widget or window merely to support appearance editing.

---

## 12. Runtime tracking and Runtime Manager

Leonardo must track meaningful operational state.

Required runtime families include, as implemented:

```text
application state
tasks
processes
coarse operational provider/connection summaries
windows
meaningful user and AI actions
recent errors and warnings
```

Detailed API requests, provider sessions, and websocket channels remain owned by Connection and are exposed to Runtime Manager only through read-only summaries when operationally useful.

A general multi-user Session Service is not required today. Use one local actor identity until a real multi-user, remote-access, or authenticated external-assistant requirement exists.

Each runtime family has one manager or registry that owns mutable state.

Each manager should expose a read-only snapshot suitable for Runtime Manager.

Runtime Manager is an inspector. It must not become a second mutation authority.

Do not create Object Map graphs, relationship legends, trace-provider families, or public contracts merely to reconstruct state already owned by runtime managers.

Audit history and current runtime state are distinct:

```text
Runtime manager/registry: what is true now
Audit log: what happened before
```

---

## 13. Logging and audit

Leonardo uses one coherent logging architecture.

Operational logging supports:

```text
debugging
diagnostics
provider communication
calculation failures
performance information
startup and shutdown
development inspection
```

Audit events support meaningful application history, including:

```text
application startup and shutdown
user actions
task submission and settlement
process launch and termination
connection and websocket state changes
destructive operations
persistence operations
trading and risk decisions
```

Not every widget interaction requires an audit event.

Logging and audit depth must be proportional to operational or financial risk.

Do not create a unique public event type for every minor action when one structured audit event with contextual details is sufficient.

No fake cancellation, fake completion, fake success, or swallowed failure state is allowed.

---

## 14. AI assistant integration

The future OpenAI-powered assistant must use a small capability gateway.

Typical capabilities include:

```text
window.open
window.focus
runtime.status
task.cancel
appearance.adjust
download.prepare
download.execute
dataset.validate
database.build
backtest.run
```

The GUI and assistant must call the same underlying application services.

Do not create separate AI implementations of domain workflows.

The assistant must not manipulate Qt widgets to perform business operations. GUI context may resolve phrases such as `this window` or `that widget`, but the actual operation uses registered capabilities or appearance services.

High-risk capabilities must enforce confirmation and permissions in Leonardo, not in model prose.

---

## 15. Core working protocol

Every implementation task follows:

```text
Audit
Update
Validation
```

Do not skip Audit.

Do not skip Validation.

Do not mix unrelated work into one task.

If nested `AGENTS.md` files exist, apply the most specific file to each edited path.

If an instruction conflicts with the accepted task, stop and report the conflict.

---

### 15.1 Audit

Before editing:

- inspect the relevant code and tests;
- identify the actual workflow and behaviour;
- identify the smallest safe change;
- identify affected canonical authorities;
- identify affected domain specifications or persisted schemas;
- identify async, runtime, GUI, persistence, and external boundaries;
- compare old Leonardo behaviour when relevant;
- identify risks;
- separate confirmed findings from assumptions;
- avoid speculative refactoring.

Audit output must include:

```text
Problem summary
Relevant files
Current behaviour
Affected canonical authorities
Affected domain models/schemas/contracts, where applicable
Proposed change
Risk level
Validation plan
Additional findings
```

No files are changed during Audit unless the user explicitly authorises immediate editing as part of a bounded task.

---

### 15.2 Update

During Update:

- implement only the accepted scope;
- preserve behaviour outside the task;
- use the smallest justified architecture;
- preserve canonical domain meaning;
- preserve persisted compatibility unless explicitly changing it;
- do not create speculative layers;
- do not add parallel implementations;
- do not rename unrelated concepts;
- do not add dependencies without approval;
- do not perform unrelated formatting;
- keep the patch readable and reversible.

Update output must include:

```text
Files changed
What changed
Why it changed
Behaviour intentionally preserved
Out-of-scope findings left unchanged
```

---

### 15.3 Validation

After every update:

- run focused tests;
- run the relevant vertical workflow test when available;
- validate imports and package boundaries;
- validate async progress, cancellation, failure, and shutdown where relevant;
- validate persistence and compatibility where relevant;
- validate Runtime Manager tracking where relevant;
- validate GUI smoke behaviour and screenshots where relevant;
- review the entire diff against the original state;
- confirm no unrelated changes or formatting churn;
- report every failure honestly.

Validation output must include:

```text
Commands run
Results
Vertical workflow result, where applicable
Original-code comparison
Failures
Remaining risks
```

Do not weaken tests, suppress failures, or claim completion without evidence.

---

## 16. Phase-scoped aggregation

A task may aggregate related subpatches only when:

- they contribute to one accepted outcome;
- they share one bounded failure radius;
- all allowed files and non-goals are explicit;
- objective validation covers the combined result.

Keep high-risk work isolated unless the accepted workplan explicitly combines it:

```text
persistence writes
dataframe loading
provider execution
projection generation
backtesting
PnL validation
signal generation
trading/order behaviour
Core runtime changes
broad GUI-service wiring
```

Aggregation must never become an excuse to hide unrelated cleanup.

---

## 17. Surgical change rule

Every patch must be:

```text
minimal
task-bound
reviewable
free from unrelated formatting
free from opportunistic refactoring
free from speculative architecture
```

When the task is an explicit architecture reset, deletion, migration, or broad simplification, the patch may be large. It must still be bounded by a named workplan, explicit file scope, dependency order, and objective validation.

Do not preserve obsolete architecture merely because the surgical-change rule exists. Conversely, do not broaden a local fix into a cleanup campaign.

The final report must include an `Original-Code Comparison` section.

---

## 18. Scope control

Before editing, identify:

```text
Included workflows
Excluded workflows
Allowed files
Conditionally allowed files
Forbidden files
Accepted architecture decisions
Canonical authorities affected
Persisted schemas affected
GUI shells affected
Validation commands
Stop conditions
```

An issue outside the accepted scope belongs in `Additional Findings`.

Do not repair unrelated problems without explicit approval.

If ambiguity could cause destructive or broad changes, stop and report it rather than improvising.

---

## 19. Old Leonardo and donor-code reuse

Old Leonardo is the behavioural authority when the user wants the old workflow preserved.

Before reuse, inspect:

```text
behaviour and edge cases
imports and dependencies
hidden GUI/domain coupling
persistence assumptions
threading assumptions
calculations and naming
tests
defects to reject
```

Classify donor material as:

```text
reuse directly
adapt
port behaviour only
reject
```

Do not redesign working old behaviour merely because a new abstraction is possible.

Do not copy entire old packages into active source as a shortcut.

Do not require old behaviour to pass through retired Heavy V2 machinery.

---

## 20. Vertical-slice development

Each task or implementation branch should normally advance one primary vertical workflow. Parallel work is allowed only when branches have explicit boundaries, independent authorities, and a defined merge plan.

The default implementation path is:

```text
user workflow
GUI shell
application service
domain implementation
provider or store
Core async integration
result/report
vertical validation
```

A feature is complete only when the real user workflow works from start to finish.

For historical download, for example:

```text
select
preflight
confirm
execute
progress
cancel
persist
validate
report
```

Architecture tests and unit tests support this path. They do not replace it.

---

## 21. Testing priorities

Tests should be prioritised in this order:

1. Vertical workflow behaviour.
2. Domain rules and calculations.
3. Persisted-schema and migration behaviour.
4. Async progress, cancellation, failure, and shutdown.
5. Provider and external-adapter behaviour.
6. Runtime tracking and audit.
7. GUI smoke and visual behaviour.
8. Dependency and layering checks.
9. Specification or metadata consistency only where the specification or metadata is genuinely authoritative.

Do not create tests whose only purpose is proving that one handwritten descriptor agrees with another handwritten descriptor.

Do not delete failing tests unless the accepted task retires the behaviour or architecture they test.

Do not skip tests merely to obtain a green result.

When tests cannot run, state what is missing and what manual validation remains.

---

## 22. Python and code-quality rules

Code must be:

```text
clear
deterministic
typed where useful
testable
maintainable
explicit about failure
consistent with nearby accepted code
minimal without being cryptic
```

Use:

- explicit imports;
- type hints for public functions and important internal boundaries;
- private dataclasses for structured internal state;
- `pathlib.Path` for filesystem paths;
- existing logging and error mechanisms;
- early returns where they improve clarity;
- direct method calls inside an area when no hard boundary exists.

Avoid:

- hidden global state;
- circular imports;
- broad dumping-ground helper modules;
- silent fallbacks;
- mutable default arguments;
- broad exception swallowing;
- hardcoded filesystem paths unless part of accepted policy;
- unnecessary copying in hot paths;
- abstractions without a current consumer;
- public APIs for disposable internal models.

Hardcoded domain constants and parameters are acceptable when they are intentional, documented, tested, and not user-configurable requirements.

Hardcoding must not duplicate canonical naming, identity, validation, persistence, or financial rules across several modules.

---

## 23. Error handling

- Fail clearly.
- Include actionable context.
- Validate at boundaries.
- Allow defensive checks at several layers when their purposes differ.
- Keep one authoritative decision for each canonical fact.
- Do not continue after critical startup failure unless degraded mode is explicit.
- Do not catch `Exception` except at a boundary responsible for final error routing.
- Do not log an error and silently continue unless continuing is safe and intentional.
- Do not remove defensive checks merely to reduce apparent duplication.

GUI usability validation does not replace service validation.

Provider capability validation does not replace OHLCV quality validation.

Store safety validation does not replace domain validation.

---

## 24. Documentation and docstrings

Documentation must describe actual behaviour.

Use professional, technical, objective language in repository documentation and code comments.

Document:

```text
intent
invariants
canonical authority
side effects
failure modes
threading assumptions
persistence assumptions
compatibility requirements
non-obvious design decisions
```

Do not document obvious syntax.

Do not claim behaviour that code does not enforce.

Do not maintain detailed GUI object inventories as handwritten documentation.

Roadmaps should be concise workflow documents, not replicas of source code.

Update documentation when:

- public behaviour changes;
- a durable domain specification changes;
- a persisted schema changes;
- application lifecycle changes;
- an accepted architecture rule changes.

---

## 25. Dependency and environment rules

- Do not add or upgrade third-party dependencies without explicit approval.
- Prefer existing dependencies or the standard library when reasonable.
- Do not modify the user's Python environment unless requested.
- Do not install packages globally.
- Do not edit lock files unless dependency changes are part of the task.
- Do not use an optional dependency to avoid solving the accepted architecture correctly.

When proposing a dependency, report:

```text
name
purpose
existing alternative
installation impact
files requiring changes
```

---

## 26. File-handling rules

Do not:

- edit archives in place;
- edit binary files;
- touch virtual environments;
- modify user datasets unless explicitly requested;
- write temporary files into source directories;
- create backup/final/fixed duplicate source files;
- commit generated caches or runtime output;
- edit secrets or local environment files without scope.

Common generated paths must remain ignored:

```text
__pycache__/
.pytest_cache/
.mypy_cache/
.ruff_cache/
.venv/
venv/
build/
*.egg-info/
runs/
tmp/
```

A deletion task may remove large obsolete architecture only when explicitly named, dependency-ordered, archived where required, and validated.

---

## 27. Git safety

Read-only Git commands are allowed when available:

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

Do not run Git write or destructive commands unless the user explicitly authorises the exact command:

```text
git commit
git push
git pull
git reset
git clean
git checkout
git restore
git merge
git rebase
branch deletion
tag deletion
remote modification
```

Do not hide or overwrite the user's uncommitted changes.

Record baseline Git state before implementation when Git evidence is available.

---

## 28. Security and secrets

- Do not print or duplicate secrets.
- Do not commit API keys, tokens, passwords, cookies, credentials, or private URLs.
- Do not inspect secret files unless the task requires it.
- Do not weaken credential validation.
- Do not add network calls outside the accepted feature.
- Do not send project data to external services.

Trading, credential, and OpenAI integration require explicit security and confirmation policies before implementation.

---

## 29. Performance

Performance work must be evidence-driven.

When performance is in scope:

- identify the hot path;
- identify the current cost;
- remove repeated work before adding complexity;
- preserve behaviour;
- validate correctness before and after;
- report readability and memory trade-offs.

For chart and GUI hot paths:

- avoid unnecessary copying;
- avoid repeated full scans during interaction;
- avoid listener fan-out without measurement;
- avoid layout recalculation when only paint data changes;
- preserve deterministic rendering.

Do not optimise speculative future workloads.

---

## 30. Layering rules

General layering:

```text
GUI shell
    calls a presenter or controller

Presenter / controller
    translates user intent and presentation state

Application services
    coordinate workflows and execution policy

Domain services
    own financial and business meaning

Core
    supervises long-running execution and runtime state

Stores/adapters
    persist objects or communicate externally
```

Lower-level infrastructure must not depend on GUI implementation.

GUI must not contain persistence, provider, financial, analysis, backtest, or trading logic.

A presenter may coordinate presentation across several Areas. An application service may coordinate a cross-Area workflow. Neither becomes the owner of the participating Areas' domain rules.

Inside one cohesive area, direct imports and ordinary typed calls are preferred over unnecessary ports and adapters.

---

## 31. Domain-specific rules

### 31.1 OHLCV

- Downloaded data is not automatically validated data.
- Dataset identity must be canonical.
- Storage owns physical persistence and atomic commit mechanics.
- The OHLCV validator owns quality truth.
- Sidecars are durable schemas and must be validated.
- Repair must preserve provenance.

### 31.2 Financial Tools

- Financial Tool definitions and naming are canonical domain specifications/policies.
- `ft_specs` and `ft_naming` or their accepted successors must remain authoritative.
- Indicators, oscillators, and constructs remain modular and deterministic.
- GUI and Data Manager must not duplicate calculation semantics.
- Output naming and parameter meaning must not change casually.
- Do not maintain duplicate `Contract` and `Spec` representations unless each has a proven distinct consumer and generated relationship.

### 31.3 Research Suite

- Preserve approved old Research Suite behaviour unless the task explicitly changes it.
- The GUI owns chart interaction and presentation.
- Domain services own data, calculations, saved objects, and backtest mathematics.
- Long calculations must not block the GUI thread.

### 31.4 Data Manager

- Data Manager coordinates preparation, refinement, recipes, artifacts, and Analysis Database creation.
- Internal build stages use private models.
- Saved recipes, artifacts, collections, and database manifests use canonical durable schemas.
- Source lineage and identity must remain explicit.

### 31.5 Analysis and custom indicators

- Analysis owns interpretation and rule discovery.
- Analysis-derived custom indicators must be deterministic, versioned, explainable definitions.
- Historical, backtest, paper, and live execution must use the same accepted calculation semantics.

### 31.6 Backtesting and trading

- Backtest mathematics belongs outside GUI widgets.
- Fees, slippage, timing, position sizing, and leakage controls must be explicit.
- Paper trading precedes live eligibility.
- Risk approval and order execution require strict validated boundaries.
- Live trading actions require explicit user authorisation and audit.

---

## 32. Sandbox escalation

Request execution outside a restricted sandbox only when:

- sandbox execution failed;
- the command is necessary for validation;
- the exact command is narrow and read-only or test-only;
- file, network, and Git effects are disclosed.

Report:

```text
exact command
why it is required
whether it modifies files
whether it uses the network
whether it affects Git state
```

Do not request broad or session-wide escalation when one command is sufficient.

---

## 33. Final report format

Every implementation report must contain:

## Audit

- files and workflows inspected;
- confirmed findings;
- affected authorities/models/schemas;
- risk level.

## Update

- files changed;
- exact changes;
- reason;
- preserved behaviour;
- out-of-scope findings.

## Validation

- commands run;
- results;
- vertical workflow result where applicable;
- runtime/persistence/GUI result where applicable;
- failures;
- remaining risks.

## Original-Code Comparison

- files compared;
- whether the diff matches scope;
- unrelated changes found;
- compatibility intentionally preserved or changed.

If no files changed, state:

```text
No files were changed.
```

If validation is incomplete, state:

```text
Validation incomplete.
```

Then identify exactly what remains unverified.

---

## 34. Stop conditions

Stop and report when:

```text
the repository baseline is wrong or unexpectedly dirty
the task conflicts with accepted architecture
critical authority is unclear
a durable data meaning is unresolved
an allowed file boundary is insufficient
the task requires hidden scope expansion
old behaviour conflicts with the accepted outcome
a required dependency or runtime is unavailable
visual validation cannot be performed when required
tests prove the accepted design cannot work as written
```

Do not improvise around stop conditions by adding fallbacks, compatibility facades, duplicate services, or temporary production behaviour.

---

## 35. Forbidden behaviour

Codex must not:

- redesign the product without explicit instruction;
- recreate retired Heavy V2 doctrine;
- introduce public contracts for disposable internal models;
- add a Contract Registry, Object Map, or GUI metadata replica without an approved current requirement;
- place domain logic in GUI widgets;
- create Area-specific replacements for Core runtime systems;
- create parallel persistence, validation, calculation, or execution paths;
- hide broken state with silent fallbacks;
- weaken tests or validation;
- present shell/demo behaviour as real implementation;
- run unauthorised Git write commands;
- install dependencies without approval;
- modify secrets or datasets outside scope;
- claim success without validation.

---

## 36. What done means

A task is done only when:

- the accepted scope is implemented;
- the real requested behaviour works;
- the diff is bounded and reviewable;
- canonical domain meaning remains coherent;
- persisted compatibility is validated where applicable;
- critical state has no competing mutation path;
- relevant async, runtime, GUI, provider, or persistence behaviour is validated;
- required tests pass or limitations are explicit;
- visual acceptance is complete where required;
- no retired architecture was recreated;
- remaining risks are documented;
- the POST/PATCH package can be independently audited.

The governing engineering principle is:

> Build the complete Leonardo product using the simplest architecture that preserves correctness, asynchronous safety, runtime visibility, durable data, canonical authority over critical truth, and future AI control.
