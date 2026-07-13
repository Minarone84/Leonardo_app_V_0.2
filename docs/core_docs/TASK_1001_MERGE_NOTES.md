# Task 1001 Merge Notes

Task 1001 was based on merged Task 1000 commit `4d34a15`.

## Source files changed

```text
src/leonardo/gui/presenters/historical_download_presenter.py
src/leonardo/gui/windows/historical_download_manager_window.py
src/leonardo/gui/windows/ohlcv_download_preflight_window.py
```

## Tests changed

```text
tests/connection_test/test_provider_registry.py
tests/gui_test/test_historical_download_wiring_static.py
```

## Research branch considerations

No Research Suite implementation file was changed.

The likely merge surface is limited to GUI composition only if the parallel
Research branch independently modifies the Historical Download presenter or its
windows. Preserve both branches' service wiring; do not replace the presenter
with GUI-owned provider or OHLCV logic.

## Post-merge validation

```text
python -m compileall -q src tests tools
python -m pytest -q
python tools/dev_launch_gui.py
```

Visually verify blank initial state, close/reset, immediate preflight display,
provider-failure display, and Research Suite behavior in the same process.
