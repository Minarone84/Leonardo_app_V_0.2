# Core Runtime Foundation

The Core runtime foundation provides the first composition root and base runtime
services for Leonardo V2.

Included components:

- `LeonardoApp` composition root;
- default app configuration and runtime paths;
- bounded in-memory audit log;
- runtime state store;
- development Administrator session manager;
- user policy checks;
- service registry;
- error router;
- runtime contract registration through the existing contract registry.

`StateStore` owns current runtime truth for the app and registered services.
`AuditLog` owns historical truth as emitted audit events.

`ServiceRegistry` can register and inspect lifecycle or capability services, but
it does not start or stop services in this phase. No domain services are
registered.

`LeonardoApp.startup()` transitions app state through `starting` to `running`.
Startup failures transition state to `failed`, route a structured error, and
re-raise the exception. `shutdown()` transitions through `stopping` to `stopped`
and is idempotent.

This phase does not include GUI, CoreBridge, async runtime, TaskManager,
ProcessManager, WindowRegistry, ActionRegistry, OperationRegistry,
Connection/WebSocket tracking, Data Manager, workspace/chart, financial tools,
or old-code reuse.
