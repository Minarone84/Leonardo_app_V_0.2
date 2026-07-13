# Leonardo Light V2

> **Reset baseline notice**
>
> This branch starts from the verified Task 0011 donor baseline. The source still contains Heavy V2 contract, Object Map, trace-provider, and GUI metadata systems scheduled for removal in Task 0047. Their presence is historical implementation evidence, not active architectural authority.

The active architecture and governance authorities are:

```text
LEONARDO_LIGHT_V2_ARCHITECTURE_GUIDELINE.md
AGENTS.md
RICK_PROTOCOL_12_COMMANDMENTS.md
RICK_CODEX_EXECUTION_PROTOCOL.md
```

Leonardo Light V2 is a modular desktop financial research and trading application. It uses one shared asynchronous runtime for long-running work, direct typed Python inside cohesive Areas, canonical authority over critical truth, and complete vertical workflow validation.

The repository is currently in an approved architecture-reset phase. Existing implementation descriptions below document the donor baseline and may reference systems that are explicitly scheduled for deletion. They must not override the governance files above.

---

## Documentation honesty

This README records the current donor implementation and reset status. It is not the architecture authority.

A legacy Leonardo capability is not current Light V2 behaviour unless the active code implements it and vertical validation proves it. A GUI shell is not backend execution. A type is not a required formal contract merely because it exists.


## Status legend

- **Implemented**: present in V2 and validated by focused tests.
- **Partially implemented**: present in V2, but incomplete, not fully wired, or not yet covering the full target architecture.
- **Shell-only**: GUI/display shell exists, but backend execution is not wired.
- **Pending sanitation**: implementation exists, but it is not yet accepted as the final V2 architecture and must be cleaned, quarantined, or rebuilt.
- **Guideline for updated V2 Leonardo version**: target architecture rule for current and future work. This is not a claim that the feature is complete.
- **Future work**: intentionally not implemented yet.
- **Explicitly out of scope**: not part of the current phase.

---

## Current implementation status

| Area | Current status | Notes |
| --- | --- | --- |
| Core foundation | **Partially implemented** | Core/contracts validation exists for the current foundation. The full target object/action/style/agent system is not complete. |
| GUI Service | **Partially implemented** | GUI shell/metadata patterns exist, including traceable dummy shell windows for the current suite cockpit phase. GUI is a shared presentation service, not a domain area. |
| Connection Suite ownership model | **Partially implemented** | Download Manager ownership contracts now point to Connection Suite. Static Bybit exchange metadata and provider capability loading exist. |
| Connection Download Manager GUI | **Shell-only** | Historical Download Manager, Confirm OHLCV Download, and OHLCV Download Task shells exist. Buttons/signals are local shell behavior only. |
| Old inline `DownloadRequestBuilder` flow | **Removed from active V2 code** | The retained builder route was decommissioned and must not be treated as future source of truth. |
| Download execution/storage/provider implementation | **Future work** | The contaminated sandbox/provider/storage implementation was removed from active source pending a future Connection Suite execution rebuild. |
| Bybit static exchange metadata | **Implemented** | Static exchange metadata belongs under the connection namespace and feeds provider capabilities. |
| Research Suite | **Shell-only** | Traceable GUI shell with deterministic dummy workspace/study/chart placeholders exists. No chart rendering, OHLCV, study calculation, or persistence logic is implemented. |
| Data Manager Suite | **Shell-only** | Traceable GUI shell with deterministic dummy dataset/artifact/recipe/database placeholders exists. No storage, artifact calculation, materialization, or Data Manager backend behavior is implemented. |
| Analysis Suite | **Shell-only** | Traceable GUI shell with deterministic dummy readiness/feature/diagnostics placeholders exists. No analysis engine, diagnostics runtime, or report generation backend is implemented. |
| Trading Suite | **Shell-only** | Traceable GUI shell with deterministic dummy paper/account/risk/order-position placeholders exists. No broker, order routing, risk engine, paper execution, or live trading behavior is implemented. |
| Full object registry doctrine | **Guideline for updated V2 Leonardo version** | Some object identity patterns may exist, but the full universal object descriptor system is not complete. |
| Full action registry doctrine | **Guideline for updated V2 Leonardo version** | Some action/menu metadata may exist, but full registered action descriptors for every operation are not complete. |
| Full style/font/layout profile doctrine | **Guideline for updated V2 Leonardo version** | Current GUI style/settings work may exist, but the full object-linked style/layout system is target architecture. |
| Full AI-agent operability doctrine | **Guideline for updated V2 Leonardo version** | Agents must eventually operate through contracts. Do not claim complete agent operation unless tested. |

