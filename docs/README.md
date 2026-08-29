# Leonardo V2 Documentation Authority Map

**Status:** Current documentation index
**Updated:** 2026-08-05

## Purpose

This directory separates current operational manuals from historical
implementation evidence. Use this index to locate the current authority for a
subject; do not infer authority from a document's age or filename.

## Current authoritative manuals

- [Core Runtime](core_docs/LIGHT_V2_RUNTIME.md)
- [Connection Suite](connection_docs/CONNECTION_SUITE.md)
- [Research Suite](research_docs/RESEARCH_SUITE.md)
- [Data Manager](data_manager_docs/DATA_MANAGER.md)
- [GUI Shell](gui_docs/LIGHT_V2_GUI_SHELL.md)
- [GUI Theme System](gui_docs/GUI_THEME_SYSTEM.md)
- [Application GUI Smoke](gui_docs/LIGHT_V2_APPLICATION_SMOKE.md)

These manuals describe current application behavior within their subject
boundaries.

## Governing root documents

The repository-root governance authorities remain:

- [Architecture guideline](../LEONARDO_LIGHT_V2_ARCHITECTURE_GUIDELINE.md)
- [Agent instructions](../AGENTS.md)
- [Rick Protocol 12 Commandments](../RICK_PROTOCOL_12_COMMANDMENTS.md)
- [Rick Codex execution protocol](../RICK_CODEX_EXECUTION_PROTOCOL.md)

## Historical evidence

The [historical archive](history/README.md) contains task records, merge notes,
completed or superseded workplans, governance revision notes, and scratch
material. Nothing under `docs/history/` is current application authority unless
a current governing or operational document explicitly references it.

Task records describe the repository at the time of the named task and may
contain limitations that later work superseded. When current behavior is
disputed, current source code and accepted tests override stale historical
prose unless governing authority explicitly says otherwise.
