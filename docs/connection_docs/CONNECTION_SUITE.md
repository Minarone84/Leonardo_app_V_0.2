# Leonardo V2 Connection Suite

**Status:** Current implementation reference, after the 9 October 2026 correction audit
**Updated:** 2026-10-09

**Development status:** Connection Suite is still incomplete and will undergo further development. Its structure can still change significantly. This document describes the current implementation, not a frozen future design.

## Reading this documentation

Read the four manuals together. They describe the implemented Connection workflow inside Leonardo, including its dependencies on Core and OHLCV. They do not define future provider, account or live-feed architecture.

| Document | Contents |
|---|---|
| This manual | Scope, supported behavior, user workflow, limitations and evidence |
| [Architecture and Leonardo integration](CONNECTION_ARCHITECTURE.md) | Production composition, authorities, execution boundaries, source map and reconstruction order |
| [Workflows and lifecycles](CONNECTION_LIFECYCLES.md) | Ordered operations, mutation points, cancellation, failures, surviving state and shutdown |
| [Data and interface contracts](CONNECTION_DATA_CONTRACTS.md) | Identities, planning, wire behavior, persistence, events, model fields, API signatures and verification matrix |

**Visual companion:** [Connection Suite - Complete Map (PDF)](Leonardo_V2_Connection_Suite_Complete_Map.pdf).
The map adds illustrated scope, composition, ownership, workflows, lifecycles and integration. It supplements these manuals; it does not replace them. "Complete Map" names the map of the current documented implementation, not a claim that Connection Suite is a completed product.

Current source and accepted tests ground this reference. Older task records and the previous August manual may describe superseded behavior. The working candidate includes accepted uncommitted changes; a Git commit identifier alone does not identify it.

## 1. Purpose and scope

Connection provides Leonardo with external-provider capabilities and provider-specific wire behavior. Its currently composed capability is public historical OHLCV access through Bybit REST. The user can inspect a proposed request, confirm a download, observe progress, request cancellation, and pass persisted data to OHLCV Maintenance for canonical validation.

```text
Connection Suite navigation shell
  -> Historical Download Manager -> review preflight -> confirm
  -> Core-supervised historical download -> OHLCV Store
  -> OHLCV Maintenance -> accepted dataset catalog -> Research / DMS
```

This chain crosses several owners. Connection does not own dataset acceptance, financial calculations, Research studies, Notebooks, Workspaces or DMS objects. OHLCV Maintenance is a neighboring OHLCV workflow accessible from the manager and main window. Its placement in this guide explains the full user journey without transferring ownership.

## 2. Implemented capability versus unfinished surfaces

| Surface or capability | Current state |
|---|---|
| Bybit public historical REST | Implemented; default production provider |
| Provider capability queries and scoped sessions | Implemented through Connection services |
| Historical request form, preflight, confirmation, task progress, Stop and recap | Wired production workflow |
| Canonical OHLCV persistence, preliminary checks | Implemented by OHLCV services |
| Maintenance discovery, validation, reviewed repair, sidecar reconstruction and controlled deletion | Implemented adjacent workflow; exact eligibility remains with Maintenance |
| Connection Suite provider/account, websocket and download-overview tables | Presentation shells; no live backend projection |
| Download task stage/output tables | Available presentation surfaces; the active presenter fills summary, progress, log and recap, not these tables |
| Accounts, credentials, private APIs, websocket subscriptions, live reconnect, order/trading gateway | Not implemented by this Connection composition |
| Additional production providers | Not registered by default |
| Persistent download queue or automatic restart/resume | Not implemented |

Refresh and Clear Log on the Connection home window are local presentation actions. They do not refresh an exchange account or create a network connection. The Historical Download Manager navigation button is wired separately by GUI composition, even though the home shell's static footer still describes unwired backend behavior.

The incomplete areas above are a description of current scope, not an approved roadmap or a commitment to retain the present class structure. Future development requires its own decisions; this edition does not authorize changes to Leonardo's existing ownership, authority or data-lifecycle policies.

## 3. Supported provider inputs

Bybit supports `spot`, `linear` and `inverse` for standard historical klines. `options` is a canonical market type elsewhere in Leonardo but is rejected by this adapter.

The displayed timeframes are `1m`, `3m`, `5m`, `15m`, `30m`, `1h`, `2h`, `4h`, `6h`, `12h`, `1d`, `1w`, `1M`. Uppercase `M` means calendar month. The adapter accepts `60m` as an alias for its `1h` wire interval; this adapter alias must not be assumed to rewrite every generic MarketId or storage path.

Symbols pass through Leonardo's canonical symbol normalization. This is syntactic normalization, not an exchange instrument-availability lookup. A valid-looking unavailable symbol may still fail or return no data at provider execution.

Start and End are optional non-negative UTC epoch timestamps in milliseconds. When both are present, Start must not exceed End. Limit is a non-negative integer; blank or zero requests the provider default. Bybit's maximum is 1,000 candles per page, and larger requested values are capped. Limit controls each ordinary data page, not the number of total rows in the request.

## 4. Normal user workflow