---

## Current accepted ownership model

Leonardo V2 is organized from Core upward:

```text
Core
  -> GUI Service
  -> Connection Suite
  -> Research Suite
  -> Data Manager Suite
  -> Analysis Suite
  -> Trading Suite
```

Core is the foundation. GUI is a shared shell service. Domain suites plug into Core through contracts.

### Core

**Current status:** Partially implemented.

Core owns runtime foundation:

- application lifecycle;
- service registration;
- suite registration;
- task orchestration primitives;
- async execution primitives;
- cancellation/progress infrastructure;
- audit/event routing;
- cross-suite coordination;
- safe bridge from GUI intent to registered domain operations.

Core must not own suite-specific business policy. Core orchestrates. It does not become every domain wearing a fake moustache.

### GUI Service

**Current status:** Partially implemented.

GUI is not a domain area. GUI is a shared, editable, traceable presentation service used by all suites.

GUI owns:

- windows;
- dialogs;
- menus;
- menu items;
- widgets;
- buttons;
- layout;
- style;
- fonts;
- GUI metadata;
- local display state;
- local user-intent signals.

GUI does not own:

- exchange rules;
- download planning;
- OHLCV validation;
- artifact calculation;
- database materialization;
- analysis semantics;
- trading behavior;
- provider/API transport;
- storage writes.

A GUI window may exist with dummy data before backend logic exists. That is valid shell work. The shell is not the engine. This apparently needs to be written in stone because buttons keep developing messiah complexes.

Current traceable dummy shell layer:

- Main Window exposes traceable menus and launcher buttons for Connection, Research, Data Manager, Analysis, Trading, Runtime Manager, and Settings.
- Connection Download Manager shells remain GUI-owned presentation shells that target Connection Suite ownership.
- Research Suite shell displays deterministic dummy workspace/study/chart-placeholder data only.
- Data Manager Suite shell displays deterministic dummy dataset/artifact/recipe/database placeholders only.
- Analysis Suite shell displays deterministic dummy readiness, feature planning, and diagnostics placeholders only.
- Trading Suite shell displays deterministic dummy paper/account/risk/order/position placeholders only, including a disabled visual kill-switch placeholder.
- Dummy data lives in GUI-only in-memory fixtures. It does not call providers, write storage, run chart logic, calculate studies, materialize databases, analyze markets, route orders, or mutate Runtime Manager/Object Map state. Truly shocking that “dummy” has to mean dummy, but here we are.

### Connection Suite

**Current status:** Partially implemented.

Connection Suite owns exchange, account, API, websocket, and download connectivity.

Connection Suite owns the Download Manager domain.

Implemented/partially implemented pieces include:

- static Bybit exchange metadata under the connection namespace;
- provider capability loading from metadata;
- Download Manager ownership contracts pointing to Connection Suite;
- shell-only Download Manager GUI windows targeting Connection Suite.

Sanitized from active V2 source:

- old inline `DownloadRequestBuilder` flow;
- contaminated download execution/storage/provider implementation;
- GUI composition path that performed workflow orchestration directly;
- Core manager imports of concrete Download Data runtime implementation.

Target responsibilities:

- exchange registry;
- exchange capability reports;
- REST API adapters;
- websocket adapters;
- account/API-key profiles;
- connection testing;
- historical download manager;
- live feed monitoring;
- rate limit reporting;
- connection audit events;
- API/websocket runtime state;
- download preflight and execution contracts.

