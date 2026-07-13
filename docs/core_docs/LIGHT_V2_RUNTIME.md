# Leonardo Light V2 Runtime

`LeonardoApp` is the single composition root.

Core owns generic application lifecycle and long-running execution:

- `CoreRunner`: background asyncio event loop;
- `TaskManager`: canonical task lifecycle;
- `ProcessManager`: external process lifecycle;
- `ConnectionRegistry`: coarse operational connection summaries;
- `WindowRegistry`: window runtime state;
- `ActionRegistry`: application-wide discoverable actions where justified;
- `AuditLog`: historical evidence;
- `RuntimeManagerBackend`: read-only aggregation of direct manager snapshots.

Core does not define provider, OHLCV, financial, research, analysis, backtest or
trading semantics.

Current runtime state lives with the manager that owns it. Runtime Manager rows
are disposable read models. Audit history is persisted separately.
