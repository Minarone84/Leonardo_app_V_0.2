# Connection Suite - Workflows and Lifecycles

**Targeted revision: 2026-10-28 (R07).** Reconciles accepted R01-R06 and current source. Earlier edition dates and validation counts below remain historical; R08 integrated and R09 native acceptance are separate, not performed by this documentation revision.

**Updated:** 2026-10-09

**Development status:** Connection Suite is still incomplete and will undergo further development. Its structure can still change significantly. This document describes the current implementation, not a frozen future design.

Companions: [scope](CONNECTION_SUITE.md), [architecture](CONNECTION_ARCHITECTURE.md), [contracts](CONNECTION_DATA_CONTRACTS.md), [illustrated map](Leonardo_V2_Connection_Suite_Complete_Map.pdf). This manual follows current mutation and failure boundaries; a successful UI action is not a promise of persisted acceptance.

## 1. Open, select and prepare

Composition lazily opens the retained Connection home and Download Manager. The presenter fills provider choices, derives market/timeframe choices from static provider capabilities, and starts with a blank request. Changing provider or market replaces choices; selections that still exist may survive the timeframe refresh, and the first available timeframe is selected when none is retained. Clear/Deselect can leave no selection, which request validation rejects.

Symbol normalization occurs when editing finishes and again when building the request. Blank numeric fields become None; invalid integers, negatives, reversed boundaries and an empty timeframe set are rejected before submission. Normalization deduplicates canonical timeframe strings while retaining their first-seen order. It does not verify that an exchange lists the symbol.

Start first checks the retained active download identity. If a download is active, it reveals the same task window before interpreting the current form. Otherwise it records the normalized request, clears prior preflight, disables Start, opens the pending review dialog and submits `ohlcv_preflight`. Submission failures reenable the form and show the error.

## 2. Provider/session lifecycle

1. Create a provider adapter through the factory registry. Capability-only queries stop here; they do not open HTTP sessions.
2. Ensure `connection.<provider>.historical_rest` exists. Increase active-session count; the first session marks `connecting`.
3. Await adapter `open()`, then mark `connected`. Bybit owns one aiohttp ClientSession per adapter instance.
4. Execute the caller inside the async context. A normal Exception marks the coarse connection `degraded` if other sessions are counted, otherwise `failed`.
5. In `finally`, attempt provider close, then decrement the count. A clean final exit marks `disconnected`; a clean exit with remaining sessions marks `connected`. A failed final session retains failure state. A close exception is propagated if there was no ordinary execution exception; otherwise the original exception retains precedence.

Cancellation is re-raised and closure is attempted; it is not classified as an ordinary provider failure by the service. A failure while closing can still be reported. Concurrent counts describe the current runtime, not an account health guarantee, and later successful session transitions can replace earlier coarse degraded status.

Provider instances, sessions and counts are not saved across application restart. They are not persistent live exchange connections.

## 3. Preflight and confirmation

One provider session serves sequential timeframe inspections. For each canonical MarketId, inspect CSV/sidecar existence, local identity/count/range and metadata issues; then build the plan using provider bounds. Inspection may use a matching size/mtime sidecar fast path, otherwise scan CSV identity. It is not a full SHA/quality acceptance check.

For an automatic new dataset with no explicit boundaries and zero local rows, `can_download` is false if the oldest timestamp cannot be resolved. The batch is confirmable only if it has items and every item is confirmable. Other local warnings are displayed; `can_download` is not a general proof that every later read/write will succeed.

The dialog shows mode, local/planned range, expected bars/pages, limit and ready/up-to-date/blocked state. Monthly or unknown bounds make estimates indeterminate. The matching result alone populates the review; callbacks for an obsolete preflight ID are ignored.

Closing the review or manager clears its request/preflight state, removes the active preflight identity and requests cancellation. A late result cannot revive the cancelled review. Confirm hides the review, retains the confirmed request separately, resets task presentation/notification state and submits `ohlcv_download`. There is no persistent queue or preflight save file.

