# Leonardo V2 Documentation Authority Map

**Status:** Current documentation index
**Updated:** 2026-10-28 (targeted R07 reconciliation; preceding index edition 2026-10-21).

## Purpose

This directory separates current operational manuals from historical
implementation evidence. Use this index to locate the current authority for a
subject; do not infer authority from a document's age or filename.

## Current authoritative manuals

- [Core Runtime](core_docs/LIGHT_V2_RUNTIME.md)
- [Connection Suite](connection_docs/CONNECTION_SUITE.md)
- [Research Suite](research_docs/RESEARCH_SUITE.md)
- [Data Manager](data_manager_docs/DATA_MANAGER.md)
- [Data Analysis Suite](analysis_docs/DATA_ANALYSIS_SUITE.md)
- [Post-discovery refinement](analysis_docs/POST_DISCOVERY_REFINEMENT.md)
- [Variation Analyzer and Dynamic Binning](analysis_docs/VARIATION_AND_DYNAMIC_BINNING.md)
- [GUI Shell](gui_docs/LIGHT_V2_GUI_SHELL.md)
- [GUI Theme System](gui_docs/GUI_THEME_SYSTEM.md)
- [Application GUI Smoke](gui_docs/LIGHT_V2_APPLICATION_SMOKE.md)

These manuals describe current application behavior within their subject
boundaries. The 2026-10-28 Core, Connection and DMS map revisions accompany the
accepted R01-R06 reconciliation. Their retained older test counts belong to
the original editions, not fresh R07 product validation. Original map bytes and
audit reports remain historical evidence. Research and Analysis manuals/maps
retain their own stated editions except the named Research lifecycle corrections.

Core companions: [architecture](core_docs/CORE_ARCHITECTURE.md),
[lifecycles](core_docs/CORE_LIFECYCLES.md), [contracts](core_docs/CORE_DATA_CONTRACTS.md)
and [map](core_docs/Leonardo_V2_Core_Complete_Map.pdf). DMS companions:
[architecture](data_manager_docs/DATA_MANAGER_ARCHITECTURE.md),
[lifecycles](data_manager_docs/DATA_MANAGER_LIFECYCLES.md),
[contracts](data_manager_docs/DATA_MANAGER_DATA_CONTRACTS.md) and
[map](data_manager_docs/Leonardo_V2_Data_Manager_Suite_Complete_Map.pdf).

The Data Analysis Suite GUI connects saved databases to the statistical backend through Variation & Binning and Trend Start Patterns. Its references include the [variation system guide](analysis_docs/VARIATION_AND_DYNAMIC_BINNING.md), [API and data reference](analysis_docs/VARIATION_API_REFERENCE.md), [worked examples](analysis_docs/VARIATION_EXAMPLES.md), [trend-start workflow](analysis_docs/TREND_START_PATTERNS.md) and [post-discovery refinement](analysis_docs/POST_DISCOVERY_REFINEMENT.md). The latter explains pinned rules, granular evaluation, fixed horizons, family/date restrictions, linked inspection and bounded sensitivity. The wider Suite remains incomplete and may change significantly; code/package acceptance is separate from final integrated validation, native acceptance and predictive validity.

The Connection Suite reference now includes its [architecture](connection_docs/CONNECTION_ARCHITECTURE.md), [lifecycles](connection_docs/CONNECTION_LIFECYCLES.md), [data/interface contracts](connection_docs/CONNECTION_DATA_CONTRACTS.md) and an additive [Complete Map PDF](connection_docs/Leonardo_V2_Connection_Suite_Complete_Map.pdf). Connection Suite is still incomplete, will undergo further development, and its structure can still change significantly. These documents map its current implementation without freezing its future design.

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
