# Permission Matrix

Leonardo V2 permission identifiers live in
`leonardo.contracts.identity.Permission`. The enum member names are Python-safe
code identifiers. The enum values are the stable contract strings used by Core
authorization policy.

Core `UserPolicy` owns authorization checks. `SessionManager` owns current actor
identity. `CoreRuntimeBridge` may gate command submission from
`CoreRuntimeMetadata.required_permission`, but it does not own domain behavior.

Defined permission boundaries:

- Runtime/Core: `runtime:view`, `runtime:manage`, `audit:view`, `service:view`,
  `service:manage`, `error:view`, `task:view`, `task:manage`,
  `operation:view`, `operation:manage`, `process:view`, `process:manage`,
  `connection:view`, `connection:manage`, `settings:view`, `settings:manage`.
- Download: `download:view`, `download:preview`, `download:submit`,
  `download:execute`, `download:cancel`, `download:manage`.
- Research: `research:view`, `research:run`, `research:save`,
  `research:manage`.
- Data Manager: `data_manager:view`, `data_manager:calculate`,
  `data_manager:materialize`, `data_manager:update`, `data_manager:delete`,
  `data_manager:manage`.
- Analysis: `analysis:view`, `analysis:run`, `analysis:save`,
  `analysis:delete`, `analysis:manage`.
- Trading: `trading:view`, `trading:simulate`, `trading:execute`,
  `trading:cancel`, `trading:manage`.
- Connection/provider: `connection:connect`, `connection:disconnect`,
  `connection:subscribe`.

`gui_settings:manage` remains defined for compatibility with the existing GUI
action observer settings gate.

These identifiers define policy boundaries only. They do not add suite
command/query ports, Download execution, adapter behavior, storage writers, or
trading behavior.
