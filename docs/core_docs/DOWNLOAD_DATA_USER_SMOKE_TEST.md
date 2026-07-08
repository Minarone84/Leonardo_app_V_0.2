# Download Data User Smoke Test

Status: retired historical reference.

This document records a removed sandbox Download Data smoke path. It is not a
current validation procedure for Leonardo V2.

## Current Truth

- The old sandbox/fixture Bybit Download Data execution path was removed from
  active source.
- No active source executes downloads, calls Bybit, writes sandbox output, or
  writes production OHLCV storage.
- The Connection Suite Download Manager GUI is shell-only.
- Static Bybit exchange metadata remains available under the Connection
  boundary, but it does not create transport, execution, or storage behavior.

## Replacement Validation Scope

Current validation for this area is limited to:

- contract tests for Download Data, provider, suite, and execution boundary
  shapes;
- GUI shell tests for Connection Download Manager windows and local intent;
- static checks proving removed builder, execution, provider, storage, and
  `download_data` runtime paths remain absent.

A future live or fixture-backed Download Data smoke test must be introduced by
a dedicated Connection Suite execution phase with explicit provider, storage,
and safety boundaries.
