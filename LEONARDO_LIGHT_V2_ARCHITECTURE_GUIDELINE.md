# Leonardo Light V2 Architecture Guideline

**Document ID:** `LEONARDO-LIGHT-V2-ARCHITECTURE-GUIDELINE-003`
**Version:** `2.4`
**Status:** Approved architecture baseline
**Architecture style:** Modular monolith
**Governing principle:** Minimum justified complexity
**Supersedes:** version 2.3 and earlier Light V2 architecture guidance

---

## 1. Purpose

Leonardo Light V2 is a modular desktop financial research, data-management, analysis, backtesting, real-time, and trading application.

It uses one shared asynchronous runtime for long-running and concurrent work while allowing several Areas and GUI windows to remain active simultaneously.

The architecture must remain simple enough for one owner and AI-assisted development to understand, modify, test, audit, and extend.

Leonardo must not recreate unnecessary:

- global contracts;
- duplicated metadata;
- handwritten GUI trees;
- registry layers that describe other registries;
- speculative compatibility systems;
- artificial ownership boundaries;
- parallel persistence or execution paths.

The engineering target is:

> **The simplest architecture that preserves correctness, asynchronous safety, persistence integrity, maintainability, runtime visibility, durable evidence, explicit user control, and future AI access.**

---

## 2. Product architecture

Leonardo is an evidence-to-decision platform.

Its broad product pipeline is:

```text
External market
    ↓
Connection/provider access
    ↓
Historical or real-time observations
    ↓
Canonical OHLCV persistence
    ↓
Validation, repair and acceptance
    ↓
Research / Financial Tool calculations
    ↓
Persisted analytical objects
    ↓
Analysis Databases
    ↓
Semantic market-state representation
    ↓
Rules, projections and temporal validation
    ↓
Backtesting and paper trading
    ↓
Risk-controlled execution
    ↓
Execution evidence
```

Architecture exists to support this pipeline. GUI shells, registries, runtime managers, automation surfaces, and audit systems support the product but are not the product itself.

---

## 3. Primary architectural model

Leonardo operates as a modular monolith.

```text
LeonardoApp
    ↓ composition

Core runtime
    +
Areas
    +
Stores/provider adapters
    +
GUI services
```

Normal interaction path:

```text
GUI intent
    ↓
Presenter / controller
    ↓
Area application service
    ↓
Direct domain call
or
Core-supervised long-running operation
    ↓
Domain services / providers / stores
    ↓
Result, progress, audit, persistence
    ↓ queued GUI update
Presenter
    ↓
GUI presentation
```

Simple operations do not pass through the asynchronous runtime merely for consistency.

---

## 4. Areas and Suites

### 4.1 Area

An **Area** owns financial or business behaviour.

Examples:

- Connection;
- OHLCV;
- Research;
- Data Manager;
- Analysis;
- Backtesting;
- Real-Time Environment;
- Trading.

An Area may contain application services, domain services, private models, provider adapters, stores, validation, reports, and tests.

Presenters/controllers/Qt adapters belong to GUI/application-adapter layers. They coordinate Areas without becoming owners of their business meaning.

### 4.2 Suite

A **Suite** is a user-facing GUI grouping.

Examples include Connection Suite, Research Suite, Data Manager Suite, Analysis Suite, and Trading Suite.

GUI navigation does not define code ownership.

---

## 5. Single composition root

`LeonardoApp` is the application composition root.

It constructs and connects:

- configuration;
- audit/logging;
- Core runtime;
- runtime registries/managers;
- Area application services;
- provider adapters;
- stores;
- GUI services;
- presenters;
- Main Window.

Windows must not construct hidden runtimes, event loops, provider transports, stores, domain services, or global registries.

Cross-Area GUI/application coordination may be wired at composition when it does not create a new business authority.

A narrow composition callback is preferable to a speculative global EventBus when only one concrete coordination path is required.

---

## 6. Core responsibilities

Core is the shared domain-neutral runtime foundation.

It owns:

