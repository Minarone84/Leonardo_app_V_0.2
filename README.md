# Leonardo App V 0.2

Leonardo V2 is a clean rebuild around explicit contracts, traceable runtime
state, strict ownership boundaries, and GUI presentation shells. The project
goal is a system where Core coordinates runtime truth, domain suites own domain
behavior, GUI presents user intent, and agents operate through contracts instead
of hidden coupling.

## Current Implementation Status

Leonardo V2 currently has a tested Core foundation, GUI shell infrastructure,
contract docs, metadata docs, and Connection Download Manager shell work. It is
not a claim that every target system is implemented.

| System | Status | Current truth |
| --- | --- | --- |
| Core foundation | `Partially implemented` | Runtime foundation and many contracts exist and pass validation. Core must not own Download Manager domain policy. |
| GUI Service | `Partially implemented` | GUI shell metadata and Connection Download Manager shell windows exist. Full style/layout/action/object registry doctrine remains target architecture unless proven by code/tests. |
| Connection Suite | `Partially implemented` | Bybit static exchange metadata, provider capability loading, and Download Manager ownership contracts are implemented. Execution architecture remains pending sanitation. |
| Connection Download Manager GUI | `Shell-only` | Historical Download Manager, Confirm OHLCV Download, and OHLCV Download Task shells exist. Buttons/signals are local GUI shell behavior only. No backend execution is wired. |
| Old inline DownloadRequestBuilder flow | `Pending sanitation` | Retained temporarily. It is not the accepted final Download Manager UX and must not be used as source-of-truth for future Connection Download Manager design. |
| Download execution, storage, and provider implementation | `Pending sanitation` | Existing sandbox, fixture, or live-opt-in work may exist. It is not yet accepted as the final Connection Suite Download Manager execution architecture. |
| Research Suite | `Partially implemented` where current V2 code/tests prove it | Legacy Research capabilities are guidelines for the updated V2 Leonardo version unless explicitly accepted into V2. |
| Data Manager Suite | `Partially implemented` where current V2 code/tests prove it | Legacy Data Manager capabilities are guidelines for the updated V2 Leonardo version unless explicitly accepted into V2. |
| Analysis Suite | `Guideline for updated V2 Leonardo version` / `Future work` | Analysis behavior is not current V2 behavior unless specific V2 code and tests prove it. |
| Trading Suite | `Future work` | Ownership is defined now to prevent leakage into GUI, Research, Analysis, Data Manager, or Connection. |
| Complete object-addressability across all objects | `Guideline for updated V2 Leonardo version` | Current traceability work establishes direction; all-object addressability is not claimed unless proven by tests. |
| Full action registry discipline across all GUI/domain actions | `Guideline for updated V2 Leonardo version` | Action IDs and observation patterns exist, but global action discipline remains target architecture unless proven by code/tests. |
| Full style/font/layout profile mutation system | `Guideline for updated V2 Leonardo version` | Safe GUI style settings exist for selected profiles; full mutation policy remains target architecture. |
| Full AI-agent operability | `Guideline for updated V2 Leonardo version` | Agents must operate through contracts, metadata, runtime state, and policy gates; full operability is not current behavior. |
| StateStore thread-safety hardening | `Future Core hardening` / `Guideline for updated V2 Leonardo version` | Do not treat thread-safety hardening as accepted unless a future focused phase proves it. |

## Status Legend

* `Implemented`: present in V2 and validated by tests.
* `Partially implemented`: present, but unfinished or not yet fully wired.
* `Shell-only`: GUI/display shell exists, but backend behavior is not wired.
* `Pending sanitation`: existing implementation exists but is not yet accepted as the correct V2 architecture.
* `Guideline for updated V2 Leonardo version`: architectural law for future and ongoing work, not a claim that implementation is finished.
* `Future work`: intentionally not implemented yet.
* `Explicitly out of scope`: not part of the current phase.

## Implemented / Partially Implemented / Shell-Only / Pending Sanitation / Guideline / Future Work / Explicitly Out Of Scope

Implemented status requires current V2 code and tests. Partial status means a
boundary or slice exists but is not the whole target system. Shell-only status
means GUI surfaces exist without backend ownership. Pending sanitation means an
existing path is retained temporarily and must not define future architecture.
Guidelines define the updated V2 direction. Future work is intentionally not
implemented. Explicitly out-of-scope work must not be introduced by adjacent
phases.

## Guidelines For The Updated V2 Leonardo Version

Leonardo V2 has five domain areas running on Core:

* `connection_suite`
* `research_suite`
* `data_manager_suite`
* `analysis_suite`
* `trading_suite`

GUI is not a domain area. GUI is a shared presentation service. GUI owns
windows, widgets, buttons, menus, metadata for visual shells, layout, style,
fonts, display state, and local user-intent signals. Domain suites own domain
behavior. Core owns runtime foundation, orchestration primitives, service
registration, task lifecycle, audit/event routing, and cross-suite
coordination.

## Core Doctrine

Core owns runtime foundation, contracts, service registration, task lifecycle,
operation lifecycle, state snapshots, policy, audit/event routing, and
cross-suite coordination. Core must not own Download Manager domain policy,
provider behavior, storage writer behavior, GUI layout, or suite-specific
workflow decisions.

