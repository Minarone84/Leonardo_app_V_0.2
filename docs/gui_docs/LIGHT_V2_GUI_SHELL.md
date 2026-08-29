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
real application root. A newly created Suite opens maximized with normal desktop
chrome. Repeated open commands focus the existing window while preserving its
current maximized or restored state and geometry. Research handoff carries only
a canonical `MarketId`; Data Manager reloads its own canonical persisted truth
and makes that market active.

The complete accepted-and-rejected OHLCV catalog is presented in the dedicated
tracked selector `data_manager.dataset_selector.window`. The selector provides
cascading Exchange, Market Type, Symbol, and Timeframe filters, two explicit
metadata-search fields, a catalog-aware help dialog, one active-dataset row, and
content-derived table sizing. The full multi-row table supports typed
presentation-only text, number, and UTC sorting while preserving the selected
domain identity; the one-row Active Dataset summary remains unsorted. Repeated
open commands reuse the selector, and it closes with the Data Manager Suite.

The Suite has three top-level tabs: Catalogs, Create Database, and Update &
Reconcile. The main Catalogs family list exposes seven non-OHLCV product
families; OHLCV selection is intentionally confined to the selector. Creation
uses nine explicit stages and update uses six explicit stages. `Create
Artifact...` provides accepted Direct Artifact creation, and `Batch
Constructs...` provides reviewed Batch planning, execution, and a local terminal
report.

The responsive Suite body uses `3:1` for Workspace to Operation, `7:3` for the
upper region to the bottom strip, and `1:1` for Inspector to Revision History.
The Inspector and Revision History strip spans the full width. Major panels and
tables resize with the window. The central Catalog family table supports typed
presentation-only sorting through `sort_data_manager_rows(...)`; sort state is
retained per family and selected domain identity remains attached to the
displayed row. Inspector, Revision History, and Operation details remain
unsorted.

One common Operation surface is the only live Data Manager progress, Core task,
cancellation, and operation authority. On first open it presents deterministic
`Loading Data Manager` foreground warm-up: initial reconciliation succeeds,
product catalogs are scanned and applied, then warm-up completes. Failed warm-up
stays visible and retryable. After warm-up, background reconciliation is
autonomous, asynchronous, non-blocking, and independent of foreground Operation
ownership. The window owns only selection and presentation state; every read,
write, plan, validation, and reconciliation operation delegates through
`DataManagerApplicationService`.

Task 1064 is closed. Tasks 1065, 1066, and 1067 remain. Use the [Data Manager
manual](../data_manager_docs/DATA_MANAGER.md) for the current boundary.

## Window tracking

Long-lived top-level windows that remain open until the user or application
closes them must register with the shared application `WindowRegistry` through
the application window tracker. Short modal confirmation prompts do not need an
independent durable registry identity.
