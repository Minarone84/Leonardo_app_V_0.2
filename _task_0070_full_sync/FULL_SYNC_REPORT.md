# Task 0070 Fully Synchronized Patch

## Inputs

- `Leo_V2_Light_partially_patched.zip`: current local snapshot supplied by the user.
- `Leo_V2_0070_PATCH_AUTOSCALE_20260714_0105.zip`: audited four-file autoscale toolbar patch.

## Applied corrections

1. Preserved the cumulative Tasks 0069–0070 implementation.
2. Preserved the corrected splitter pane-size authority from the partially patched snapshot.
3. Applied the integrated `Disable Autoscale` / `Enable Autoscale` toolbar control.
4. Updated the corresponding static and PySide6 integration tests.
5. Updated the Task 0070 documentation.

## Rejected inputs

The uploaded PowerShell apply/package scripts were not included because earlier copies contained parser or execution-flow defects. This package is a complete synchronized repository snapshot rather than a script-generated partial patch.

## Boundaries preserved

- No provider behavior changed.
- No Download Data behavior changed.
- No OHLCV write, validation, or repair behavior changed.
- No Financial Tool behavior was added.
- No persistence behavior was added.
- No Git write operation was performed.

## Validation

- Python compile validation: PASS.
- Focused Task 0070 suite: 10 passed, 2 skipped (PySide6 unavailable).
- Full repository suite: 187 passed, 4 skipped (PySide6 unavailable).
- Autoscale patch internal SHA-256 manifest: PASS.
- Generated/cache/runtime data excluded from this package.

## Remaining gate

Run the local PySide6 visual smoke after mirroring this package. Confirm autoscale toggle, manual vertical interaction, volume synchronization, splitter resizing, hide/show proportions, and resident-refill alignment before creating the final accepted POST milestone.
