# Leonardo Light V2 Governance Revision Notes

**Date:** 2026-07-14
**Scope:** Operational governance hygiene only
**Architecture guideline:** unchanged at version 2.3

## Updated files

- `AGENTS.md`: version 2.4
- `RICK_CODEX_EXECUTION_PROTOCOL.md`: version 2.4
- `RICK_PROTOCOL_12_COMMANDMENTS.md`: version 2.5

## Governing changes

1. Codex/Goblin has zero discretionary authority.
2. The accepted task is a closed execution specification.
3. Unsolicited improvement, refactoring, cleanup, renaming, restyling, optimisation, modernisation, adjacent fixes, and test changes are forbidden.
4. Any missing material decision is a stop condition returned to Rick.
5. One working tree has one modification owner.
6. Local task closure is `apply → validate → explicit staging → local commit → clean tree → stop`.
7. Pushes and pull requests are optional explicit checkpoints, not mandatory task ceremony.
8. Patch scripts must be guarded, argument-safe, and resumable.
9. Generated `_task_*` audit workspaces, caches, bytecode, and replay folders must not be tracked or included in clean baseline packages.
10. The architecture guideline remains the approved version 2.3 baseline.