Core status is `Partially implemented`: runtime foundation and many contracts
exist and pass validation, but not every target object/action/style/agent
system is finished.

## GUI Service Doctrine

GUI is a presentation service. It owns windows, widgets, menus, buttons,
dialogs, layout, fonts, style defaults, editable GUI metadata, display state,
and local user-intent signals. GUI may expose launch surfaces and shell-only
signals, but it must not own Connection Suite behavior, provider calls, storage
writes, Core execution policy, Runtime Manager control behavior, or Object Map
mutation.

GUI status is `Partially implemented`. The Connection Download Manager windows
are `Shell-only`.

## Connection Suite Doctrine

Connection Suite owns exchange, API, websocket, provider capability, and
Download Manager domain behavior. Download Manager belongs to Connection Suite.
The accepted target module is `connection.download_manager`.

Connection Suite status is `Partially implemented`: Download Manager ownership
contracts, Bybit static exchange metadata, and provider capability loading are
implemented. Final Download Manager execution architecture and final
provider/storage/download runtime architecture are `Pending sanitation`.

## Research Suite Doctrine

Research Suite owns research workflow behavior when that behavior is accepted
into V2. Research capability is `Partially implemented` only where current V2
code and tests prove it. Legacy Research behavior remains a guideline for the
updated V2 Leonardo version or reference material until audited and accepted.

## Data Manager Suite Doctrine

Data Manager Suite owns managed data artifacts and accepted data-management
workflows. It does not inherit ownership from old code automatically. Data
Manager capability is `Partially implemented` only where current V2 code and
tests prove it. Legacy Data Manager behavior remains a guideline for the
updated V2 Leonardo version until accepted.

## Analysis Suite Doctrine

Analysis Suite behavior is `Guideline for updated V2 Leonardo version` or
`Future work` unless current V2 code and tests prove implementation. Old
Analysis Suite behavior must not be described as current V2 behavior merely
because reference code exists.

## Trading Suite Doctrine

Trading Suite is `Future work`. Ownership boundaries are defined now to
prevent trading behavior from leaking into GUI, Research, Analysis, Data
Manager, Connection, or Core. No trading/order behavior is part of the current
phase.

## Object System Doctrine

Objects should be traceable, addressable, and inspectable through contracts and
metadata. Complete object-addressability across all objects is a `Guideline for
updated V2 Leonardo version` unless specific modules and tests prove a narrower
implemented slice.

## Action System Doctrine

Actions require stable IDs, explicit ownership, policy visibility, and audit
readiness. Full action registry discipline across all GUI and domain actions is
a `Guideline for updated V2 Leonardo version` unless proven by current code and
tests.

## State Snapshot Doctrine

Runtime truth must be inspectable through snapshots and read models. Runtime
Manager may display state but must not own task, process, connection, action,
operation, provider, or Download Manager behavior. StateStore thread-safety
hardening is future Core hardening unless a focused phase proves otherwise.

## Style/Font/Layout Doctrine

Style, font, density, geometry, and layout policy are first-class GUI metadata
concerns. A full style/font/layout profile mutation system is a `Guideline for
updated V2 Leonardo version`; current V2 implements selected safe visual
settings and must not claim the whole target system is finished.

## Metadata/Persistence Doctrine

Metadata is system truth for GUI presentation shells and traceable identities.
GUI metadata may reference a target area, suite, module, or shell, but that
reference does not transfer domain ownership to GUI.

Persistent user overrides are changed-only where implemented. Source metadata
must not be mutated by settings UI. Review ZIPs should exclude `.git`,
`__pycache__`, `.pytest_cache`, egg-info, `runs`, `tmp`, and generated
`historical_data` unless specifically requested.

## Agent Operability Doctrine

Agents must operate through contracts, metadata, runtime state, policy gates,
and audited actions. Full AI-agent operability is a `Guideline for updated V2
Leonardo version`, not current finished behavior.

## Legacy Capability Migration Doctrine

Old Leonardo code is reference material unless a future phase explicitly audits
and accepts a specific module for V2. Legacy Analysis Suite, Data Manager,
financial tools, adapters, trading behavior, and historical downloader behavior
must not be described as current V2 implementation unless corresponding V2 code
and tests exist.

The old inline `DownloadRequestBuilder` flow is `Pending sanitation`. It is
retained temporarily and must not be used as source-of-truth for future
Connection Download Manager design.

## Non-Negotiable Boundaries

No shared responsibility is allowed. GUI remains a shell service. Connection
Suite remains Download Manager owner. Core remains runtime foundation. Data
Manager owns managed data artifacts later. Runtime Manager remains an inspector,
not a controller. Object Map inspection must remain read-only unless a future
phase explicitly changes that contract.

## Validation Doctrine

Claims require validation. Tests define accepted V2 behavior. Documentation
must distinguish implemented behavior, shell-only work, pending sanitation,
guidelines for the updated V2 Leonardo version, future work, and legacy
references.

## Final Doctrine

Leonardo V2 is contract-aware, metadata-driven, observable, and ownership
strict. The current repository contains validated slices and shell-only
surfaces, not the entire target system. Future phases must preserve ownership,
avoid shared responsibility, and keep documentation truthful as implementation
advances.