### Research Suite

**Current status:** Shell-only GUI dummy shell where current code/tests prove it. Backend/chart logic remains future work.

Research Suite owns historical chart research and visual study workflows.

Target responsibilities:

- historical chart sessions;
- chart workspace slots;
- chart panels;
- chart panes;
- viewport/camera state;
- study instances;
- study style profiles;
- financial tool apply/save intent;
- Study Environment save/load/update/delete flows;
- Workspace Snapshot save/load/update/delete flows;
- notebook assignment display and navigation;
- chart annotations;
- research-only visual workflows.

Research Suite does not own OHLCV truth, artifact persistence policy, Analysis Database materialization, trading execution, or exchange connectivity.

### Data Manager Suite

**Current status:** Shell-only GUI dummy shell where current code/tests prove it. Backend data/materialization logic remains future work.

Data Manager Suite owns dataset preparation and Analysis Database construction.

Target responsibilities:

- accepted/loadable OHLCV dataset selection;
- dataset preview intent;
- saved artifact catalog;
- artifact recipes;
- recipe collections;
- artifact collections;
- artifact calculation intent;
- metadata tools;
- database seed creation;
- database component editing;
- database build/rebuild/update intent;
- materialization preflight display;
- freshness/update reports;
- artifact/database lineage display.

Data Manager Suite does not own chart sessions, rendering, exchange connectivity, raw OHLCV validation policy, Analysis Suite diagnostics, or trading behavior.

### Analysis Suite

**Current status:** Shell-only GUI dummy shell where current code/tests prove it. Analysis engine behavior remains future work.

Analysis Suite owns structured analysis workflows.

Target responsibilities:

- Analysis Database readiness inspection;
- target/label planning;
- feature-set planning;
- diagnostic reports;
- POI definitions;
- event family definitions;
- road/outcome concepts;
- genome/path previews;
- white-box rule testing;
- candidate scanning;
- temporal validation;
- rule review;
- rule package previews;
- saved analysis projects;
- saved runs;
- saved reports;
- saved rule packages;
- validation scenarios.

A diagnostic report is not a tradable strategy. A rule package is not a trading bot. A promising pattern is not proof of profit. Markets do not care about your confidence, your chart annotations, or your inspirational desk lamp.

### Trading Suite

**Current status:** Shell-only GUI dummy shell where current code/tests prove it. Trading and broker/order behavior remain future work.

Trading Suite owns real-time trading scenarios.

Target responsibilities:

- strategy activation;
- paper trading;
- live trading;
- broker/exchange order routing;
- account trading state;
- risk profiles;
- position tracking;
- order lifecycle;
- execution reports;
- capital/equity state;
- kill switch;
- manual override;
- trading audit events.

Trading Suite must be the strictest suite in the system.

No unregistered order actions. No hidden live trading buttons. No strategy execution without contracts, metadata, risk policy, connection refs, task/audit state, and explicit safety gates.

---

# Guidelines for the updated V2 Leonardo version

Everything in this section is target architecture unless the **Current implementation status** section explicitly marks it as implemented or partially implemented.

These guidelines are still binding design rules. They are not proof that the implementation is finished.

## Mission guideline

Leonardo V2 exists to provide a deterministic, auditable, extensible environment for:

- exchange/account connectivity;
- OHLCV download, validation, repair, and maintenance;
- historical chart research;
- financial study design and artifact generation;
- dataset and Analysis Database preparation;
- analysis planning, diagnostics, POI/family/genome/rule research;
- future real-time trading workflows;
- AI-agent inspection and safe operation through contracts.

The old Leonardo proved that the Research Suite, Download Manager, OHLCV Maintenance, and Data Manager workflows were valuable. V2 keeps those ideas, but rebuilds them with stronger contracts, metadata, object identity, agent-readable state, async Core orchestration, and stricter ownership boundaries.

---

## Ten architecture commandments

These are architectural laws for the updated V2 Leonardo version. If a commandment describes a system that is not yet implemented, it remains a guideline and target requirement.