Execution rereads and rebuilds each plan under the dataset lock; preflight does not hold a lock or freeze provider time. The service API accepts a DownloadBatchRequest rather than a preflight token. The GUI requires successful preflight, while a direct service caller must respect its own request/review boundary.

## 4. Automatic, custom and no-op planning

| Inputs and local state | Execution plan |
|---|---|
| No Start/End, no local rows | Discover provider oldest; find latest closed; `new_download` |
| No Start/End, existing local rows | Start at local last timestamp, retaining one-bar overlap; `update_latest` |
| End supplied | `custom_range`; end cursor is explicit End; Start may remain unknown |
| Start supplied, End absent | `custom_range`; end is latest closed or server-time fallback |

Latest-closed detection queries server time and the two most recent candles, selects the maximum timestamp whose `is_closed` flag is true and is no later than server time, and may fall back to server time with `derived_from_now=True`. That fallback is an estimate, not evidence of a known closed bound.

Only `update_latest` with known local start and latest-closed timestamp can be `up_to_date`, when local last >= latest closed. Under the lock, this branch runs read-only preliminary validation and returns `up_to_date=True`, zero fetched rows and no downloaded range. It does not call Store write/finalize, publish acceptance, rewrite lineage, change file times, or notify DMS of a mutation. Existing malformed CSV can fail on the initial read before reaching this branch; missing/invalid/stale/partial metadata is not silently repaired.

An automatic tail update does not imply complete history or gap repair. End-only custom requests may have no known lower bound. The exact estimator and page termination rules appear in contracts section 2.

## 5. Download, merge and finalization

For each selected timeframe:

1. Acquire the shared lock for the full MarketId. Read current candles, inspect current evidence and recompute the plan. Emit `plan_ready`.
2. On a non-no-op plan, fetch pages backwards from the end cursor with the bounded request retry policy. Convert provider records to Candle, sort ascending and filter to inclusive planned bounds. For automatic requests, the first page excludes the newest open/out-of-bound candle; explicit custom ranges do not apply that automatic open-candle exclusion.
3. Merge by timestamp. Incoming values replace existing values at equal timestamps; preserve other rows and sort ascending. `fetched_rows` counts filtered incoming rows, including overlap/replacements, rather than unique additions.
4. Persist the whole merged list through Store as `partial/unknown`. Await the write even if cancellation arrives. Only after a successful settled write update counters, emit `page_persisted` and audit it. DMS notification uses that event and the final source-evidence witness.
5. Stop on an established completion condition (lower bound reached, empty provider/filter result, or a negative end cursor). Otherwise set the next cursor to oldest returned timestamp minus one millisecond. A non-decreasing cursor fails. Natural exhaustion of 10,000 pages fails before finalization; saved pages remain partial.
6. If there are no existing or downloaded candles, fail. Otherwise run preliminary checks and finalize the sidecar as `committed/unknown`, preserving warnings and lineage. The CSV and sidecar write/publication rules remain Store-owned. Preliminary errors do not themselves turn this normal task result into canonical acceptance.
7. Emit preliminary feedback, return the item, emit item/batch progress and move to the next timeframe. Only after all timeframes succeed return DownloadBatchResult and normal batch completion.

Earlier completed timeframes are not rolled back if a later one fails. The batch failure path rethrows and returns a failed Core task, with the completed prefix in audit evidence rather than a successful partial batch result. Provider closure and lock exit occur through their context managers.

An empty custom-range fetch with existing candles can still reach step 6. It is not the explicit no-op branch and may reset acceptance without changing CSV bytes. Do not infer immutability from a zero fetched-row count or absence of page events.

On exit, including a failed operation, `source_evidence_changed` reports changed or uncertain CSV/sidecar witnesses (presence/path, size, mtime_ns and inode). Thus metadata-only finalization and a CSV replacement followed by sidecar failure also inform the selected DMS context. Unchanged witnesses on a true no-op or pre-mutation failure do not create a notification. The normal per-market presenter deduplication remains.

