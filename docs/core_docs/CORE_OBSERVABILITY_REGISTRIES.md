# Core Observability Registries

Core observability registries provide identity, runtime state, and audit events
for windows, actions, and semantic operations.

`WindowRegistry` registers window definitions and records open, focus,
close-request, and closed lifecycle transitions. It stores no Qt objects and
does not perform GUI focus behavior.

`ActionRegistry` registers action definitions and records action trigger events.
It does not execute commands, invoke handlers, or start operations.

`OperationRegistry` records semantic workflow lifecycle transitions. It does not
run tasks, own TaskManager behavior, execute business logic, or manage OS
processes.

Runtime state is current truth. Audit log history is historical truth. Runtime
Manager GUI, ProcessManager, connection/websocket tracking, Data Manager,
financial tools, workspace/chart behavior, and old Leonardo reuse are future
work and are not implemented here.