1. Open Connection Suite and then Historical Download Manager. Select provider, market, symbol and at least one timeframe. Select All and Clear/Deselect operate on the displayed timeframe choices.
2. Leave dates blank for automatic history/update, or enter explicit boundaries. Press Start to prepare a non-mutating preflight. Provider calls and inspection may take time, particularly oldest-candle discovery.
3. Review local data/evidence, planned ranges, page sizes, estimates and warnings for every timeframe. Unknown estimates are displayed as indeterminate. Local inspection warnings do not themselves mean the request is accepted for trusted use.
4. Confirm in the preflight window. The manager submits one batch; selected timeframes run sequentially under one scoped provider session. Each dataset is identified independently by exchange, market, symbol and timeframe.
5. Observe the task window. Stop requests cancellation of the current job. Closing the manager resets its form and cancels pending preflight, but retains any active download. Reopening and pressing Start reveals that active task rather than replacing it.
6. Review the terminal recap and inspect Maintenance where necessary. Actual downloaded/updated datasets need canonical validation before trusted use. A genuine up-to-date automatic update preserves the prior files and validation evidence exactly.
7. Use accepted datasets through the Research catalog or DMS. Connection does not automatically refresh open Research charts or recalculate derived objects.

## 5. Meaning of planning and completion

| Term | Exact meaning |
|---|---|
| `new_download` | Automatic request without local rows; discovers a lower bound and targets the latest closed candle |
| `update_latest` | Automatic request with local rows; overlaps the last local timestamp and targets the latest closed candle |
| `custom_range` | Start, End or both supplied; merges the requested range into existing data |
| `up_to_date` | Automatic update whose local last timestamp is at or beyond the latest provider closed timestamp; no persistence mutation |
| Preliminary validation | Read-only defensive feedback from the downloader; never Research acceptance |
| Completed task | Requested execution reached its normal terminal result; does not mean canonical acceptance |
| Accepted dataset | Final persistence and `validation_status="ok"`, with current canonical evidence verified by the consumer |

All modes retrieve pages backwards from the end cursor, even though the resulting CSV is sorted ascending. Automatic updates do not search for missing earlier prefixes or repair internal gaps. Preflight is an advisory snapshot, not a dataset reservation or durable plan; execution rereads and replans under the per-dataset mutation lock.

The no-op classification is the explicit `up_to_date` result. It cannot be inferred from zero fetched rows: a custom-range request that fetches nothing can still finalize an existing dataset and reset acceptance to `unknown`. A no-op neither repairs nor promotes missing, invalid, stale, partial or unaccepted evidence.

## 6. Data safety and authority

Only `OHLCVStore` performs the physical canonical writes used by this workflow. Each persisted page merges by timestamp with incoming values winning, writes a sorted CSV, and records `partial/unknown`. Normal finalization records `committed/unknown`; Maintenance owns the later canonical validation publication. Each file is atomically replaced, but the CSV and sidecar are not one cross-file transaction.

Cancellation is not rollback. A completed write is allowed to settle before cancellation is reported. Earlier pages and earlier completed timeframes survive a later cancellation or failure. Reaching the 10,000-page safety ceiling without a completion condition now fails and preserves partial evidence; it does not declare a truncated download complete.

Store, provider and UI details are specified in the [lifecycle manual](CONNECTION_LIFECYCLES.md). Do not manually edit a sidecar to bypass acceptance. Supported recovery is through the existing reviewed Maintenance operations where eligible.

## 7. Integration with the rest of Leonardo

| Neighbor | Relationship |
|---|---|
| [Core](../core_docs/LIGHT_V2_RUNTIME.md) | One runtime for jobs, cancellation, coarse connection/window summaries, actions, audit and shutdown |
| OHLCV | Owns planning, persistence, dataset locks, validation, repair, reconstruction and deletion |
| [Research](../research_docs/RESEARCH_SUITE.md) | Discovers accepted OHLCV through its catalog and loader; Connection does not own charts/studies/saved Research objects |
| [Data Manager](../data_manager_docs/DATA_MANAGER.md) | Receives actual OHLCV evidence-change and accepted-validation notifications through composition; preserves its own selected-context and object rules |
| Runtime Manager | Shows generic tasks/connections from Core; no separate operating-system process is launched for a historical download |

## 8. Known limits and evidence

The 9 October 2026 bounded correction audit passed for four approved defects: no-op evidence preservation, retained active-task identity/stale-callback rejection, oldest-candle discovery with small page sizes, and honest page-ceiling failure. The test-lifetime cleanup also passed the formerly aborted ordered GUI sequence. The underlying historical native abort mechanism remains unidentified.

Recorded implementation evidence: 2,890 repository tests passed and seven existing Windows symlink-privilege cases skipped; eight isolated native checks passed. The later independent package audit freshly passed 198 combined tests plus 27 probes and verified the unchanged full/native evidence without rerunning those two gates. This documentation task checks source, references, models and PDF layout; those earlier tests are not claimed as new runs here. Evidence directories are named in the architecture manual.

Live exchange/account behavior and private/live capabilities were not validated by those generated-provider runs. The seven skips and agent-operated native checks do not constitute independent user visual acceptance.

Two presentation limits remain explicit: cancellation recap uses the last item-cancel event, not a complete per-timeframe cancellation report; its zero-page text can say canonical validation is unknown even when cancellation of a no-op preserved previously accepted evidence. Persisted evidence, not that sentence, determines the dataset state. The old claim that the GUI always reports every completed and unfinished timeframe has been removed.

Current loading and merging operate on complete in-memory candle lists and rewrite the merged CSV per page. There is no compression, alternate storage format, automatic recovery, background resumption, or large-file parallel loading added by this documentation. These limitations do not invalidate the bounded correction verdict or imply authority to extend the product.