### 1. Core is the foundation

Core owns application lifecycle, service registration, task orchestration, async execution, cancellation, progress, audit/event routing, and cross-suite coordination.

Any serious operation goes through Core.

This includes downloads, validation, repair, artifact calculation, database build/rebuild/update, analysis execution, websocket feeds, account checks, backtests, trading simulation, and real trading.

A GUI callback must never become a secret execution engine.

### 2. GUI is a traceable shell service

The GUI is not the brain. The GUI is a shared, inspectable, configurable shell service used by every suite.

The complete GUI must be buildable with dummy data before real backend logic exists.

Every GUI object should have stable identity:

- windows;
- dialogs;
- menus;
- menu items;
- toolbars;
- tabs;
- dock widgets;
- panels;
- buttons;
- labels;
- inputs;
- tables;
- table columns;
- chart panes;
- status panels;
- progress displays;
- style controls;
- layout containers.

A missing backend is not an excuse for an unregistered GUI object. The cockpit can be wired before the engine is installed.

### 3. Everything is traceable

If it exists, it must be addressable.

Every important object should expose:

- stable object ID;
- object type;
- owning layer;
- owning suite/service;
- parent object ref;
- child object refs;
- available action refs;
- state snapshot contract;
- metadata contract;
- style profile ref, when visual;
- layout profile ref, when visual;
- audit/event refs;
- agent access policy.

Examples:

```text
gui.window.main
gui.window.research_suite
gui.button.research_suite.chart.add
gui.widget.data_manager.database_builder
gui.menu.connection
gui.action.connection.download.preflight
core.task.download_ohlcv.20260708_001
connection.exchange.bybit
connection.websocket.bybit.public
research.chart.session.btcusdt_1m_001
research.study.rsi_001
data_manager.artifact.volume_001
data_manager.database.btc_1m_topology_001
analysis.project.poi_family_research_001
trading.order.paper_001
```

No anonymous buttons. No mystery widgets. No hidden execution paths.

### 4. No shared responsibility

Every behavior has exactly one owner.

GUI owns display and user intent collection. It does not own business rules.

Core owns orchestration. It does not own domain policy.

Domain services own planning, validation, and execution semantics. They do not own GUI layout.

Storage services own persistence. They do not invent business decisions.

Renderers render. They do not calculate studies, validate data, or mutate state.

Agents inspect and invoke through contracts. They do not bypass ownership.

If two layers both think they own the same decision, the design is wrong.

### 5. Contracts define the shape of reality

All important payloads must be contract-backed.

Contracts define:

- object refs;
- action descriptors;
- input payloads;
- preflight reports;
- progress events;
- terminal reports;
- metadata sidecars;
- state snapshots;
- style profiles;
- layout profiles;
- suite capability descriptors;
- persistence schemas;
- audit events.

No tuple soup. No undocumented dictionaries. No “the widget knows the format.” That way lies the old swamp.

### 6. Metadata is not decoration

Metadata is system truth.

Every persistent object must carry enough metadata to explain what it is, where it came from, how it was produced, what version of the contract created it, and whether it is safe to use.

Persistent objects should include, where applicable:

- stable ID;
- schema version;
- object kind;
- display name;
- source refs;
- lineage;
- owner service;
- creation/update timestamps;
- quality state;
- validation state;
- hash/fingerprint evidence;
- contract version;
- parameters/spec identity;
- warnings/blockers;
- audit refs.

CSV rows are data. Metadata explains whether those rows mean anything.

### 7. Every action is registered

A button is only a visual surface for an action. The action is the real contract.

Every action should define:

- action ID;
- label;
- owning object;
- input contract;
- preflight contract, if any;
- confirmation policy;
- execution owner;
- result contract;
- audit events;
- agent invocation policy;
- safety level.

Examples:

```text
action.connection.download.preflight
action.connection.download.confirm
action.ohlcv.validate.checked
action.data_manager.database.build_checked
action.research.chart.apply_study
action.analysis.target.preview
action.trading.order.submit_paper
action.trading.kill_switch.activate
```

