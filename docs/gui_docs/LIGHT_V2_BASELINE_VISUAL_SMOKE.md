# Leonardo Light V2 Baseline Visual Smoke

Use this smoke after installing the frozen reset baseline.

1. Launch `python tools\dev_launch_gui.py` in the `py312_Leo` environment.
2. Confirm the Main Window opens without traceback or frozen controls.
3. Open Connection, Research, Data Manager, Analysis and Trading Suite shells.
4. Open Runtime Manager and press **Refresh**.
5. Confirm the Runtime Manager lists the open windows and registered actions.
6. Move, resize and focus several windows while the others remain responsive.
7. Close the child windows and then the Main Window.
8. Confirm the process exits cleanly and no shutdown traceback is printed.

Accepted baseline expectations:

- unfinished workflows display honest unavailable or empty states;
- no provider, download, analysis, backtest or trading operation is implied to
  be implemented;
- the Leonardo theme remains applied;
- stable window and action identities remain intact;
- no GUI metadata, Object Map or contract-registry machinery is required.
