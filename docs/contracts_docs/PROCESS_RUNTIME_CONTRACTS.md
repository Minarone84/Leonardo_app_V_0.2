# Process Runtime Contracts

Process runtime contracts define the Core process supervision boundary.

`ProcessLaunchRequest` represents an explicit request to start one supervised
process. Commands are stored as argument-token tuples, not shell command strings.
The request can carry optional runtime correlation fields such as operation,
task, service, and correlation identifiers.

`ProcessRuntimeState` represents current active process truth. It includes the
stable process identifier, label, kind, lifecycle status, command tokens, optional
operating-system PID, timestamps, exit code, correlation fields, error message,
and metadata.

`ProcessExitRecord` represents terminal process facts. Terminal process state
leaves active runtime state and remains available through audit history.

These contracts do not define domain process recipes, automatic startup work,
GUI behavior, Qt/PySide behavior, or connection/websocket tracking.