If an action is not registered, it does not exist.

### 8. Style, font, color, and layout are first-class objects

The GUI should be configurable through object-linked profiles, not scattered hardcoded widget tweaks.

Every visual object should be traceable to style/layout configuration where applicable:

- font family;
- font size;
- bold/italic state;
- foreground color;
- background color;
- border/padding/margin policy;
- visibility;
- enabled state;
- geometry hints;
- dock/slot/pane placement;
- layout profile;
- theme profile.

If an AI agent is asked to increase the Research Suite font by `1`, the target architecture is:

1. resolve object `gui.window.research_suite`;
2. read linked font/style profile;
3. apply font size delta `+1`;
4. re-render affected child objects;
5. emit a style mutation audit event.

No pixel guessing. No Qt archaeology. No “which stylesheet was that again?” nonsense.

### 9. Agents operate through contracts, not hacks

An AI helper must use the same object/action/state/event contracts as the GUI and Core.

An agent may inspect:

- registered objects;
- available actions;
- current state snapshots;
- style/layout profiles;
- task state;
- audit/event history;
- preflight reports;
- blockers/warnings/errors.

An agent may invoke only actions that are explicitly agent-invokable and only through the registered action path.

An agent must not:

- scrape pixels;
- bypass preflight;
- write files directly;
- mutate database manifests directly;
- fake service reports;
- invent object refs;
- run trading actions without explicit safety gates.

The agent is a disciplined operator, not a raccoon with admin rights.

### 10. Legacy strengths are preserved, but V2 improves them

The old app had useful foundations:

- Research Suite was a strong historical chart research workspace;
- Download Manager had a sound preflight/task-monitor/audit direction;
- OHLCV Maintenance had the right explicit validation/repair/acceptance model;
- Data Manager had useful dataset/artifact/recipe/database preparation workflows;
- metadata sidecars and lineage were the correct direction;
- GUI-as-intent/display was already the right boundary in several places.

V2 preserves these strengths as capability references. They become current V2 implementation only when rebuilt through contracts, metadata, object identity, action registration, Core task routing, state snapshots, audit/event traces, and tests.

---

## Object system guideline

**Current status:** Guideline for updated V2 Leonardo version, partially implemented only where code/tests prove it.

Every Leonardo object should be describable through a stable object descriptor.

Minimum target descriptor fields:

```text
object_id
object_type
owner_layer
owner_suite
owner_service
parent_object_id
child_object_ids
action_ids
state_contract
metadata_contract
style_profile_id
layout_profile_id
agent_access_policy
audit_event_refs
schema_version
```

Target object categories include:

- runtime objects;
- services;
- suites;
- windows;
- dialogs;
- widgets;
- menus;
- actions;
- charts;
- panes;
- renderers;
- studies;
- datasets;
- OHLCV sources;
- artifacts;
- recipes;
- notebooks;
- databases;
- analysis reports;
- websockets;
- API connections;
- trading orders;
- tasks;
- audit events;
- style profiles;
- layout profiles.

---

## Action system guideline

**Current status:** Guideline for updated V2 Leonardo version, partially implemented only where code/tests prove it.

Every user-visible action and agent-invokable operation should be registered.

Minimum target action descriptor fields:

```text
action_id
label
description
owning_object_id
owning_suite
input_contract
preflight_contract
confirmation_required
execution_owner
long_running
result_contract
progress_event_contract
audit_event_types
agent_invocation_policy
safety_level
```

Buttons, menu items, shortcuts, context actions, and agent commands all point to action descriptors.

The visual control is not the source of truth. The action descriptor is.

---

## State snapshot guideline

**Current status:** Guideline for updated V2 Leonardo version, partially implemented only where code/tests prove it.

Every important object should expose a structured state snapshot.

State snapshots answer:

- what object this is;
- whether it is visible;
- whether it is enabled;
- what is selected;
- what data is displayed;
- what actions are available;
- what blockers exist;
- what warnings exist;
- what task/report/event produced this state;
- when it changed.

