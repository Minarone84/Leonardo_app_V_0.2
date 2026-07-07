# Leonardo V2 Core Manifesto

## 1. Purpose

Leonardo V2 Core is the foundation of the application.

Its purpose is to provide a stable, observable, asynchronous, contract-backed runtime on which all Leonardo areas can operate independently while remaining coordinated, traceable, auditable, and safe.

Leonardo is not a collection of isolated windows and scripts. Leonardo is a structured system made of identifiable objects, explicit ownership boundaries, contracts, metadata, runtime state, audit history, and controlled interactions.

The Core exists so every meaningful action, object, process, connection, task, and result can be known, inspected, authorized, traced, audited, and reasoned about.

The final goal is a modular “Lego-like” architecture where each area can evolve independently without creating shared responsibilities, hidden dependencies, or untraceable behavior.

---

## 2. Core Identity

The Core is not a domain suite.

The Core does not replace the Research Suite, Data Manager Suite, Analysis Suite, Trading Suite, or Connection / Provider layer.

The Core is the runtime, policy, state, audit, permission, task, operation, lifecycle, contract, and traceability foundation that allows those areas to run safely.

The Core supervises, identifies, authorizes, schedules, tracks, audits, cancels, and exposes runtime truth.

The suites own their own domain behavior.

The Core must remain independent from GUI layout, rendering, chart panes, visual style, domain-specific workflows, storage-writing semantics, trading logic, analysis logic, and data-manager business rules.

---

## 3. Core Scope

The Core owns:

* runtime lifecycle;
* session and user policy;
* permission definitions and authorization checks;
* current runtime state;
* historical audit truth;
* task supervision;
* semantic operation lifecycle;
* process tracking and controlled cleanup;
* connection and websocket runtime tracking;
* service registration and lifecycle classification;
* contract registration and validation;
* error routing;
* asynchronous command execution boundary;
* result, progress, cancellation, and error metadata;
* runtime snapshots;
* read-only runtime inspection;
* common traceability rules;
* common object identity and relationship policy.

The Core does not own:

* GUI layout;
* GUI widgets;
* chart rendering;
* chart pane logic;
* domain-specific suite behavior;
* artifact calculation rules;
* database materialization rules;
* analysis rules;
* trading rules;
* provider adapter implementation;
* websocket transport implementation;
* storage writer behavior;
* user-facing confirmation dialogs;
* visual style decisions;
* domain object mutation outside its owning service.

---

## 4. Fundamental Ownership Rule

Every responsibility must have exactly one owner.

No shared responsibilities are allowed.

A system component may observe another component through a read-only boundary, but it must not mutate state it does not own.

The ownership rule is:

* `StateStore` owns current runtime state mutation.
* `AuditLog` owns historical truth.
* `TaskManager` owns task lifecycle.
* `OperationRegistry` owns semantic operation lifecycle.
* `UserPolicy` owns authorization decisions.
* `SessionManager` owns current session identity.
* `CoreRuntimeBridge` owns GUI/caller-to-Core async command submission.
* `CoreRunner` owns the persistent Core async runtime loop.
* `RuntimeManagerBackend` owns read-only runtime inspection only.
* GUI owns display, input, layout, and local Qt lifetime only.
* Each suite owns its own domain services, domain contracts, read models, persistence semantics, and object families.

No manager, registry, window, or suite may silently take ownership of another layer’s responsibility.

---

## 5. Runtime Truth and Historical Truth

Leonardo separates runtime truth from historical truth.

Runtime truth answers:

* What exists now?
* What is currently running?
* What is open?
* What is active?
* What is the current state?

Historical truth answers:

* What happened?
* Who requested it?
* What action triggered it?
* What object changed?
* What failed?
* What completed?
* What was denied?
* What was cancelled?

Runtime truth belongs to `StateStore`.

Historical truth belongs to `AuditLog`.

Runtime Manager and future object maps may inspect both, but they must not become controllers.

---

## 6. Async Core Runtime

Leonardo must remain fully asynchronous where long-running work is involved.

Long-running Core work must not block the GUI thread.

The Core runtime path is:

```text
caller intent
→ CoreRuntimeBridge
→ command metadata
→ permission gate
→ operation identity
→ CoreRunner
→ TaskManager
→ domain service
→ progress / result / error / cancellation
→ StateStore / AuditLog
→ read-only inspection
```

The Core async runtime must support:

* thread-safe submission;
* operation identity;
* task identity;
* correlation identity;
* permission gating before execution;
* progress reporting;
* result reporting;
* structured errors;
* cancellation routing;
* task settlement;
* shutdown cleanup;
* audit emission;
* read-only runtime inspection.

