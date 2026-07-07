# Download Data Runtime Summary

This document records the first read-only Runtime Manager summary integration
for Download Data runtime read models.

Runtime Manager consumes optional injected `DownloadDataRuntimeSummary` values
and exposes one compact `download_data_runtime` section. The provider is
explicit injection only. If no provider is injected, the section remains an OK
unavailable read model.

## Scope

The summary reports compact counts for:

- workflows
- selections
- preflight recaps
- progress recaps
- completion recaps
- output references
- storage targets
- partial persistence records
- expected and completed steps
- expected and downloaded bars
- warnings, errors, unavailable summaries, and last activity

The section is read-only. It is display/query metadata, not a control surface.

## Boundaries

This phase does not implement Download Data execution, adapter calls, provider
clients, network/API/websocket/subscription behavior, storage writes,
cancellation behavior, Runtime Manager controls/actions, Object Map service
changes, GUI behavior, Data Manager integration, ProviderRegistry discovery, app
startup changes, old Leonardo code import, or AI helper behavior.

Runtime Manager does not import Download Data Object Map helpers and does not
modify those helpers in this phase.

Core supervises runtime workflow state. Core does not own persisted OHLCV truth.
Storage/Data owns persisted OHLCV truth. Provider/Exchange owns capability and
API facts. GUI owns selection, display, and intent. Runtime Manager only reads
summary values supplied by composition.

Partial persistence remains diagnostic state. It does not imply accepted,
loadable, validated, repaired, or clean data.

## Diagnostics

Runtime Manager redacts and bounds diagnostics before exposing them in section
metadata. Summary metadata must not contain credentials, tokens, secrets,
passwords, API keys, authorization material, raw clients, sockets, payloads, raw
responses, provider objects, adapters, storage writers, handles, GUI objects,
Data Manager objects, or runtime task objects.

## Validation

The focused validation targets are:

```text
python -m pytest tests/contracts_test/test_runtime_inspection_contracts.py -q -p no:cacheprovider
python -m pytest tests/core_test/test_runtime_manager_backend.py -q -p no:cacheprovider
```
