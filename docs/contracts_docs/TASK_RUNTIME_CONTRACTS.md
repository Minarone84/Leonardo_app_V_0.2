# Task Runtime Contracts

Task runtime contracts define the current state of Core-supervised async tasks.

`TaskLifecycleStatus` includes:

- `created`;
- `running`;
- `completed`;
- `failed`;
- `cancel_requested`;
- `cancelled`.

`TaskRuntimeState` identifies one task with `task_id`, `task_name`, lifecycle
status, start/update timestamps, optional completion timestamp, optional
operation/service/correlation references, optional error message, and metadata.

Task runtime state is current truth. Active tasks are visible in runtime
snapshots. Completed, failed, and cancelled terminal outcomes are removed from
active runtime state and remain available through audit history.

This phase does not add operation, window, process, connection, websocket, GUI,
Data Manager, financial-tool, workspace, chart, or old-code contracts.