The Core runtime must remain domain-neutral. It may execute submitted handlers, but it must not contain Download, Data Manager, Analysis, Research, Trading, or provider-specific behavior.

---

## 7. Command, Query, Progress, Result, Error, and Cancellation Contracts

All meaningful work must be described through contracts.

Core runtime contracts must describe:

* commands;
* queries;
* submissions;
* progress events;
* results;
* errors;
* cancellation requests;
* cancellation results;
* runtime metadata;
* permission metadata;
* operation metadata;
* task metadata;
* correlation metadata.

Contracts must be stable, explicit, versioned where appropriate, and JSON-safe where intended.

Contracts are not decoration. They are the boundary language between areas.

If an operation cannot be described, authorized, traced, cancelled, and audited through contracts, it is not ready for Core-managed execution.

---

## 8. Permission Policy

Authorization is Core-owned policy.

The GUI may expose buttons and actions, but it must not own permission rules.

Every meaningful action or command should be able to declare:

* required permission;
* originating action;
* originating window;
* target domain;
* target object;
* user/session identity;
* denied reason when rejected.

Denied commands must not create tasks.

Denied commands must not create running operations.

Denied commands must produce structured denial results and audit facts according to policy.

Permissions must cover Core/runtime boundaries and future suite boundaries, including runtime, audit, services, tasks, operations, processes, connections, settings, download, research, data manager, analysis, and trading.

Permission definitions do not imply domain behavior. They define gates.

---

## 9. Runtime Manager Boundary

Runtime Manager is an inspector.

Runtime Manager is not a controller.

Runtime Manager must remain:

* read-only;
* snapshot-based;
* not a task executor;
* not an operation canceller;
* not a settings owner;
* not a domain service;
* not a lifecycle owner;
* not a hidden command surface.

Runtime Manager may show:

* current app state;
* services;
* tasks;
* operations;
* processes;
* connections;
* websocket channels;
* windows;
* actions;
* contracts;
* audit summaries;
* download read models;
* suite read models where future providers expose them.

Runtime Manager must not mutate those objects.

---

## 10. GUI Boundary

The GUI is a shell, an input surface, and a display layer.

The GUI owns:

* windows;
* controls;
* layout;
* visual metadata;
* local Qt object lifetime;
* user input;
* display formatting;
* confirmation dialogs;
* report rendering;
* action trigger surfaces.

The GUI does not own:

* Core execution;
* task lifecycle;
* operation lifecycle;
* permissions;
* download logic;
* adapter logic;
* storage writing;
* artifact calculation;
* database materialization;
* analysis logic;
* trading logic;
* connection lifecycle;
* websocket transport;
* validation;
* repair;
* persistence policy.

Windows may collect intent.

Windows may render state.

Windows may expose actions.

Windows must not become domain services.

---

## 11. Suite Interaction with Core

All major Leonardo areas run on Core.

The major areas are:

* Research Suite;
* Data Manager Suite;
* Analysis Suite;
* Trading Suite;
* Connection / Provider layer.

Each area must interact with Core through explicit boundaries.

A suite may ask Core to:

* submit a command;
* perform a query;
* register runtime-visible objects;
* report progress;
* emit results;
* request cancellation;
* register contracts;
* expose read models;
* emit audit facts;
* use permission gates;
* expose runtime summaries;
* participate in lifecycle where appropriate.

A suite must own:

* its domain objects;
* its domain services;
* its object family metadata;
* its persistence rules;
* its validation rules;
* its read models;
* its command/query handlers;
* its relationship rules;
* its domain-specific errors;
* its domain-specific reports.

Suites may interact with each other only through explicit contracts, object references, read models, events, or approved services.

No suite may silently reach into another suite’s private state.

---

## 12. The Traceable Object System

Leonardo must become a traceable object system.

Every meaningful thing should be identifiable, inspectable, and traceable.

This does not mean every object shares the same rigid schema.

It means every object has a common trace envelope plus a family-specific legend.

The common trace envelope should answer:

* What is this object?
* What kind of object is it?
* Who owns it?
* What is its stable ID?
* What schema/version describes it?
* Is it runtime, persistent, temporary, GUI, data, connection, or domain?
* What is its lifecycle status?
* Where is its metadata?
* What objects does it depend on?
* What objects depend on it?
* What actions can affect it?
* What permissions apply?
* What audit events mention it?
* How can it be inspected?
* Who is allowed to mutate it?

Each object family then defines its own legend.

The legend defines the family-specific fields that make sense for that object type.

A window and an analysis database must share identity and traceability rules, but they must not pretend to have the same structure.

---

## 13. Object Map and Object Legends

Leonardo needs both a model and a map.

The model defines the rules.

The map explains the system.

