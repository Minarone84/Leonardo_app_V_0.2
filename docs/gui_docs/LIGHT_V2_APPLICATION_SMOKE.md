# Leonardo Light V2 Application GUI Smoke

This procedure supersedes the old reset-baseline visual smoke. It checks the
current application-level GUI lifecycle without duplicating the detailed
Research acceptance procedure.

1. Activate the `py312_Leo` environment and launch the application with
   `python tools\dev_launch_gui.py`.
2. Confirm the Main Window opens without a traceback and that application
   navigation remains responsive.
3. Open Runtime Manager. Invoke the command again and confirm the existing
   single-instance window is reused or focused.
4. Open Historical Download Manager. Invoke the command again and confirm the
   existing single-instance window is reused or focused.
5. Open OHLCV Maintenance. Invoke the command again and confirm the existing
   single-instance window is reused or focused.
6. Open Research Suite. Invoke the command again and confirm the existing
   single-instance window is reused or focused.
7. Refresh Runtime Manager and confirm the tracked Main Window, Runtime
   Manager, Historical Download Manager, OHLCV Maintenance, and Research Suite
   windows appear with their current lifecycle state.
8. Confirm the bundled Leonardo theme is applied coherently across the open
   windows and local control states.
9. Confirm unavailable suites remain honestly disabled or shell-only. Do not
   treat Data Manager as accepted through this smoke.
10. Close the Main Window and confirm tracked windows close and the shared Core
    runtime settles without a shutdown traceback or hanging process.

For Research-specific workflow and acceptance details, use the
[Research Suite manual](../research_docs/RESEARCH_SUITE.md).
