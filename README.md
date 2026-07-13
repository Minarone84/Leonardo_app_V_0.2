# Leonardo Light V2

Leonardo Light V2 is a modular desktop financial research and trading application.
This branch is the approved architecture-reset baseline derived from the verified
Task 0011 donor commit.

## Active governance

```text
LEONARDO_LIGHT_V2_ARCHITECTURE_GUIDELINE.md
AGENTS.md
RICK_PROTOCOL_12_COMMANDMENTS.md
RICK_CODEX_EXECUTION_PROTOCOL.md
```

These files supersede all Heavy V2 contract-first, Object Map, strict NSRR and
handwritten GUI metadata doctrines.

## Current baseline

The reset baseline preserves:

- application startup and ordered shutdown;
- one background asyncio runtime;
- task progress, completion, cancellation and failure;
- external process tracking;
- coarse connection tracking;
- window tracking;
- application-wide action registration where justified;
- JSONL and in-memory audit logging;
- Runtime Manager direct snapshots;
- Main Window and Area Suite GUI shells;
- the GUI theme system;
- stable Qt object names and action IDs;
- `AuditEventV1`, `OHLCVSidecarV1` and `MarketId`.

The reset removes:

- the global Contract Registry and internal contract parliament;
- Object Map and all trace-provider families;
- duplicated `StateStore` runtime authority;
- suite/provider/download boundary descriptor systems;
- GUI metadata, window TOMLs, roadmap JSON and parent maps;
- metadata-driven Settings Inspector and override machinery;
- production dummy-data fixtures.

## Current product status

The Core runtime and GUI shells are a clean foundation. Financial workflows are
not complete merely because their windows exist.

The next development rule is vertical delivery:

```text
user workflow
→ GUI shell
→ presenter/controller
→ Area application service
→ domain implementation
→ optional Core job
→ provider/store
→ result
→ end-to-end validation
```

Old Leonardo remains the behavioural authority for proven workflows. Heavy V2
remains donor code only.

## Developer launch

With the project environment activated:

```powershell
$env:PYTHONPATH = "$PWD\src;$PWD"
python .\tools\dev_launch_gui.py
```

The GUI launcher does not enable provider, storage, trading or other unfinished
business workflows.

## Validation

Core and schema tests:

```powershell
python -m pytest tests/core_test tests/schema_test -q
```

Full tests, including GUI smoke tests when PySide6 is available:

```powershell
python -m pytest -q
```
