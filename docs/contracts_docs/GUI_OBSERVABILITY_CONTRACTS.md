# GUI Observability Contracts

GUI observability contracts describe stable window and action identities without
importing Qt or storing widgets.

Window contracts include registered window definitions and current runtime
state. Closed windows are removed from open runtime state; their lifecycle facts
remain in audit history.

Action contracts include registered action definitions and observed trigger
records. An action trigger records that a stable action identifier was invoked;
it does not execute a command or start an operation.

Runtime state is current truth. Audit events are historical truth.

GUI widgets, Qt/PySide behavior, CoreBridge wiring, Runtime Manager GUI, command
execution, and old Leonardo dependencies are not implemented in this phase.
