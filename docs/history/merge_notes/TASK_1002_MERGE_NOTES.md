# Task 1002 Merge Notes

Task 1002 is based on merged Task 1001 commit `9fab7b7b3686f518b5dbb1d1eeae2488208e2e0d`.

Production change:

- `src/leonardo/gui/windows/ohlcv_download_preflight_window.py`

Test changes:

- `tests/gui_test/test_light_gui.py`
- `tests/gui_test/test_historical_download_wiring_static.py`

Task evidence:

- `_task_1002_preflight_row_shape/AUDIT_REPORT.md`
- `_task_1002_preflight_row_shape/VALIDATION.txt`
- `_task_1002_preflight_row_shape/CHANGED_FILES.txt`

No Research Suite source file is modified. If a parallel branch changed the same
preflight window, preserve the `_normalize_table_rows(...)` calls in all three table
setter methods.
