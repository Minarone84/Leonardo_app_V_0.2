# Leonardo App V 0.2

Leonardo V2 is a clean rebuild of Leonardo around explicit contracts,
traceable runtime state, GUI presentation shells, and strict ownership
boundaries. This README describes the current V2 implementation status and the
target architecture without treating future or legacy capabilities as complete.

## Current Implementation Status

Status legend:

* `Implemented`: present in V2 and validated by tests.
* `Partially implemented`: present, but incomplete or not yet fully wired.
* `Shell-only`: GUI/display shell exists, but backend behavior is not wired.
* `Guideline / target architecture`: architectural law for future and ongoing work, not a claim that implementation is complete.
* `Future work`: intentionally not implemented yet.
* `Pending sanitation`: existing implementation exists but is not yet accepted as the correct V2 architecture.
* `Explicitly out of scope`: not part of the current phase.

| Area | Status | Current truth |
| --- | --- | --- |
| Core foundation | `Partially implemented` | Core contracts and runtime foundations exist and are covered by tests, but the full target object, action, style, layout, and agent-operability system is not complete. |
| GUI Service | `Partially implemented` | The GUI shell pattern exists. GUI owns windows, widgets, buttons, layout, style, fonts, metadata for visual shells, and local display/user-intent signals only. GUI is not a domain owner. |
| Connection Suite ownership model | `Partially implemented` | Download Manager ownership contracts exist. Bybit static exchange metadata and provider capability loading exist. The final Download Manager backend and execution path remain pending sanitation. |
| Connection Download Manager GUI | `Shell-only` | Historical Download Manager, Confirm OHLCV Download, and OHLCV Download Task shells exist. Buttons and signals are local shell behavior only. No backend execution is wired. |
| Old inline DownloadRequestBuilder flow | `Pending sanitation` | This existing flow is not the accepted final Download Manager UX and must not be treated as the source of truth for future Download Manager GUI work. |
| Download execution, storage, and provider implementation | `Pending sanitation` | Sandbox, fixture, or live-opt-in work may exist, but it is not yet accepted as the final Connection Suite Download Manager execution architecture. |
| Research Suite | `Partially implemented` / `Guideline / target architecture` | Only V2 code and tests define current implementation. Legacy research capabilities remain target architecture or reference material unless explicitly accepted into V2. |
| Data Manager Suite | `Partially implemented` / `Guideline / target architecture` | Only V2 code and tests define current implementation. Legacy data-management capabilities remain target architecture or reference material unless explicitly accepted into V2. |
| Analysis Suite | `Guideline / target architecture` / `Future work` | Analysis capability is not treated as complete V2 behavior unless specific V2 code and tests prove implementation. |
| Trading Suite | `Future work` | Ownership boundaries are defined to prevent leakage into GUI, Research, Analysis, Data Manager, or Connection. Trading behavior is not part of the current implementation. |
| Object registry, action registry, style-layout-profile, and agent-operability doctrine | `Guideline / target architecture` | These are architectural laws and design targets unless a specific V2 module and test suite proves partial implementation. |

## Ownership Doctrine

Leonardo V2 has five domain areas running on Core:

* `connection_suite`
* `research_suite`
* `data_manager_suite`
* `analysis_suite`
* `trading_suite`

GUI is a shared presentation service, not a domain area. GUI owns visual shells
and local user-intent signals. Domain suites own domain behavior. Core owns
runtime foundation, orchestration primitives, contracts, audit, state, policy,
identity, and lifecycle boundaries.

Every responsibility must have one owner. No shared responsibility is allowed.

## Current Architecture Rules

Contracts define runtime reality. Importable contracts live under
`src/leonardo/contracts/`, and human-readable contract documentation lives under
`docs/contracts_docs/`.

Metadata is system truth for GUI presentation shells and traceable identities.
GUI metadata may reference a target suite or module, but that reference does not
transfer domain ownership to GUI.

Connection Suite owns Download Manager domain workflow. The current standalone
Download Manager windows are GUI shells only and must not call providers,
storage writers, backend execution managers, Runtime Manager, Object Map, or
Data Manager services directly.

Core is the foundation for runtime state, task and operation supervision,
permission policy, audit history, contract registration, and read-only
inspection. Core must not import GUI or become the owner of domain behavior.

Action registry discipline, object registry discipline, style/font/layout
mutation, and agent operation through contracts are target architecture
requirements. Do not claim these systems are fully implemented until V2 code and
tests establish that status.

## Legacy Capability References

Old Leonardo code is reference material unless a future phase explicitly audits
and accepts a specific module for V2. Legacy Analysis Suite, Data Manager,
financial tools, adapters, trading behavior, and historical downloader behavior
must not be described as current V2 implementation unless corresponding V2 code
and tests exist.
