# Task 1002 Audit Report: Preflight Table Row Shape Repair

## Audit

The local Task 1001 merge raised `AttributeError: 'tuple' object has no attribute 'get'`
when the Historical Download presenter opened the preflight window.

Confirmed cause:

- `HistoricalDownloadPresenter` intentionally supplies compact GUI-local tuple rows.
- `OhlcvDownloadPreflightWindow` declared tuple-compatible setter signatures.
- The setters forwarded those tuples directly to `populate_table()`.
- `populate_table()` correctly expects mapping rows and calls `row.get(...)`.

The same mismatch affected request summary, validation checklist, and workload estimate
surfaces. The GUI/domain boundary remained correct; no Bybit, Core, OHLCV, persistence,
or Research behavior required modification.

Risk: low and GUI-local.

## Update

- Added one preflight-window-local normalization helper that converts either mapping
  rows or positional sequence rows into mappings keyed by the target table columns.
- Applied normalization to request summary, validation checklist, and workload estimate.
- Added a PySide6 regression test covering the exact tuple rows sent by the presenter.
- Strengthened the static GUI wiring test so the repair remains visible when PySide6 is
  unavailable.

No Research Suite files were changed.

## Validation

Commands/results:

- `python -m compileall -q src tests tools` — PASS
- Focused historical-download/Core/Connection/OHLCV tests — 21 passed
- Full suite — 48 passed, 1 skipped
- `git diff --check` — PASS
- Direct AST-isolated tuple normalization probe — PASS

The skipped module is the existing PySide6 GUI runtime suite because PySide6 is not
installed in the audit container. The added runtime regression test will execute in the
user's local PySide6 environment.

## Original-Code Comparison

Changed production boundary:

- `src/leonardo/gui/windows/ohlcv_download_preflight_window.py`

Changed tests:

- `tests/gui_test/test_light_gui.py`
- `tests/gui_test/test_historical_download_wiring_static.py`

No provider, OHLCV, Core, persistence, composition, launcher, or Research implementation
was changed.

## Verdict

PASS WITH LOCAL GUI SMOKE.
