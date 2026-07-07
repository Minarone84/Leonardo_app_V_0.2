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
- `CoreRunner` persistent async loop;
- `CoreRuntimeBridge` command/query/result/progress/cancel boundary;
- `TaskManager` task lifecycle owner;
- `OperationRegistry` semantic operation lifecycle owner;
- `ProcessManager` process tracking owner;
- `ConnectionRegistry` connection and websocket tracking owner;
- `WindowRegistry` and `ActionRegistry` runtime GUI identity registries;
- `RuntimeManagerBackend` read-only runtime inspection facade;
- optional read-only Object Map snapshot integration through Runtime Manager;
- runtime contract registration through the existing contract registry.

`StateStore` owns current runtime truth for the app and registered services.
`AuditLog` owns historical truth as emitted audit events.

`ServiceRegistry` can register and inspect lifecycle or capability services, but
it does not start or stop services in this phase. No domain services are
registered.

The Core foundation also constructs accepted download read-model managers and
capability catalog components. Those components expose Core-owned read models
and contracts only; they do not add Download Data execution, provider clients,
network transport, storage writers, Data Manager behavior, Analysis Suite
behavior, or trading behavior.

`LeonardoApp.startup()` transitions app state through `starting` to `running`
and registers runtime contracts. It does not silently start the persistent Core
async runtime. The async runtime starts only through the explicit app-level
`start_core_runtime()` boundary or through direct bridge use in focused Core
tests.

Startup failures transition state to `failed`, route a structured error, and
re-raise the exception. `shutdown()` transitions through `stopping` to `stopped`,
stops the Core async runtime if it was started, and remains safe when the async
runtime was never started. `stop_core_runtime()` is the explicit app-level stop
boundary for callers that need to stop the async runtime before full app
shutdown.

GUI runners may start the Core async runtime at the top-level application
boundary. Suites, windows, Runtime Manager, Object Map, providers, adapters, and
domain services must not start the Core runtime independently.

The completed Core foundation is ready for baseline preparation after the Core
completion documentation and commit phases. Major suite and provider areas remain
future work.
