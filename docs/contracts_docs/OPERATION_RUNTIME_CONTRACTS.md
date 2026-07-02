# Operation Runtime Contracts

Operations represent semantic workflows, not button clicks.

Operation runtime state tracks an operation identifier, kind, lifecycle status,
label, timestamps, optional actor/session/window/action/task/correlation
references, blockers, warnings, optional error message, and metadata.

Active operations remain in runtime state. Terminal operation outcomes are
removed from active runtime state and retained in audit history. Terminal
statuses are `blocked`, `completed`, `failed`, and `cancelled`.

The operation contracts do not execute business logic, run async tasks, own GUI
actions, manage processes, or track connections/websockets.
