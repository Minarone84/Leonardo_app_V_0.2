# Task 1017 Research Execution, Apply and Save

Task 1017 adds the first Research Study runtime. A Study is a chart-session-local
application of full Financial Tool result or saved artifact truth. Study identity
is distinct from Financial Tool, recipe, artifact, renderer, pane, and workspace
identity.

## Authorities

- Task 1014 remains the authority for Financial Tool specifications, output
  semantics, source compatibility, renderability, style-driver eligibility, and
  pane recommendations.
- Task 1015 remains the only calculation and runtime-output authority.
- Task 1016 remains the only artifact, recipe, serialization, lineage, and
  persistence authority.
- Task 1017 owns chart-local Study identity, ordered Study state, source
  resolution, full-result retention, resident projection, Apply, explicit Save,
  and Core-supervised Study jobs.

## Apply

Live Apply adapts the complete accepted `HistoricalDataset`, resolves explicit
OHLCV, Study, or artifact sources, invokes Task 1015 exactly once, retains the
validated full result, and derives a resident-only projection. It writes no
recipe or artifact. Applying a saved artifact validates and loads it only through
`ArtifactService`, reconstructs Task 1015 result truth, and invokes no
calculation.

Every loaded artifact is checked against the active in-memory dataset after
Task 1016 current validation. Its recipe MarketId, source CSV fingerprint,
coverage, and complete timeline must match the active `HistoricalDataset`.
Artifact source values enter calculation frames by position only after that
complete timeline proof; Pandas index labels never control source alignment.
Task 1017 also requires every Study and persisted artifact source reference to
match the canonical Task 1015 selector roles. Referenced artifacts are validated
recursively for numeric, analysis-usable output semantics and Task 1014 source
family compatibility. UTC peak and trough references must be the exact
Peaks & Troughs output pair for the resolved trend fractal window.

The same canonical selector authority identifies inline OHLCV roles as well as
external Study and artifact roles. Task 1014 source-family restrictions are
evaluated against their combined semantic source view for Study construction,
Save, artifact Apply, and recursive artifact lineage. Consequently Braids and
Braid Instability require all-indicator, all-oscillator, or all-construct
same-family inputs; inline or mixed OHLCV inputs are invalid. OHLCV-capable
constructs retain their documented inline OHLCV behavior.

Every Task 1017 artifact read uses the same public-API sequence: current
validation, load, active-dataset and recursive Research-semantic validation,
then a final current validation. A source change during that sequence returns no
Study, source value, durable reference, or idempotent Save result.

Duplicate same-configuration Applies receive distinct chart-local Study IDs.
Resident movement reprojects stored full results by global position and never
recalculates.

## Projection

Projection preserves exact resident timestamps. Only Task 1014 renderable
outputs enter render series. Non-renderable outputs marked as style drivers may
enter the separate style-driver mapping. Other analysis-usable outputs remain in
the full Study result. Pane values are recommendations only; Task 1018 owns pane
and workspace behavior.

## Save

Save persists the exact stored full result through `ArtifactService` without
recalculation and links the same Study after callback acceptance. It never
creates a second Study. Transient Study references are chart-session state and
cannot become durable IDs. Every transient dependency must first have a current
saved artifact; its role, artifact ID, and requested output then become an
`ArtifactSourceRefV1`. Existing durable artifact sources remain durable lineage.

An already-linked Study is idempotent only when the current loaded artifact
matches its exact artifact ID, recipe ID, kind, tool key, durable source
references, configuration, output names, full output frame, and analysis truth.
A newly saved artifact is subjected to the same final current and exact-result
validation. If that validation fails, only the exact newly created artifact is
deleted through `ArtifactService`, no save outcome is published, and the
independently valid recipe is retained.

Durable conversion of a transient dependency requires the source Study to come
from the same chart session and generation. Its saved artifact must match both
the active dataset and the exact source Study result.

Apply and Save are intentionally separate operations. A durable artifact that
completes before a late session callback is rejected remains durable and does
not resurrect stale chart state.

## Core and stale work

`ResearchStudyApplicationService` submits blocking work through `CoreRunner`,
reports bounded progress, and owns cooperative cancellation events. It accepts
immutable dataset and Study snapshots and never mutates `ChartSessionState`.
Chart-session generation tokens reject late results after dataset replacement,
dependency removal, or disposal. Resident movement during calculation does not
invalidate full result truth; acceptance projects that result onto the latest
resident slice.
Registered transient sources must also belong to the same session and current
generation and match the active MarketId, dataset fingerprint, complete dataset
timeline, and requested output before a dependent Study can be accepted.

Cancellation and persistence start are ordered by one atomic application-local
gate. Cancellation that wins before persistence delegates to Core and prevents
the write. Once persistence starts, cancellation returns `False`, does not
cancel Core, and allows Task 1016 to complete normally. Terminal bookkeeping is
cleared inline before any user result callback is forwarded to its external
dispatcher.

Task 1017 adds no GUI, style, pane creation, renderer payload, collection,
recipe execution, artifact update/recovery, Data Manager, Analysis, Backtest,
realtime, or compatibility behavior.