## 6. Cancellation and failure boundaries

| Timing | Surviving state and observation |
|---|---|
| Preflight or lock/provider wait | Cancellation propagates; no new mutation implied |
| Provider/retry await before first page | No successful new page has been recorded; earlier durable state survives |
| In-flight Store page write | Shielded write settles; successful page is recorded, then cancellation re-raised |
| Between pages | Persisted prefix remains partial/unknown; no rollback |
| Read-only no-op validation | Existing CSV/sidecar evidence stays unchanged |
| During preliminary validation after pages | Pages already saved survive; finalization may not yet have occurred |
| In-flight finalization | Shielded finalization settles; cancellation may be reported after committed/unknown evidence exists |
| Page-ceiling or exhausted request error | Task fails; no synthetic completion or automatic repair/resume |
| File replacement/sidecar publication failure | Error propagates; inspect actual files and evidence, not counters alone |

Shielding protects a begun mutation from task cancellation; it is not a cross-file transaction or a guarantee that operating-system file replacement succeeds. If CSV replacement succeeds and sidecar replacement fails, mismatched/missing evidence may remain. The consumer's acceptance check must reject stale evidence. The earlier intermittent Windows CSV replacement mechanism remains unidentified; existing controlled Maintenance recovery is the supported route when eligible.

Stop targets the retained active task ID and disables itself while requesting cancellation; an exception reenables it. Core can report that the task already settled. Cancellation intent is not an instantaneous promise of stopped work or restored data.

The downloader emits item-cancel details (pages/rows, persisted range, downloaded range, persistence status, completion flag) and batch-cancel completed/remaining timeframe tuples, then rethrows cancellation. The GUI retains the last item-cancel event for its recap. It does not aggregate the full batch cancellation evidence, and its zero-page wording can understate preserved validation on a no-op. Inspect Maintenance/current evidence for durable truth.

## 7. Progress, identity, close and reopen

The presenter ignores all download callbacks unless their task ID matches the retained active ID. This guard precedes logs, UI changes, cancellation evidence and DMS notification. Matching page notifications are deduplicated per MarketId before the 250 ms display throttle. Page-persisted, batch-progress and page-retrying events can be coalesced; terminal handling stops the timer, flushes pending display once, then clears the active ID/request.

The task window displays request summary, current/overall percentages, live log and terminal recap. Overall progress is shown for multiple timeframes. Unknown bar estimates are not an ETA. Task stage/output tables are currently empty presentation surfaces. A matching terminal result sets Completed, Failed or Cancelled and enables OK; duplicate or stale terminal results are ignored.

Closing the manager resets its form and cancels pending preflight but does not cancel a confirmed download or erase its retained request. Closing/hiding the task dialog is not connected to Stop. Reopening the manager and pressing Start reveals the current task, even with a blank/invalid reset form. Once settled, a newly prepared request can start a later job. There is no durable task recovery after process exit.

## 8. Maintenance, canonical validation and recovery

Maintenance discovery is read-only and may list unavailable/problem datasets that Research's accepted catalog rejects. Selection controls which existing reviewed operation is available. Discovery/selection is not acceptance and does not auto-repair data.

**Validation:** Core submits a blocking job. Canonical validation streams rows, checks identity, quality, continuity, sidecar/final persistence and stable file evidence. It supports a cooperative cancellation event and row progress. Maintenance refuses publication when blockers exist; otherwise Store compares the expected CSV and sidecar size, mtime and SHA again before publishing `ok`, `warning` or `error`. Repeating identical evidence is a publication no-op. Acceptance requires a published `ok` result, including already-identical publication; a quality report alone is insufficient. Cancellation checked before publication avoids blessing a cancelled scan, but is not rollback of an already published result.

