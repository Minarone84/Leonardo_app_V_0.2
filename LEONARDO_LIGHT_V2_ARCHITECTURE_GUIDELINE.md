# Leonardo Light V2 Architecture Guideline

**Document ID:** `LEONARDO-LIGHT-V2-ARCHITECTURE-GUIDELINE-003`  
**Version:** `2.3`  
**Status:** Approved architecture baseline  
**Architecture style:** Modular monolith  
**Governing principle:** Minimum justified complexity  
**Supersedes:** strict NSRR, contract-heavy internal architecture, duplicated GUI metadata and handwritten GUI roadmaps

---

## 1. Purpose

Leonardo Light V2 is a modular desktop financial research and trading application with one shared asynchronous runtime for long-running and concurrent work.

It must allow several functional Areas and GUI windows to remain active simultaneously while sharing:

- application lifecycle;
- background task execution;
- process tracking;
- provider and connection status;
- window tracking;
- logging;
- audit;
- error routing;
- runtime inspection;
- safe shutdown.

The architecture must remain simple enough for one owner and AI-assisted development to understand, modify, test and extend.

Leonardo must not introduce unnecessary:

- global contracts;
- duplicated metadata;
- manually reproduced GUI trees;
- registry layers that describe other registries;
- speculative compatibility systems;
- artificial ownership boundaries.

The engineering target is:

> **The simplest architecture that preserves correctness, asynchronous safety, persistence integrity, maintainability, necessary runtime visibility and future AI control.**

---

## 2. Product architecture

Leonardo is an evidence-to-decision platform.

Its primary pipeline is:

```text
External market
    ↓
Connection and provider access
    ↓
Historical or real-time observations
    ↓
OHLCV persistence
    ↓
Validation, repair and acceptance
    ↓
Financial-tool calculations
    ↓
Artifacts and recipes
    ↓
Analysis Database
    ↓
Semantic market-state representation
    ↓
White-box rules and projections
    ↓
Temporal validation
    ↓
Backtesting and paper trading
    ↓
Risk-controlled execution
    ↓
Execution evidence
```

Architecture exists to support this pipeline.

The GUI, downloader, runtime manager, action registry and audit system are supporting mechanisms. They are not the product.

---

## 3. Primary architectural model

Leonardo shall operate as a modular monolith.

```text
LeonardoApp
    ↓ composition

Core runtime
    +
Areas
    +
Stores and provider adapters
    +
GUI services
```

The user interaction path is:

```text
GUI control
    ↓ user intent

Presenter / controller
    ↓ workflow coordination

Area application service
    ↓

Direct domain call
or
Core-supervised background operation
    ↓

Domain services, providers and stores
    ↓

Operation handle, progress, result and audit
    ↓ queued GUI update

Presenter / controller
    ↓

GUI presentation
```

Simple operations do not pass through the asynchronous runtime merely for architectural consistency.

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

An Area may contain:

- application services;
- domain services;
- private models;
- provider adapters;
- stores;
- validation;
- reports;
- tests.

Presenters, controllers, view adapters and Qt binding code belong to the GUI or application-adapter layer. They may coordinate an Area but do not become owners of its business behaviour.

### 4.2 Suite

A **Suite** is the user-facing GUI grouping through which an Area is presented.

Examples:

- Connection Suite;
- Research Suite;
- Data Manager Suite;
- Analysis Suite;
- Trading Suite.

The GUI navigation structure must not define the application’s code ownership.

An Area may expose several windows. A window may coordinate several Areas through an application workflow without becoming an owner of their business rules.

---

## 5. Single composition root

`LeonardoApp` is the only application composition root.

It constructs and connects:

- configuration;
- audit log;
- Core runtime;
- runtime managers and registries;
- Area application services;
- provider adapters;
- stores;
- GUI services;
- presenters;
- Main Window.

Windows must not construct hidden:

- Core runtimes;
- event loops;
- provider transports;
- stores;
- domain services;
- global registries.

A window receives the presenter or services it requires through explicit construction or binding.

---

## 6. Core responsibilities

The Core is the shared, domain-neutral runtime foundation.

