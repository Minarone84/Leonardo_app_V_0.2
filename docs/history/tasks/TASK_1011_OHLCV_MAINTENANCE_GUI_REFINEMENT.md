# Task 1011 — OHLCV Maintenance GUI Layout and Evidence Refinement

## Objective

Improve the existing OHLCV Maintenance presentation without changing validation,
repair, deletion, reconstruction, persistence, provider, or Research behavior.

## Accepted old-document behavior

The Old Leonardo Maintenance documentation and window established these useful
presentation requirements:

- open centered at roughly half of the usable screen width;
- use the full usable screen height while keeping the title bar inside the
  available desktop geometry;
- apply a local one-point font increase rather than a global application font
  change;
- keep dataset inspection and detailed reporting readable;
- keep the GUI presentation-only.

The old CoreBridge, GUI polling, direct service ownership, and source-correction
controls are not restored.

## Implemented

- screen-aware initial geometry and frame correction;
- local one-point font increase for the Maintenance window and its children;
- vertical workspace with:
  - dataset catalog beside selected-dataset evidence;
  - canonical validation findings beside the reviewed repair plan;
- compact dataset table that keeps source and issue detail in the evidence view;
- two-row action/progress layout suitable for the documented half-width window;
- richer read-only evidence reporting:
  - canonical paths and existence;
  - persistence, validation, source, and evidence state;
  - row count and first/last timestamps in milliseconds and UTC;
  - current CSV size and modification fingerprint;
  - sidecar SHA-256, schema, creation and update times;
  - canonical validator and error/warning counts;
  - sidecar warnings and discovery issues;
- splitter identities for runtime inspection and deterministic GUI tests.

## Explicit non-goals

- no source correction;
- no `modified` validation status;
- no batch validation;
- no Download Manager redesign;
- no provider, Store, sidecar schema, validator, repair, deletion, reconstruction,
  Research, or Core behavior changes;
- no color-theme redesign.

## Validation

- detailed summary regression test;
- presenter evidence regression test;
- static shell/geometry/font/boundary test;
- complete repository suite;
- temporary-data PySide6 visual smoke in the user environment.