The Object Map answers:

* What objects exist?
* Who owns each object?
* Where is the object truth?
* What can affect the object?
* What does the object affect?
* What depends on it?
* What actions target it?
* What permissions govern it?
* What contracts describe it?
* What audit history exists for it?

The Object Legend answers:

* What fields are meaningful for this object family?
* Which fields are required?
* Which fields are optional?
* Which fields are runtime-only?
* Which fields are persistent?
* Which fields are user-facing?
* Which fields are internal?
* Which actions are allowed?
* Which services answer interrogation requests?
* Which service owns mutation?

The Object Map must be read-only.

The Object Map must not become a global owner.

Each object owner remains the source of truth.

---

## 14. Object Family Examples

### Window

A window is a mostly static GUI object with runtime state.

It may expose:

* window ID;
* metadata ID;
* object name;
* title;
* category;
* layout policy;
* style policy;
* settings surface;
* declared actions;
* action IDs;
* permission requirements;
* singleton or multi-instance policy;
* runtime open/focus/close state.

A window does not own domain execution.

### Action / Button

A button is a visual trigger.

The traceable object is usually the action, not the raw button widget.

An action may expose:

* action ID;
* window ID;
* label;
* required permission;
* target command or query;
* target object kind;
* enabled/disabled policy;
* audit category;
* expected operation kind.

A process started from a button must be traceable through:

```text
window_id
→ action_id
→ required_permission
→ command_id
→ operation_id
→ task_id
→ result / audit
```

### Study

A study is a chart or research object.

A live study is not automatically a saved artifact.

A study may expose:

* study ID;
* chart ID;
* tool family/key;
* parameters;
* input bindings;
* output definitions;
* style;
* runtime output references;
* chart-local lifecycle.

### Study Environment

A Study Environment is a persistent object containing saved study definitions and metadata.

It may expose:

* setup ID;
* name;
* description;
* market context;
* ordered study definitions;
* user metadata;
* created/updated timestamps;
* content hash.

A Study Environment can be used to derive artifact recipes.

### Artifact Recipe

An Artifact Recipe is a formula or instruction object.

It is not a saved artifact.

It may expose:

* recipe ID;
* tool family/key;
* parameters;
* input bindings;
* role mappings;
* output definitions;
* source signal or column identity;
* portability policy;
* compatibility policy;
* recipe hash.

A recipe describes how to calculate an artifact.

### Saved Artifact

A Saved Artifact is a materialized calculated output.

It may expose:

* artifact ID;
* artifact UID;
* family;
* market identity;
* CSV/value path;
* metadata path;
* selected columns;
* first/last timestamp;
* row count;
* column metadata;
* quality state;
* source OHLCV snapshot;
* recipe provenance where available;
* lineage;
* fingerprint.

Artifact metadata is not the same thing as an artifact recipe.

### Analysis Database

An Analysis Database is a persistent domain object.

It may expose:

* database ID;
* display name;
* market identity;
* manifest path;
* dataframe path;
* materialization status;
* component references;
* source OHLCV snapshot;
* artifact references;
* freshness state;
* build/rebuild operation references;
* validation/readiness reports.

### Connection

A connection is a runtime communication object.

It may expose:

* connection ID;
* connection kind;
* provider;
* status;
* lifecycle state;
* last heartbeat;
* last error;
* metadata;
* related websocket channels;
* owning service.

Connection tracking belongs to Core.

Provider/client behavior belongs to connection/provider services.

### WebSocket Channel

A websocket channel is a traceable runtime object.

It may expose:

* channel ID;
* connection ID;
* topic;
* subscription metadata;
* status;
* received count;
* sent count;
* error count;
* last message timestamp;
* last error;
* metadata.

Individual messages may later become optional trace objects, but channel tracking must exist first.

---

## 15. Relationship and Lineage Rules

Leonardo must know not only what objects exist, but how they relate.

The system must be able to answer:

* Which action created this operation?
* Which task executed it?
* Which object was created?
* Which object was changed?
* Which data source was used?
* Which artifact came from which recipe?
* Which database uses which artifacts?
* Which chart uses which dataset?
* Which study environment produced which recipes?
* Which websocket channel belongs to which connection?
* Which connection served which operation?
* Which audit events prove the chain?

Relationships must be explicit references, not guessed from filenames, labels, widget names, or folder structure alone.

---

## 16. Interrogation Policy

Leonardo must be designed so humans and AI assistants can inspect it.

An interrogation request should be able to ask:

* Show me this object.
* Show me its owner.
* Show me its metadata.
* Show me its settings.
* Show me its actions.
* Show me its contracts.
* Show me its permissions.
* Show me its relationships.
* Show me its runtime state.
* Show me its audit trail.
* Show me how it can be changed.
* Show me what tests cover it.