Agents inspect state snapshots. They do not scrape pixels, parse labels, or guess from widget hierarchy.

---

## Style, font, and layout profile guideline

**Current status:** Guideline for updated V2 Leonardo version, partially implemented only where code/tests prove it.

Visual configuration is part of the target architecture.

A profile may define:

- font family;
- font size;
- bold/italic/underline;
- foreground color;
- background color;
- accent color;
- border policy;
- margin/padding;
- table density;
- pane split ratios;
- default geometry;
- maximized/default window state;
- dock/slot/pane placement;
- chart pane sizing;
- button rack sizing;
- theme inheritance.

The style/layout system must allow targeted changes. If the user wants a Jarvis-style Leonardo tomorrow, GUI style/layout profiles must allow that without domain rewrites. Apparently “make the interface editable” means not welding fonts into random constructors like a goblin with a glue gun.

---

## Metadata and persistence guideline

**Current status:** Guideline for updated V2 Leonardo version, partially implemented only where code/tests prove it.

Persistent objects must never rely on filename vibes.

Every persistent object should carry contract-backed metadata:

```text
object_id
object_kind
schema_version
display_name
owner_suite
owner_service
created_at
updated_at
source_refs
lineage
quality_state
validation_state
hashes/fingerprints
spec refs
contract refs
warnings
blockers
audit refs
```

Data without metadata is not trusted system truth.

---

## Agent operability guideline

**Current status:** Guideline for updated V2 Leonardo version, partially implemented only where code/tests prove it.

Leonardo V2 is built so an AI helper can safely operate the system through contracts.

The agent should eventually be able to ask:

```text
What suites exist?
What windows exist?
What widgets exist in this window?
What actions does this object expose?
What state is currently displayed?
What service owns this operation?
What preflight is required?
What style profile controls this object?
What changed recently?
What warnings/blockers exist?
```

The agent should act only through registered actions:

```text
inspect object
read state snapshot
run preflight
request confirmation
invoke allowed action
watch task progress
read terminal report
apply style/layout mutation
read audit trail
```

Agent operation is not GUI automation. It is contract operation.

---

## Legacy capability migration guideline

**Current status:** Guideline for updated V2 Leonardo version unless specific items are proven by current code/tests.

The old Leonardo README is treated as a legacy capability reference, not as current V2 implementation truth.

V2 will preserve and improve the sound legacy workflows.

### Research Suite legacy target

Preserve:

- historical chart workspace;
- multi-chart layout;
- chart-local studies;
- study styles;
- Study Environments;
- Workspace Snapshots;
- notebook association;
- chart annotations;
- pane/renderer ownership model.

Improve with:

- object refs for every chart/window/pane/study/control;
- style/layout/font profiles;
- agent-readable chart state;
- action descriptors;
- Core-routed long operations;
- stronger metadata and lineage.

### Connection / Download Manager legacy target

Preserve:

- exchange capability display;
- OHLCV preflight;
- multi-timeframe download planning;
- task monitoring;
- cancellation/reporting;
- audit events;
- conservative post-download validation state.

Improve with:

- Connection Suite ownership;
- account/API/websocket object refs;
- Core task execution;
- richer connection state snapshots;
- agent-safe connection tests;
- API/websocket audit traces.

Current accepted status:

- Connection ownership contracts: partially implemented.
- Connection Download Manager GUI shells: shell-only.
- Download Manager backend/execution path: removed from active source pending future Connection Suite rebuild.

### OHLCV Maintenance legacy target

Preserve:

- explicit validation;
- accepted/loadable states;
- repair planning;
- metadata rebuild;
- source correction policy;
- dataset deletion safety.

Improve with:

- dataset object refs;
- validation report contracts;
- repair task contracts;
- clear owner services;
- agent-visible blockers and repair plans;
- stronger metadata/fingerprint traceability.

### Data Manager Suite legacy target

Preserve:

- accepted OHLCV-only policy;
- saved artifacts;
- recipes;
- recipe collections;
- artifact collections;
- database seed creator;
- database builder;
- update manager;
- metadata/lineage hardening;
- backend-owned validation/materialization/update policy.