- startup and ordered shutdown;
- background event-loop execution;
- long-running task lifecycle;
- progress and cancellation;
- external-process lifecycle;
- generic runtime identifiers;
- coarse connection summaries;
- window runtime summaries;
- application-wide discoverable actions where justified;
- operational logging;
- historical audit events;
- structured error routing;
- Runtime Manager snapshot aggregation.

Core does **not** own:

- provider semantics;
- exchange-specific behavior;
- websocket business meaning;
- financial calculations;
- OHLCV validation truth;
- persistence semantics;
- Recipe/Artifact meaning;
- Database construction rules;
- analysis/backtest mathematics;
- trading or risk decisions.

Core runs and observes work. It does not define what the work means.

---

## 7. Canonical Authority Rule

Strict NSRR remains retired.

The governing rule is:

> **Every critical truth, invariant, canonical identity, persisted object family, financial decision, and mutable runtime-state family has one canonical authority and one controlled write path. Shared workflow participation is normal. Competing authority is forbidden.**

Representative authorities:

| Critical truth/state | Canonical authority |
|---|---|
| Application lifecycle | `LeonardoApp` |
| Task lifecycle | `TaskManager` |
| Process lifecycle | `ProcessManager` |
| Detailed provider/API/websocket state | Connection Area |
| Coarse operational connection summary | `ConnectionRegistry` |
| Window runtime state | `WindowRegistry` |
| Historical audit evidence | `AuditLog` |
| Market-series identity | `MarketId` authority |
| OHLCV persistence | OHLCV Store |
| OHLCV validity | OHLCV Validator |
| Financial Tool definition | Financial Tools specification authority |
| Artifact naming | Canonical naming policy |
| Portable Recipe identity | Recipe identity/store authority |
| Managed Artifact lineage | Artifact persistence authority |
| Database persistence | Database Store |
| Risk approval | Risk Service |
| Order execution | Trading Gateway |

Shared participants may derive presentation, coordinate calls, perform defensive checks, cache read-only views, or emit audit evidence. They must not persist contradictory truth or create a second uncontrolled mutation path.

---

## 8. Persisted concepts and versioning

Minimal contracts do not mean minimal domain vocabulary.

Durable Leonardo concepts are explicit, typed, validated, and versioned where persisted.

Current durable families include, as implemented:

- audit evidence;
- canonical OHLCV sidecars;
- portable Recipes and Recipe Collections;
- managed Artifacts and Artifact Collections;
- Study Environments;
- Workspace Snapshots;
- Research Notebooks/annotations where persisted;
- Database Seeds;
- Database revision manifests;
- future Analysis/backtest/trading persisted evidence as those vertical workflows are implemented.

Do not maintain a permanent architecture census of every schema class/version. Each owning Area and its tests remain authoritative for the exact current schema set.

Additional versioned schemas are introduced only with real vertical workflows and genuine persistence requirements.

---

## 9. Data Manager product model

Data Manager coordinates durable preparation of accepted market evidence for Analysis.

The accepted flow is:

```text
Accepted OHLCV
├──→ Database Seed
│    └──→ immutable Database base revision
│
└──→ Financial Tool calculation
     ├──→ managed Artifact
     └──→ portable Recipe / Recipe Collection

Managed Artifacts / Artifact Collections
        ↓ explicit reviewed selection/import
immutable Database revisions
        ↓
Analysis
```

### 9.1 Recipe and Artifact independence

A Recipe describes how a result can be calculated. It is global and portable.

A managed Artifact is a persisted calculated object bound to concrete market/source evidence.

Artifacts are not runtime-owned by Recipes. Direct Artifact creation need not publish a portable Recipe.

Deleting a portable Recipe must not be blocked merely because an Artifact historically contains equivalent calculation semantics.

### 9.2 Independent collection families

Recipe Collections and Artifact Collections are independent.

Deleting one collection family must not be blocked by references from the other family unless a current canonical dependency explicitly requires it.

Deleting a collection does not automatically delete its members.

### 9.3 Database Seeds

A Database Seed is an immutable reviewed selection of accepted OHLCV source/range evidence used to establish a Database base.

