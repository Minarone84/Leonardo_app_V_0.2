# Task 1016 Canonical Artifact and Recipe Foundation

## Authority

`leonardo.artifacts` is the canonical owner of persisted Financial Tool
recipes and calculated artifacts. `ArtifactService` is its only public write
owner. It consumes validated `FinancialToolCalculationResult` objects from
Task 1015 and Task 1014 specification, naming, parameter, and output-signal
authorities. Supplied results and persisted recipes are independently checked
through the Task 1015 result-model structural validator. Task 1016 does not
reproduce Financial Tool configuration rules, formulas, or dispatch.

Task 1016 owns versioned recipe and artifact metadata, deterministic identity,
canonical serialization, accepted OHLCV lineage capture, source-artifact
lineage validation, atomic create, read-only catalog summaries, load,
validation, and exact deletion.

## Persisted Schemas

The persisted schema version is `1.0` for:

- `OHLCVSourceFingerprintV1`;
- `ArtifactSourceRefV1`;
- `ArtifactRecipeV1`;
- `ArtifactMetadataV1`.

Persisted models are frozen and validate exact fields. Persisted mappings are
JSON-safe, finite, and read-only. Datetimes are timezone-aware, normalized to
UTC, and serialized with a `Z` suffix. Unsupported versions, noncanonical
market or tool identities, invalid hashes, and identity mismatches fail
explicitly. No migration or compatibility path is provided.

## Canonical Identity

Identity payloads use UTF-8 JSON with sorted keys, compact separators,
`ensure_ascii=False`, and `allow_nan=False`. No final newline participates in
identity hashing.

Recipe identity includes schema version, canonical `MarketId`, tool key, kind,
parameters, bindings, ordered output names, and ordered source-artifact
references. Display name, description, creation time, and storage path do not
affect identity.

Artifact identity includes schema version, recipe ID, accepted OHLCV
fingerprint, source-artifact references, full row/timestamp coverage, values
SHA-256, and optional analysis SHA-256.

The frozen golden identities are:

```text
recipe_id    67e1847a396e2ea878f408bcbb13925248d556c4ceac4c7e971ac266a91835f4
values_sha256 2a3d4a028860e79e7ac965834cde3522b25b9a858e2000d680b59869765f19d7
artifact_id  0de76f8222e23e4a67a8b72cbd262d3dd4899fd1fa26ea1b2c74b6a895b007ca
```

## Storage Layout

Artifacts and recipes are partitioned by canonical market identity:

```text
<historical_root>/<exchange>/<market_type>/<symbol>/<timeframe_segment>/
  artifacts/<kind>/<tool_key>/<artifact_id>/
    values.csv
    artifact.meta.json
    analysis.json
  recipes/<kind>/<tool_key>/<recipe_id>.json
```

`analysis.json` exists only for non-empty analysis. No user text participates
in paths. There is no global index and no filename compatibility inference.
Listing scans only canonical directories and reports malformed entries as
invalid typed summaries. Every artifact directory must contain exactly
`values.csv`, `artifact.meta.json`, and optional paired `analysis.json`; extra
files, directories, links, and junctions are rejected.

## Serialization

`values.csv` is UTF-8 with LF line endings. Its columns are `ts_ms` followed by
the recipe output names in exact order. Numeric outputs round-trip as
`float32`; NaN uses an empty field; booleans use lowercase `true` and `false`;
categorical strings remain exact. Loading restores Task 1014 output-signal
dtypes and a zero-based `RangeIndex` without mutating the calculation result.
Encoding and decoding consume the Task 1015 runtime-output authority, including
Braids' numeric ambient state. Loading re-encodes decoded values and requires
the original `values.csv` bytes to be exactly canonical.
Integer-valued Python and NumPy floating timestamps are accepted and serialized
as canonical decimal integers without a `.0` suffix; loaded timestamps are
`int64`.

Persisted JSON is UTF-8, key ordered, indented, and terminated by one LF.
Loading requires byte-for-byte canonical JSON encoding rather than accepting
semantically equivalent formatting.
Dynamic Binning analysis is recursively serialized when non-empty and its file
hash participates in artifact identity.

## Lifecycle And Atomicity

`save_recipe_from_result` creates or idempotently reuses one immutable recipe.
`save_calculation` requires exact full coverage of the current accepted OHLCV
dataset, creates or reuses its recipe, and creates one immutable artifact.
Duplicate artifact identity is rejected.

Values and analysis payloads are fully validated and canonically serialized
before a recipe is created or reused. Invalid persisted payload content leaves
both recipe and artifact catalogs unchanged.

An artifact is fully written in one unique sibling staging directory and
published with one native same-filesystem atomic no-replace directory rename.
An existing empty or complete destination is never replaced. A recipe is written to a
unique sibling temporary file and published by atomic create-if-absent hard
link. Concurrent identical bytes are reused; concurrent different bytes raise
an identity collision without replacement. Failures remove only the exact
temporary object and never expose a partial final object or replace existing
content.

Recipe display name, description, and timezone-aware creation timestamp are
normalized and validated before both initial publication and idempotent reuse.
Invalid reuse arguments do not alter existing recipe bytes.

Artifact deletion removes exactly one canonical artifact directory and does
not cascade. Recipe deletion removes exactly one canonical recipe file and is
refused while a valid artifact references that recipe. No wildcard, recursive
root, recovery, or regeneration operation exists.

The trusted historical root and every existing storage component are checked
for lexical and resolved confinement before read, write, list, publication, or
deletion. Symbolic links, broken links, and Windows junctions are rejected.

## Lineage

Artifact creation captures stable hashes and accepted status from the real
canonical OHLCV CSV and `OHLCVSidecarV1`. The source must be committed or
repaired, have validation status `ok`, match the requested canonical
`MarketId`, and remain unchanged throughout capture. The calculation result
must match every source timestamp and the complete row and timestamp range.
Persisted artifact metadata independently requires its row count and first and
last timestamps to equal its saved OHLCV fingerprint during construction and
load.

Current lineage validation uses one stable accepted fingerprint plus the
complete strictly increasing OHLCV timestamp sequence. Every current artifact
and recursively referenced source artifact must match that exact timeline.
The accepted source is recaptured after recursive validation before success is
returned.

Artifact creation recaptures and compares the accepted source immediately
before native publication and once again after publication. A detected
post-publication source change removes only the exact artifact created by that
operation and raises a lineage error; its independently valid recipe may
remain.

Source-artifact references must resolve within the same market, name a real
source output, and validate recursively against the same current OHLCV
fingerprint. Missing, stale, cross-market, and cyclic lineage is rejected.
Current validation never repairs, updates, or regenerates persisted data.

## Boundaries

Task 1016 does not write, repair, validate, reconstruct, or delete OHLCV. It
does not add collections, recipe execution, target-market rebinding, artifact
update or append, recovery, batch calculation, Analysis Databases, GUI,
Research Apply/Save, Data Manager, Core task submission, progress,
cancellation, realtime behavior, migration, legacy compatibility, or global
indexes. Those boundaries remain deferred beyond Task 1016.