Improve with:

- full object/action registry;
- Core-routed long operations;
- stricter metadata contracts;
- agent-readable preparation state;
- style/layout-configurable suite shell;
- no direct GUI policy decisions.

### Analysis Suite legacy target

Preserve:

- readiness/target/feature/diagnostic direction;
- POI/family/genome/rule concepts;
- white-box diagnostic philosophy;
- saved analysis object direction.

Improve with:

- first-class suite ownership;
- clearer execution boundaries;
- better persistence contracts;
- explicit non-trading status;
- agent-readable reports and blockers.

### Trading Suite target

Trading Suite is future work, but its ownership is defined now.

It must not be smuggled into Research Suite, Analysis Suite, Connection Suite, Data Manager, or GUI callbacks.

---

## Non-negotiable boundaries

These boundaries are active architectural rules now and target rules for all future implementation.

### GUI must never

- decide OHLCV loadability;
- validate business rules;
- write domain files directly;
- mutate database manifests directly;
- calculate artifacts directly;
- execute recipes directly;
- classify artifact freshness locally;
- own websocket connection logic;
- place orders;
- generate trading signals;
- bypass preflight;
- fake backend reports.

### Core must never

- own suite-specific business policy;
- write arbitrary domain files outside storage services;
- replace domain services with orchestration shortcuts;
- hide task execution from audit/event history.

### Domain services must never

- own GUI layout;
- mutate visual state directly;
- bypass storage services for persistence;
- return undocumented payloads.

### Storage services must never

- invent business decisions;
- silently repair references;
- mutate unrelated objects;
- cascade deletes unless a contract explicitly says so.

### Renderers must never

- calculate financial studies;
- validate data;
- persist artifacts;
- mutate chart/session truth;
- own business meaning.

### Agents must never

- bypass registered actions;
- bypass safety gates;
- write files directly;
- invent object IDs;
- scrape GUI pixels;
- imply profitability from diagnostics;
- trade without explicit Trading Suite contracts and confirmations.

---

## Validation doctrine

Every architecture patch must preserve:

- no shared responsibility;
- object identity discipline;
- action registry discipline;
- Core execution ownership;
- GUI shell-only boundaries;
- metadata and lineage requirements;
- agent-safe operation paths;
- documentation truthfulness.

Code changes should follow:

```text
Audit -> Update -> Validation
```

Validation should include, where applicable:

- static import boundary checks;
- contract serialization tests;
- object registry tests;
- action descriptor tests;
- GUI object-name/registry tests;
- style/layout profile tests;
- Core task lifecycle tests;
- metadata round-trip tests;
- persistence safety tests;
- agent snapshot/invocation tests;
- docs link/status review.

---

## Implementation status policy

Every README/doc section must distinguish between:

```text
Implemented
Partially implemented
Shell-only
Pending sanitation
Guideline for updated V2 Leonardo version
Future work
Explicitly out of scope
```

No section may describe old Leonardo behavior as current V2 behavior unless V2 actually implements it.

Documentation must be ambitious, but not dishonest. Markdown lies are still lies, just with headings.

---

## Final doctrine

Leonardo V2 is rebuilt from Core upward.

Core is the foundation.

GUI is the traceable shell service.

Connection Suite owns exchange/API/websocket/download connectivity.

Research Suite owns historical chart research workflows.

Data Manager Suite owns dataset/artifact/recipe/database preparation.

Analysis Suite owns structured analysis and diagnostic research.

Trading Suite owns real-time trading behavior and risk-controlled execution.

Every object must eventually be identified.

Every action must eventually be registered.

Every state must eventually be inspectable.

Every style/layout/font property must eventually be configurable.

Every persistent object must carry metadata and lineage.

Every long-running operation must go through Core.

Every agent operation must go through contracts.

Every warning, blocker, error, success, task, API call, websocket state, button press, style mutation, and user action must be auditable.

No shared responsibility is allowed.

That is Leonardo V2.