It owns:

- application startup and shutdown coordination;
- the background event loop;
- long-running task lifecycle;
- task progress and cancellation;
- external process lifecycle;
- generic runtime identifiers;
- coarse provider and connection runtime summaries;
- window runtime summaries;
- registration and invocation of application-wide discoverable actions;
- coherent logging;
- persisted audit events;
- structured error routing;
- Runtime Manager snapshot aggregation;
- safe and ordered shutdown.

The Core does **not** own:

- provider capability rules;
- exchange-specific request semantics;
- websocket business behaviour;
- financial calculations;
- OHLCV validation;
- persistence rules;
- database construction;
- analysis algorithms;
- backtest mathematics;
- trading decisions;
- risk decisions.

The Core runs and observes work. It does not define what that work means.

---

## 7. Area responsibilities

Each Area owns its own business behaviour and critical decisions.

Areas use the Core for:

- long-running execution;
- task identity;
- progress delivery;
- cancellation;
- generic runtime tracking;
- errors;
- logging;
- audit;
- application shutdown coordination.

Areas do not recreate their own:

- event loops;
- generic task managers;
- process managers;
- global logging systems;
- global window tracking;
- application shutdown systems.

Several Areas may operate simultaneously.

Example:

```text
Download running
Research window active
Runtime Manager refreshing
Appearance settings changing
Another provider connection receiving data
```

The Core must support this without one Area blocking or corrupting another.

---

## 8. Canonical Authority Rule

Strict NSRR is retired.

The replacement rule is:

> **Every critical truth, invariant, canonical identity, persisted object family, financial decision and mutable runtime-state family must have one canonical authority and one controlled write path. Shared workflow participation is normal. Competing authority is forbidden.**

### 8.1 Canonical authorities

| Critical truth or state | Canonical authority |
|---|---|
| Application lifecycle | `LeonardoApp` |
| Task lifecycle | `TaskManager` |
| Process lifecycle | `ProcessManager` |
| Provider/API/websocket detailed state | Connection Area |
| Coarse operational connection summary | `ConnectionRegistry` |
| Window runtime state | `WindowRegistry` |
| Registered application-wide action | `ActionRegistry` |
| Historical audit evidence | `AuditLog` |
| Canonical market identity | Naming/Data identity authority |
| Provider capability | Connection provider adapter/configuration |
| OHLCV persistence | OHLCV Store |
| OHLCV validation truth | OHLCV Validator |
| Financial Tool definition | Financial Tools specification authority |
| Artifact naming | Canonical naming policy |
| Database persistence | Database Store |
| Risk approval | Risk Service |
| Order execution | Trading Gateway |
| Position state | Position Manager |
| Credentials | Credential Store |

### 8.2 Allowed shared participation

Other components may:

- participate in workflows;
- read authoritative state;
- perform defensive input checks;
- derive display state;
- cache read-only summaries;
- emit audit events;
- reuse shared utilities;
- coordinate calls between authorities.

They must not:

- persist contradictory truth;
- independently redefine a critical business rule;
- bypass the controlled write path;
- treat derived state as canonical;
- create a parallel implementation of the same critical decision.

### 8.3 Layered validation

Validation may exist at several layers:

```text
GUI:
fast usability checks

Application service:
authoritative request validation

Provider:
external capability validation

Store:
persistence safety validation

Domain validator:
canonical domain truth
```

Repeated checks are acceptable when only one layer owns the canonical result.

---

## 9. GUI policy

The GUI is a replaceable shell around Leonardo’s capabilities.

The GUI owns:

- windows;
- widgets;
- layouts;
- user interaction;
- local selection state;
- display formatting;
- enabled and disabled control state;
- dialogs;
- progress presentation;
- visual errors and reports;
- appearance;
- navigation;
- focus and selection context.

The GUI does not own:

- provider communication;
- background task execution;
- financial calculations;
- OHLCV validation truth;
- persistence rules;
- database construction;
- analysis algorithms;
- backtest mathematics;
- trading logic;
- risk decisions.

A GUI action expresses intent.

Normal local interaction uses the direct path:

```text
Start Download button
    ↓
Download presenter
    ↓
Connection application service
    ↓
Core-supervised background operation, when required
```

`ActionRegistry` is used only when an operation needs application-wide discovery, invocation, auditing, shortcuts, automation or future AI access. Local presentation behaviour such as changing tabs, clearing a preview or expanding a tree does not require registration.

A window may be redesigned or replaced without changing the underlying operation.

---

## 10. Synchronous GUI calls and concurrent windows

Leonardo uses one Qt GUI thread and one `QApplication` event loop.

Many windows may remain open and responsive simultaneously.

Short GUI operations execute synchronously on the GUI thread:

```python
window.show()
window.raise_()
window.activateWindow()
widget.setVisible(True)
widget.setFont(font)
label.setText(message)
```

These calls complete quickly and do not prevent other windows from working.

Qt processes events sequentially and rapidly for all windows:

```text
mouse event in Main Window
paint Download Manager
keyboard input in Research
progress update in Runtime Manager
resize Trading window
```

To the user, the windows operate concurrently.

### 10.1 What must not run on the GUI thread

Long-running work must not execute directly from a widget callback.

Bad:

```python
def _on_start_clicked(self) -> None:
    candles = download_all_candles()
    save_csv(candles)
    validate_dataset()
```

This freezes every window.

Correct:

```text
button click
→ short synchronous presenter call
→ application service
→ optional Core-supervised background operation
→ return to Qt event loop
```

### 10.2 Concurrent operations

Several windows may start or observe several jobs:

```text
Download Manager → OHLCV download
Data Manager → artifact calculation
Analysis Suite → analysis job
Runtime Manager → observes all jobs
```

The Core supervises these jobs outside the GUI thread.

### 10.3 GUI update rule

Background code must never mutate Qt widgets directly.

Use:

```text
Core callback
→ queued Qt signal
→ presenter
→ window update on GUI thread
```

### 10.4 Modal windows

Modal dialogs are allowed only for short user decisions such as:

- download confirmation;
- destructive deletion;
- live order confirmation;
- credential changes.

Long-running progress windows should normally be non-modal so unrelated workflows remain usable.

### 10.5 Resource conflicts

Responsive windows do not imply that conflicting operations are safe.

Example:

```text
Download writes BTCUSDT 1h
Maintenance attempts to repair the same dataset
```

Storage locks, validation and controlled write paths prevent the conflict.

Window concurrency and resource authority are separate concerns.

---

## 11. GUI-first vertical development

Leonardo may use a shell-first process. Each task or implementation branch should normally advance one primary vertical workflow at a time. Parallel work is allowed when branches have explicit boundaries, independent authorities and a defined merge plan.

For each feature:

1. Audit the old working behaviour where available.
2. Define the visible user workflow.
3. Build or correct the visual shell.
4. Define empty, ready, running, failed, cancelled and completed states.
5. Assign stable identifiers to meaningful controls.
6. Add a thin presenter or controller.
7. Implement the application and domain services.
8. Connect long-running work through Core.
9. Complete persistence or provider integration.
10. Validate the real workflow end to end.
11. Obtain user acceptance.
12. Move to the next feature.

A shell must not contain fake business logic that becomes permanent by accident.

A feature is not complete because its window exists.

Do not build dozens of empty windows before proving one complete workflow.

---

## 12. Presenter and controller policy

A significant workflow should use one small presenter or controller.

Example:

```python
class DownloadManagerPresenter:
    def __init__(
        self,
        view: DownloadManagerView,
        service: DownloadApplicationService,
    ) -> None:
        ...
```

The presenter may:

- read user intent from the view;
- call the application service;
- receive an operation or job handle;
- associate an operation with the window for presentation;
- translate progress and results into view operations;
- display errors.

The application service decides whether an operation is direct or asynchronous. It owns workflow coordination, task submission policy, task naming, cancellation policy, resource locking and audit correlation. `TaskManager` remains the canonical owner of task lifecycle.

The presenter must not:

- calculate provider ranges;
- paginate exchanges;
- write files;
- validate OHLCV truth;
- calculate financial results;
- own canonical task state.