Seed identity and provenance remain explicit.

### 9.4 Database ownership

A Database owns fixed explicitly reviewed content.

Adding an Artifact Collection imports the exact reviewed current Collection revision/output membership at that time.

Later edits to the source Collection do **not** automatically change Database membership.

Database membership changes only through an explicit reviewed Database operation.

### 9.5 Database revisions

Database history is immutable.

Existing historical schema versions remain readable. New semantic evolution uses the currently approved persisted version unless a real new persistence requirement justifies another version.

Do not create a new schema version merely for internal implementation convenience.

---

## 10. Data Manager currentness and update architecture

Currentness is derived authoritative reconciliation truth, not a second persistence family.

The lifecycle is:

```text
canonical OHLCV / Artifact / Collection evidence changes
    ↓
read-only reconciliation
    ↓
CURRENT / UPDATE AVAILABLE / BLOCKED / INVALID style presentation
    ↓
user reviews update
    ↓
explicit persistent mutation
```

Reconciliation must not silently mutate Artifacts, Collections, or Databases.

When relevant evidence changes while Data Manager is open, GUI/application composition may notify the existing Data Manager presenter so it can request reconciliation through the existing background mechanism.

Do not create a second watcher/currentness service when the existing reconciliation authority can be triggered.

Existing per-tool update policies, dependency ordering, overlap behavior, and full-recalculation fallbacks remain mathematical authority unless an explicitly accepted task changes them.

A universal fixed-backtrack rule is not architectural authority.

---

## 11. GUI policy

The GUI is a replaceable shell around Leonardo capabilities.

It owns windows, widgets, layouts, interaction, selection state, display formatting, enabled/disabled presentation, dialogs, progress presentation, visual errors/reports, appearance, navigation, and focus.

It does not own provider communication, task execution, financial calculations, OHLCV validation truth, persistence rules, Database construction, Analysis algorithms, backtest mathematics, trading logic, or risk decisions.

A GUI action expresses intent.

Local behavior such as switching tabs, filtering rows, clearing previews, or expanding trees does not require global action registration.

Application-wide `ActionRegistry` use is justified only for shared discovery/invocation, shortcuts, automation, audit policy, or future AI access.

---

## 12. Qt concurrency model

Leonardo uses one Qt GUI thread and one `QApplication` event loop.

Many windows may remain active simultaneously.

Short Qt operations remain synchronous on the GUI thread.

Long-running work must return control to Qt promptly and execute through Core or another accepted non-GUI execution authority.

Background work never mutates Qt widgets directly.

Use the existing queued signal/callback path back to the GUI thread.

Modal dialogs are reserved for short user decisions. Long-running workflows should normally remain non-modal.

Responsive windows do not imply conflicting resource mutations are safe. Resource authority and locking remain separate concerns.

---

## 13. GUI tracking and appearance

The live Qt object tree is the GUI source of truth.

Do not maintain a second handwritten GUI in JSON/TOML/roadmaps/parent maps.

Use stable identifiers for meaningful windows/actions/widgets and semantic appearance roles where appropriate.

Framework-generated visual atoms do not require governance identities.

A lightweight runtime GUI registry may expose live windows/widgets through weak references and read-only inspection. It must not own widget lifecycle.

---

## 14. Runtime tracking

Leonardo tracks operational systems that matter:

- application state;
- tasks;
- processes;
- provider/connection summaries;
- windows;
- meaningful user/AI actions;
- recent errors/warnings.

Each family has one owner/registry and exposes read-only snapshots.

Runtime Manager aggregates those snapshots for inspection. It must not become a second mutation authority.

Audit history and current runtime state remain distinct.

---

## 15. Logging and audit

Operational logging supports debugging, diagnostics, provider communication, performance, calculation failures, startup/shutdown, and development inspection.

Audit events preserve meaningful application history such as startup/shutdown, task settlement, persistence mutations, destructive operations, connection changes, and future trading/risk decisions.

Not every widget interaction is an audit event.

Logging/audit depth is proportional to operational and financial risk.

---

## 16. Contracts policy