The answer must come from structured maps, metadata, contracts, read models, registries, stores, and audit history, not random source-code guessing.

---

## 17. Settings Policy

Settings are traceable objects or traceable properties of objects.

A setting must have:

* stable setting ID;
* owner;
* target object or family;
* type;
* default value;
* current value;
* persistence owner;
* apply behavior;
* validation rules;
* permission requirement;
* audit behavior where appropriate.

For windows, settings often affect layout, visual style, geometry, or display behavior.

Settings must not become hidden domain behavior.

---

## 18. Temporary Objects

Not every object is permanent.

Temporary runtime objects are valid traceable objects.

Examples:

* running task;
* operation;
* websocket channel;
* websocket subscription;
* transient download request;
* preview report;
* progress event;
* temporary chart session;
* temporary study instance.

Temporary objects still need identity, lifecycle, owner, and audit visibility appropriate to their lifespan.

Temporary does not mean invisible.

---

## 19. Persistent Objects

Persistent objects must have stable identity and durable metadata.

Examples:

* saved artifact;
* artifact recipe;
* recipe collection;
* artifact collection;
* analysis database;
* study environment;
* workspace snapshot;
* notebook;
* saved report;
* saved package;
* validation scenario.

Persistent objects must not rely on runtime state for identity.

Persistent mutation must be owned by the correct store or service.

---

## 20. Object Map Read-Only Rule

The Object Map must never become the owner of the objects it maps.

The Object Map is an index, navigator, and inspection layer.

It may aggregate summaries from:

* registries;
* stores;
* metadata files;
* contracts;
* runtime snapshots;
* audit history;
* suite read models.

It must not:

* write object state;
* mutate metadata;
* execute commands;
* bypass owners;
* repair objects;
* infer ownership where none is declared;
* replace domain stores or services.

The map points.

The owner mutates.

The audit records.

---

## 21. System We Are Building

Leonardo V2 is planned as a contract-backed, metadata-driven, traceable object system.

The system will support:

* independent suites running on Core;
* async command execution;
* safe cancellation;
* permission-gated actions;
* runtime state visibility;
* historical auditability;
* domain object ownership;
* object maps and legends;
* relationship and lineage tracking;
* read-only inspection;
* AI-assisted interrogation;
* testable boundaries;
* modular expansion.

The system must be able to answer:

* What can be done?
* Who can do it?
* What object does it affect?
* What contract governs it?
* What state is it in?
* What started it?
* What is running now?
* What has completed?
* What failed?
* What was denied?
* What changed?
* What depends on what?
* What is safe to update?
* What must be blocked?

This is the standard for future development.

---

## 22. Influence on the Rest of the Program

Every future Leonardo feature must respect the Core Manifesto.

Before implementing a feature, we must know:

* object family;
* owner;
* metadata;
* contracts;
* actions;
* permissions;
* lifecycle;
* runtime visibility;
* audit events;
* relationships;
* mutation path;
* read path;
* tests.

A new feature is not complete just because it works.

It is complete when it is:

* owned;
* contracted;
* traceable;
* auditable;
* inspectable;
* testable;
* cancellable where applicable;
* permission-gated where applicable;
* documented;
* integrated without shared responsibilities.

---

## 23. Non-Negotiable Rules

1. Core remains independent from GUI.
2. GUI remains shell, intent, and display.
3. Runtime Manager remains read-only.
4. StateStore remains current runtime truth.
5. AuditLog remains historical truth.
6. TaskManager owns task lifecycle.
7. OperationRegistry owns semantic operation lifecycle.
8. UserPolicy owns authorization.
9. Each suite owns its own domain behavior.
10. No shared responsibilities.
11. No hidden mutation paths.
12. No direct GUI ownership of Core work.
13. No domain behavior inside generic Core runtime contracts.
14. No global object registry that mutates everything.
15. Every meaningful object must have identity and owner.
16. Every meaningful action must be mapped.
17. Every long-running operation must be traceable.
18. Every persistent object must have stable metadata.
19. Every temporary object must be visible while relevant.
20. Every future feature must fit the object model and ownership map.

---

## 24. Final Statement

Leonardo V2 Core is the foundation for a modular, asynchronous, inspectable, traceable, contract-backed application.

The Core does not exist to do everything.

The Core exists so everything can be done safely, explicitly, observably, and without shared responsibility.

Suites run on Core.

Objects are owned by their proper domains.

Metadata describes them.

Contracts govern them.

State tracks them.

Audit remembers them.

Runtime Manager inspects them.

The Object Map explains them.

This is the architecture Leonardo must follow.