Use a small local `Protocol` when it materially improves testing.

Local presenter interfaces are ordinary internal Python, not formal public contracts.

---

## 13. GUI tracking and appearance

The live Qt object tree is the GUI source of truth.

Leonardo must not maintain a second handwritten copy of the GUI in:

- TOML;
- JSON;
- roadmap metadata;
- parent maps;
- object-family descriptors.

### 13.1 Stable identities

Assign stable IDs to meaningful objects:

- windows;
- interactive controls;
- editable widgets;
- tables;
- important status and report surfaces;
- custom interactive regions;
- actions.

Use Qt `objectName`:

```python
table.setObjectName("download_manager.dataset_table")
```

Use action IDs:

```python
button.setProperty("action_id", "download.execute")
```

### 13.2 Appearance roles

Use semantic appearance roles:

```python
table.setProperty("appearance_role", "data_table")
button.setProperty("appearance_role", "primary_action")
```

### 13.3 Editable properties

Objects that may be customized declare supported properties:

```python
table.setProperty(
    "editable_properties",
    (
        "font_family",
        "font_size",
        "font_weight",
        "foreground",
        "background",
        "row_height",
    ),
)
```

### 13.4 Proportional traceability

Do not govern framework-generated or irrelevant visual atoms.

Stable IDs are not required for:

- Qt-created internal viewports;
- automatic scrollbars;
- delegates;
- temporary paint objects;
- ordinary spacers;
- decorative labels that are never inspected, edited, automated or audited.

### 13.5 Runtime GUI registry

A lightweight GUI registry may discover or register live objects using:

- `QObject.objectName()`;
- Qt class name;
- owning window;
- dynamic properties;
- visibility and enabled state;
- weak references.

The registry must not own widget lifecycle.

It may provide:

- live window count;
- live widget count by type;
- objects by window;
- registered actions;
- editable objects;
- duplicate ID detection;
- unnamed interactive-control detection.

---

## 14. Runtime tracking

Leonardo tracks operational systems that matter.

Required runtime families:

- application state;
- tasks;
- processes;
- operational provider/API requests where useful;
- provider connections;
- websocket channels;
- windows;
- meaningful user and AI actions;
- recent errors and warnings.

A general multi-user session service is not required today.

Use one local actor identity until an actual multi-user, remote-access or external-assistant authentication requirement exists.

Each runtime family has one manager or registry:

```text
TaskManager
ProcessManager
ConnectionRegistry
WindowRegistry
AuditLog
```

`ActionRegistry` is included when application-wide discoverable actions are enabled. It is not required for local widget behaviour.

Each owner exposes a read-only snapshot.

Runtime Manager combines those snapshots for inspection.

Runtime Manager does not own or mutate runtime state.

Derived rows and summaries must be disposable and regenerable.

---

## 15. Logging and audit

Leonardo uses one coherent logging architecture.

### 15.1 Operational logging

Used for:

- debugging;
- diagnostics;
- provider communication;
- calculation failures;
- performance information;
- startup and shutdown;
- development inspection.

### 15.2 Audit events

Used for meaningful application history:

- application startup and shutdown;
- important user or AI actions;
- task submission and completion;
- task failure and cancellation;
- process launch and termination;
- connection and websocket state changes;
- destructive operations;
- persistence operations;
- trading and risk decisions.

Audit events include relevant identifiers:

- timestamp;
- actor;
- window;
- action;
- task;
- process;
- connection;
- domain subject;
- correlation ID;
- severity;
- message;
- structured details.

Not every widget interaction requires an audit event.

Logging and audit depth must be proportional to operational and financial risk.

---

## 16. Contracts policy

Contracts are exceptional.

At the initial Light V2 reset baseline, the only retained public versioned persisted schemas are:

```text
AuditEventV1
OHLCVSidecarV1
```

The shared canonical market-series identity is:

```text
MarketId
```

`MarketId` is the frozen canonical name for the shared immutable value object containing:

```text
exchange
market_type
symbol
timeframe
```