**Repair:** Prepare a read-only plan from canonical issues and safe provider-redownload ranges. Unsupported/unparseable defects remain inspect-only. On execution, revalidate the reviewed fingerprints and issue conditions after acquiring the shared dataset lock, retain it across all reviewed ranges, and reuse the downloader/provider boundary. While still holding that same lock, the finalizer records repaired evidence, runs canonical post-repair validation and constructs the result. A begun worker is drained before cancellation releases the lock; its real failure retains precedence over cancellation. Provider coverage and remaining issues determine the outcome; repaired does not automatically mean accepted. There is no automatic retry from an old plan after files change.

**Sidecar reconstruction:** Prepare a plan for eligible missing/invalid/stale evidence over a stable canonical parseable CSV. Partial evidence cannot be promoted to committed by reconstruction; orphan sidecar, unsafe/unreadable/unstable evidence and structural CSV blockers are not bypassed. After explicit confirmation, recheck reviewed state, reconstruct `committed/unknown` evidence, immediately run canonical validation and invalidate the loader cache. The application holds the dataset lock and shields this started mutation sequence; late cancellation is recorded while returning its actual result. The presenter does not offer cancellation after confirmed mutation starts.

**Controlled deletion:** Prepare fingerprints for the exact canonical CSV and optional adjacent sidecar, obtain explicit confirmation, acquire the same dataset lock and recheck evidence. Store stages canonical files under hidden deletion names; if staging fails, it attempts restoration of files already staged. Then remove the staged files and only empty canonical ancestor directories. Cleanup warnings remain explicit. No recursive pool deletion or downstream cascade is part of this operation. The application invalidates the loader cache and shields begun deletion; late cancellation does not pretend the files survived.

Maintenance's presenter tracks its active operation and refreshes discovery after terminal results. It forwards changed evidence and accepted-validation callbacks to composition. The more extensive DMS object consequences remain in [DMS lifecycles](../data_manager_docs/DATA_MANAGER_LIFECYCLES.md).

## 9. Research/DMS handoff and deletion semantics

```text
Downloaded pages: partial / unknown
  -> normal finalization: committed / unknown
  -> Maintenance canonical publication: committed (or repaired) / ok
  -> strict accepted-catalog evidence check -> trusted consumer load
```

Warning/error/unknown and partial datasets are unavailable for trusted Research use. A true up-to-date branch keeps whatever prior state existed; it neither resets accepted evidence nor upgrades rejected evidence. Metadata-only discovery is distinct from payload verification at trusted-use boundaries.

Changed or uncertain source evidence informs an open DMS selected context through its matching notification, including metadata-only and failed split writes. DMS also checks actual source identities before reusing successful cached proof, independently of GUI delivery. Acceptance is restored through canonical validation, not through a task success label. Existing Research charts and derived saved objects are not owned by the download task. Source deletion leaves their definitions/references with their respective owners; it does not delete their pools. Future attempts to resolve missing/unaccepted source data follow those owners' refusal and compatibility rules.

## 10. Shutdown and restart

Accepted GUI closure follows the existing composition/main-window guard, including Research dirty-change decisions. Once shutdown proceeds, LeonardoApp requests cancellation of pending DMS operations, then pending Analysis operations, invokes CoreRunner shutdown, then child-process shutdown, generic connection tracking shutdown and window-record closure, emits the application stop event, and closes audit output. Connection adds no independent shutdown coordinator.

Core cancellation unwinds active provider contexts and downloader locks and respects the existing mutation fences. Shutdown can fail if Core cannot settle within its timeout; documents must not promise instantaneous termination or undo. A registry state change is only a tracking transition, not the mechanism that closes an aiohttp session.

On a later startup, new services, windows and session counters are composed. Existing CSV/sidecar files remain discoverable in their actual final/partial/accepted/rejected states. Unsaved form/preflight/task-display state is not restored. No automatic resumed download, reconstructed evidence or canonical acceptance is inferred from restart.