Formal contracts are exceptional.

A formal contract is justified only when it protects a genuine hard boundary such as:

- a durable persisted format;
- an external wire format;
- a financially dangerous operation requiring stable validation/audit;
- a genuinely independent implementation boundary that ordinary local typed code cannot safely serve.

Thread crossing alone does not require a formal contract.

GUI-to-presenter calls, internal planner records, runtime rows, and ordinary Area-local DTOs should normally remain ordinary typed Python or local Protocols.

Every proposed formal contract must identify its owner, producer, independent consumer, boundary, versioning need, failure prevented, and why owner-local typed code is insufficient.

---

## 17. AI and development-agent separation

Leonardo's future product AI assistant and Codex used to develop Leonardo are different systems.

### Product AI
Future product AI must use the same application services/capability paths as the GUI. It must not manipulate Qt controls to perform business operations. High-risk capabilities enforce confirmation and safety inside Leonardo.

### Development Codex
Codex CLI is an external development agent operating on repository files under project governance. It is not part of Leonardo runtime architecture and does not use Leonardo's `ActionRegistry` to edit the application.

Do not mix these concepts.

---

## 18. Development and validation policy

Leonardo advances through complete vertical workflows.

Preferred sequence:

```text
user workflow
→ GUI shell where applicable
→ presenter/controller
→ application service
→ domain implementation
→ provider/store
→ Core async integration where needed
→ result/persistence
→ vertical validation
→ user acceptance
```

Tests prioritize:

1. vertical workflow behavior;
2. domain rules/calculations;
3. persistence and migration;
4. async progress/cancellation/failure;
5. provider adapters;
6. runtime tracking/audit;
7. GUI smoke/visual behavior;
8. dependency/layering checks.

A GUI-bearing task does not close solely because automated tests pass. Native/visual acceptance remains required where specified.

---

## 19. Complexity rule

Every abstraction must justify its current existence.

A new layer, registry, contract, adapter, schema, watcher, or event system must provide a concrete present benefit such as preventing competing truth, isolating an external dependency, preserving durable data, enabling safe long-running execution, supporting genuine multiple implementations, protecting a dangerous operation, or substantially improving testability.

Future possibility alone is insufficient.

Leonardo follows:

> **Minimum justified complexity.**

Not minimum structure.

Not maximum abstraction.

---

## 20. Practical decision checklist

Before adding architecture, ask:

- Is this a durable Leonardo concept? Define a canonical domain model/specification.
- Will it be persisted and loaded later? Use a versioned persisted schema.
- Does it cross a genuine hard boundary? Consider a formal contract.
- Is it temporary implementation data? Keep it internal.
- Is the same fact already authoritative elsewhere? Derive, do not duplicate.
- Does long-running work need supervision? Use Core/TaskManager.
- Is the operation trivial/fast? Call directly.
- Can ordinary typed Python solve it clearly? Use ordinary typed Python.
- Can composition wire this concrete cross-Area interaction without a global event system? Prefer composition.
- Is a proposed update automatic? Verify that persistent mutation still requires explicit user review where product policy requires it.

---

## 21. Final architectural statement

Leonardo Light V2 is a modular desktop application with one composition root, one shared Core runtime for long-running work, several cooperating Areas, and a replaceable Qt GUI shell.

Critical truths have canonical authorities and controlled mutation paths.

Durable concepts are explicitly modeled and versioned when persisted.

Recipes, managed Artifacts, collection families, Database Seeds, and Database revisions retain their accepted independent semantics.

Databases own fixed reviewed membership. Reconciliation discovers currentness; users explicitly authorize persistent updates.

The live Qt object tree is not duplicated in handwritten metadata.

The future product AI and GUI use the same application capabilities, while development Codex remains external repository tooling.

Development proceeds through bounded complete vertical slices with independent audit and native acceptance.

The governing principle remains:

> **Build the complete Leonardo product using the simplest architecture that preserves correctness, asynchronous safety, runtime visibility, durable evidence, canonical authority over critical truth, explicit persistence control, and future AI access.**