Do not create a parallel `OHLCVDatasetIdentity` type or compatibility alias. Persisted OHLCV schemas reference `MarketId`; Area-local models may compose it without redefining market identity.

Additional versioned schemas are introduced only when their corresponding vertical workflow is implemented and persistence compatibility genuinely requires them.

### 16.1 Contract admission

A future formal contract may be introduced only when it protects:

- a persisted versioned format;
- an external wire format;
- a financially dangerous operation requiring stable validation;
- a genuine independently implemented boundary that cannot safely use local typed code.

Thread crossing alone does not require a formal contract.

A provider adapter boundary may use a local `Protocol`.

A GUI-to-presenter call may use direct typed Python.

A cross-Area application DTO may remain owned by the producing Area unless independent version stability is genuinely required.

### 16.2 Required justification

Every proposed formal contract must state:

```text
Owner
Producer
Independent consumer
Boundary crossed
Versioning requirement
Failure prevented
Why owner-local typed code is insufficient
```

If these cannot be stated clearly, do not create the contract.

### 16.3 Do not create formal contracts for

- temporary GUI state;
- preflight table rows;
- internal planner stages;
- local service results;
- pagination cursors;
- internal provider page models;
- database-build intermediate data;
- display-only summaries;
- Runtime Manager rows;
- process or window registry records;
- one internal service calling another;
- AI capabilities that do not yet exist.

Use ordinary typed Python:

- classes;
- private dataclasses;
- enums;
- local Protocols;
- method signatures;
- direct imports;
- documentation;
- validation;
- tests.

---

## 17. Domain specifications and persisted schemas

Minimal contracts do not mean unstructured data.

Important Leonardo concepts remain explicit, typed, validated and documented.

Examples:

- Financial Tool specifications;
- Financial Tool naming policies;
- market identities;
- OHLCV sidecars;
- artifact definitions;
- artifact recipes;
- recipe collections;
- Study Environments;
- Workspace Snapshots;
- Analysis Database manifests;
- analysis reports;
- custom trading indicators;
- backtest reports;
- trading records.

Classify structures correctly:

| Structure | Purpose |
|---|---|
| Domain specification | Defines what an important Leonardo concept means |
| Canonical policy | Defines deterministic rules such as naming |
| Persisted schema | Defines data saved and loaded later |
| Formal boundary contract | Defines an exceptional stable hard boundary |
| Internal model | Supports implementation and may change freely |
| Runtime snapshot | Read-only inspection output |
| Report model | Structured analytical or validation result |
| Configuration schema | Defines appearance or application settings |

The simplification target is disposable workflow plumbing, not Leonardo’s durable vocabulary.

---

## 18. Concurrency and multi-Area operation

Leonardo must support multiple Areas and operations simultaneously.

Examples:

- historical download while Research remains usable;
- database construction while another chart is inspected;
- several provider connections remaining active;
- Runtime Manager inspecting active jobs;
- appearance settings changing without affecting background work.

Long-running work must:

- execute outside the GUI thread;
- have a unique task identity;
- report progress;
- support cancellation where possible;
- produce a terminal result;
- route errors coherently;
- settle cleanly during shutdown.

Trivial synchronous actions remain direct:

- opening a window;
- changing a font;
- focusing a widget;
- reading a local setting;
- updating display text;
- taking a lightweight snapshot.

---

## 19. Application actions and future AI control

Only operations that require application-wide discovery, invocation, auditing, shortcuts, automation or future AI access are exposed through `ActionRegistry`.

Examples:

```text
window.open
window.focus
runtime.status
task.cancel
appearance.adjust
download.execute
dataset.delete
database.build
backtest.run
trading.order.submit
```

Local GUI behaviour does not require registration. Examples include:

```text
select table row
expand tree node
clear preview
switch tab
change local filter
resize panel
```

The registry initially owns only:

- stable action ID;
- invocation handler or application-service target;
- optional label;
- optional risk level;
- optional confirmation policy;
- audit policy where required.

Argument validation, enabled-state truth and business rules normally remain with the application service or canonical domain authority.

The registered invocation path is:

```text
GUI, menu, shortcut or AI request
    ↓
ActionRegistry
    ↓
application service
    ↓
optional Core-supervised background operation
    ↓
result and audit
```

