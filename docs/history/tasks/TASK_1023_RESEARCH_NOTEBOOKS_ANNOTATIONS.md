# Task 1023 Research Notebooks and Chart Annotations

Research Notebooks are durable, plain-text human research documents. The
Research Notebook service owns schema validation, canonical serialization,
content hashing, summaries, and exact-market annotation projection. The store
is the only notebook filesystem writer and uses atomic replacement.

Exactly one notebook editor may be active in a Research Suite. Runtime editor
generations, dirty state, pending operations, and task identities are not
persisted. Save, Discard, and Cancel protect dirty close and replacement.
Deleting the active dirty notebook uses the same decision before the editor is
fenced and deletion is submitted. A deferred delete proceeds only after a
successful Save and only while the originating manager and editor generations
remain current. Failed, cancelled, invalid, or unsubmitted saves clear their
pending transition; another notebook operation blocks new transitions until it
settles.

The editor exposes current validity independently from its last valid draft.
Every Save reparses and submits the exact current draft; invalid input blocks
manual and transition-driven saves without closing, replacing, or deleting.
While Save is pending, every notebook mutation control is fenced. Settlement
restores mutation controls, while Save and Save As follow current validity so a
failed Save cannot enable them from older cached state.

Pages are keyed by canonical `MarketId`. Notes remain editor-only. Potential
Trades and Points of Interest project through the dedicated annotation scene
onto every open attached or detached chart with the exact same market identity.
Annotations are not Studies or Artifacts and do not contribute to price
autoscale.

Row Go To uses the existing chart-session timestamp authority. It prefers the
active exact-market chart, then the lowest workspace position. It never opens a
chart or loads a dataset. Malformed timestamps remain editable and emit no Go
To request. Page removal uses raw table state so malformed cells on unaffected
pages are preserved. Duplicate Add Current Chart requests activate the existing
page; genuinely new pages are blocked while the editor contains invalid input.
Go To accepts zero and positive UTC millisecond timestamps and rejects negative
values.

Workspace Snapshots contain no notebook identity, content, or reference.
During snapshot restoration, annotation publication and notebook Go To are
deferred. The active notebook remains unchanged and is reprojected after the
restore settles.

Task 1023 adds no rich-text persistence, drawing tools, order execution,
position sizing, profit-and-loss calculation, Data Manager handoff, Analysis,
Backtest, or realtime behavior.
