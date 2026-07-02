# Core Async Task Manager

The Core TaskManager supervises Core-managed asyncio tasks on the currently
running event loop.

Responsibilities:

- assign stable task identifiers;
- reject duplicate active task names by default;
- register active task runtime state in `StateStore`;
- emit task lifecycle audit events through `StateStore`;
- route task failures through `ErrorRouter` when configured;
- remove completed, failed, and cancelled tasks from active runtime state;
- cancel individual tasks or all active tasks.

Runtime task state is current truth. Audit events are historical truth. Terminal
task facts remain in audit history after task runtime state is removed.

The TaskManager is not a ProcessManager, OperationRegistry, GUI worker owner,
connection manager, Data Manager, financial-tool runner, workspace/chart owner,
or business-logic execution layer.

Async event-loop ownership and GUI/CoreBridge runner integration are deferred to
later phases. This phase does not launch a persistent background loop.
