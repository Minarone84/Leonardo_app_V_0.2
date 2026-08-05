# Leonardo Light V2 GUI Shell

The GUI is a replaceable Qt presentation shell. It owns windows, widgets,
layouts, user interaction, appearance, navigation, and derived display state.
It does not own provider behaviour, persistence policy, financial calculations,
validation truth, backtest mathematics, risk, or order execution.

The live Qt object tree is authoritative. Meaningful controls use stable
`QObject.objectName()` values, and appearance roles may classify editable
presentation surfaces. There is no handwritten duplicate widget tree in TOML
or JSON.

Simple GUI actions run synchronously on the Qt thread. Long-running work runs
through the shared Core runtime and returns through queued Qt signals;
background work must not mutate Qt widgets directly.

## Current workflows

Implemented production workflows are:

- Historical Download;
- OHLCV Maintenance;
- Research Suite;
- Data Manager Suite;
- Runtime Manager;
- Research persistence workflows.

Current shell-only or incomplete workflows are:

- the Connection Suite live dashboard beyond historical REST workflows;
- Analysis;
- Backtesting;
- Real-Time;
- Trading;
- application-wide Appearance Settings;
- other visibly unavailable future suites exposed by the current shell.

An incomplete shell must remain honest about unavailable behavior. Current
Research architecture and workflow details are documented in the
[Research Suite manual](../research_docs/RESEARCH_SUITE.md).

## Data Manager Suite

`data_manager_suite.window` is a tracked single-instance window composed by the
real application root. Repeated open commands focus the existing window.
Research handoff carries only a canonical `MarketId`; the Data Manager reloads
its own canonical persisted truth and focuses the matching OHLCV row.

The Suite has three top-level tabs: Catalogs, Create Database, and Update &
Reconcile. Catalogs exposes all eight persisted product families. Creation uses
nine explicit stages; update uses six explicit stages. One common operation
surface displays the Core task identity, progress, cancellation availability,
structured plan or report details, and terminal state. The window owns only
selection and presentation state; every read, write, plan, validation, and
reconciliation operation delegates through `DataManagerApplicationService`.

## Window tracking

Long-lived top-level windows that remain open until the user or application
closes them must register with the shared application `WindowRegistry` through
the application window tracker. Short modal confirmation prompts do not need an
independent durable registry identity.