GUI and AI must not receive separate implementations.

The AI assistant must not manipulate Qt controls to perform business operations.

It may inspect or focus GUI objects for navigation and appearance tasks.

High-risk actions require explicit confirmation and safety policy:

- destructive dataset changes;
- credential changes;
- paper-order submission;
- live-order submission;
- risk-limit changes.

No speculative AI contract family is created before a real external assistant interface exists.

---

## 20. Development and validation policy

Leonardo is developed through complete vertical slices.

For each feature:

```text
GUI shell
→ presenter
→ application service
→ domain implementation
→ optional Core job
→ persistence or external adapter
→ result
→ vertical validation
```

A feature is accepted only when the real user workflow works from beginning to end.

Tests should prioritize:

1. vertical workflow behaviour;
2. domain rules and calculations;
3. persistence and compatibility;
4. asynchronous progress, cancellation and failure;
5. provider adapters;
6. GUI smoke behaviour;
7. architecture dependency checks.

Tests must not primarily prove that metadata agrees with other metadata.

A refusal or blocked operation backed by correct evidence is a successful result.

---

## 21. Complexity rule

Every abstraction must justify its existence.

A new layer, registry, contract, adapter or schema must provide a concrete current benefit such as:

- preventing competing critical truth;
- isolating an external dependency;
- preserving durable data;
- enabling long-running execution safely;
- supporting multiple genuine implementations;
- protecting a financially dangerous operation;
- substantially improving testability.

Future possibility alone is insufficient.

Leonardo follows:

> **Minimum justified complexity.**

Not minimum structure.

Not maximum abstraction.

---

## 22. Practical decision checklist

Before adding architecture, ask:

### Does this represent a durable Leonardo concept?

If yes, define a canonical domain model or specification.

### Will it be saved and loaded later?

If yes, define a versioned persisted schema.

### Does it cross a real external wire format or financially dangerous boundary?

If yes, consider a formal contract.

### Is it temporary implementation data?

Keep it internal.

### Is the same fact already represented elsewhere?

Choose one canonical source and derive the rest.

### Does the GUI need to edit or track it?

Use stable IDs, runtime registration and appearance roles.

### Does Runtime Manager need to display it?

Expose a read-only snapshot from the existing authority.

### Does long-running work need supervision?

Use TaskManager/CoreRunner.

### Is the operation trivial and fast?

Call it directly.

### Can ordinary typed Python solve the problem clearly?

Use ordinary typed Python.

---

## 23. Final architectural statement

Leonardo Light V2 is a modular desktop application with one composition root, one shared Core runtime for long-running work and several cooperating Areas.

The Core supplies:

- lifecycle;
- long-running concurrency;
- task and process supervision;
- coarse connection and window tracking;
- application-wide registered actions, where justified;
- errors;
- logging;
- audit;
- runtime inspection;
- safe shutdown.

The Areas supply:

- Connection;
- OHLCV;
- Research;
- Data Management;
- Analysis;
- Backtesting;
- Real-Time;
- Trading capabilities.

The GUI remains a replaceable presentation shell.

Short GUI operations run directly on the Qt thread.

Long-running operations run through Core and return updates through queued GUI signals.

Strict NSRR is retired.

It is replaced by canonical authority over critical truths and controlled mutation of important state.

At the initial Light V2 reset baseline, public versioned persisted schemas are limited to:

```text
AuditEventV1
OHLCVSidecarV1
```

with:

```text
MarketId
```

as the shared canonical market-series value object. Additional schemas are introduced only with their corresponding vertical workflows.

Important domain objects and persisted formats remain precisely defined, typed, validated and documented.

The GUI object tree is discovered from live Qt objects, not duplicated in handwritten metadata.

GUI and AI use the same application services. Operations that require shared discovery or invocation use the same registered application actions.

Development proceeds through complete vertical slices.

The governing principle is:

> **Build the complete Leonardo product using the simplest architecture that preserves correctness, asynchronous safety, runtime visibility, durable evidence, canonical authority over critical truth and future AI control.**
