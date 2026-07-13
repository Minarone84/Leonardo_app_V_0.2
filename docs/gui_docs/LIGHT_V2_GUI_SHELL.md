# Leonardo Light V2 GUI Shell

The GUI is a replaceable Qt presentation shell.

It owns windows, widgets, layouts, user interaction, appearance, navigation and
derived display state. It does not own provider behaviour, persistence policy,
financial calculations, validation truth, backtest mathematics, risk or order
execution.

The live Qt object tree is authoritative. Meaningful controls use stable
`QObject.objectName()` values and optional action/appearance properties. There
is no handwritten duplicate widget tree in TOML or JSON.

Short Qt operations run directly on the GUI thread. Long-running work is
submitted by an application service to Core and returns through queued Qt
signals.

Production shells start in honest empty/unavailable states. Test fixtures belong
under tests or explicit demo tools and must not be presented as completed
application behaviour.
