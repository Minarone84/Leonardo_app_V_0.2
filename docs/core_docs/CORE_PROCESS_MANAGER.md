# Core Process Manager

`ProcessManager` is the CORE-11 backend service for controlled process
supervision.

The manager starts processes only from explicit `ProcessLaunchRequest` values. It
uses an injectable launcher boundary so tests and future platform adapters can
provide process handles without changing Core process lifecycle logic.

Responsibilities:

- validate launch requests;
- reject duplicate active process identifiers;
- start processes through the configured launcher;
- record current active process state in `StateStore`;
- emit audit history for process lifecycle transitions;
- refresh process state from handle polling;
- request graceful termination;
- force termination when explicitly requested;
- expose defensive active-process snapshots.

`ProcessManager` does not run domain logic by itself. It does not own
`TaskManager`, `OperationRegistry`, Runtime Manager GUI behavior, Qt/PySide
objects, Data Manager behavior, financial tools, workspace/chart behavior, old
Leonardo code, or connection/websocket tracking.

Runtime state is current truth. Audit log history is historical truth. Terminal
process facts leave active runtime state and remain in audit history.
