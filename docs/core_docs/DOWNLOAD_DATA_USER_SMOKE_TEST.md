# Download Data User Smoke Test

## Scope

This smoke test covers the default sandbox Download Data path only. It does not
write to production storage and does not make a default live Bybit call.

## Launch

From the repository root:

```powershell
$env:PYTHONPATH="src"
python tools/dev_launch_gui.py --settings-base-dir runs/gui_dev_settings
```

## Steps

1. Open Main Window.
2. Open Download Data.
3. Confirm the empty selection blocked state.
4. Select Bybit / spot / BTCUSDT / 1m / limit 10.
5. Confirm the selection recap.
6. Click Preview Preflight.
7. Confirm preview does not execute or write output.
8. Click Start.
9. Confirm progress reaches 100.
10. Confirm the final recap shows:
    - `new_file` on the first run;
    - completed status;
    - bars written;
    - CSV path;
    - metadata path;
    - `accepted=false`;
    - `loadable=false`;
    - `validated=false`;
    - sandbox-only notice.
11. Repeat the same selection.
12. Confirm `update_existing`.
13. Confirm there is no default live API call.
14. Confirm there is no real project `data/historical` write.

## Optional Live Smoke

Optional live Bybit smoke is opt-in only. It requires
`LEONARDO_ALLOW_LIVE_BYBIT_SMOKE=1` or an explicit `allow_live=True` call. It
remains sandbox-only and is not part of default user smoke validation.

## Non-Goals

This smoke test does not validate production live download behavior, OHLCV
Maintenance acceptance, Data Manager integration, accepted/loadable/validated
dataset state, Runtime Manager controls, Object Map mutation, cancellation, or
AI helper behavior.
