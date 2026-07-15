# Task 1014: Canonical Financial Tool Specifications and Naming

## Purpose

Task 1014 restores the Old Leonardo financial-tool catalog as a small, immutable V2 authority. The package defines metadata and deterministic output naming only. It does not calculate tools, create GUI objects, persist data, or integrate with Core.

The implementation baseline is branch `main` at commit `ff6cb486cfdcf718197f90d39548ff0931ccb016` (`Task 1013: harden OHLCV validation performance`). The working tree was clean at the Task 1014 start gate.

## Canonical authority

`leonardo.financial_tools.specifications` is the canonical authority for the 26 accepted financial tools:

- 10 indicators;
- 7 oscillators;
- 9 constructs.

The four read-only catalogs are `INDICATOR_SPECS`, `OSCILLATOR_SPECS`, `CONSTRUCT_SPECS`, and `ALL_FINANCIAL_TOOL_SPECS`. They are the only public uppercase constants assigned by the specification module; supporting constants and mutable assembly dictionaries remain private. Their values are frozen, slotted models. Catalog insertion order is stable and follows the frozen Task 1014 inventory.

The exact canonical inventory is:

- Indicators: `sma`, `ema`, `tema`, `hma`, `kama`, `bb`, `hck`, `strategy`, `peaks_troughs`, `universal_trend_classifier`.
- Oscillators: `rsi`, `arsi`, `tdirsi`, `smi`, `mfi`, `obv`, `volume`.
- Constructs: `dynamic_binning`, `derivative`, `angle`, `braids`, `braid_instability`, `delta`, `trap_area`, `percent_span_angle`, `angle_momentum`.

The accepted lookup and naming aliases are:

- `utc` to `universal_trend_classifier`;
- `dynamic_binning_analysis` to `dynamic_binning`;
- `derivative_analysis` to `derivative`;
- `angle_analysis` to `angle`;
- `braid_state_analysis` to `braids`;
- `trap_area_analysis` to `trap_area`;
- `percent_angle`, `percent_angle_analysis`, and `percent_span_angle_analysis` to `percent_span_angle`.

Aliases never appear as catalog keys. The alias mapping is exposed as a read-only mapping proxy. `slope` is not an active key or alias.

`leonardo.financial_tools.naming` is the canonical authority for financial-tool keys, source tokens, and emitted output names. It preserves the accepted Old Leonardo naming behavior, including chained `__` source separators, parameterized names, construct source identity, the uppercase `A` in `trapA`, and the non-visual empty output of `dynamic_binning`.

## Public API

The package root exports the accepted models, catalogs, aliases, and functions:

- `get_financial_tool_spec` and `list_financial_tool_specs` provide read-only catalog access;
- `resolve_parameters` validates and resolves typed defaults without mutating caller data;
- `canonicalize_tool_key` applies the accepted aliases;
- `build_source_token` canonicalizes source identities;
- `resolve_output_names` resolves canonical output names;
- `resolve_output_signals` combines resolved names with output semantics;
- `validate_catalog` checks the fixed catalog structure.

Unknown tools raise `KeyError`. Invalid parameters, unsupported choices, and missing source bindings raise `ValueError`.

## Module responsibilities

- `models.py` defines the frozen, slotted domain specification models and local structural validation.
- `naming.py` owns canonical tool-key, source-token, and output-series naming.
- `specifications.py` owns the read-only catalogs, parameter resolution, output-signal semantics, and catalog validation.
- `__init__.py` exposes only the accepted Task 1014 public API.

Parameter resolution uses exact `int`, `bool`, and `str` types. Float parameters accept integers or floats except booleans and are normalized to `float`. Resolution fills canonical defaults, enforces ranges and choices, rejects unknown parameters, returns a read-only mapping, and does not mutate caller input.

## Preserved boundaries

This foundation has no dependency on Qt, Core, calculation implementations, persistence, Data Manager, Research, NumPy, or pandas. It does not expose the retired `ft_naming`, `ft_specs`, or manifest compatibility facades. It does not define OHLCV artifact or storage naming.

The catalog contains metadata required by later consumers, including input declarations, all 88 exact parameter descriptions from the frozen catalog, behavior, output semantics, style and edit capabilities, oscillator guides, and construct source-binding rules. Those consumers must use this authority rather than reconstructing financial-tool specifications or output names.

`volume` remains an oscillator specification only; Task 1014 does not create or alter a volume pane. Universal Trend Classifier retains its fixed output identities and per-signal semantics without implementing calculation or dependency resolution. Construct source identities describe data-series semantics, not positional row semantics.

## Old-code comparison

The implementation ports the accepted behavior from the permitted Old Leonardo specification and naming files. Donor classes named `ParamSpec` and `ToolSpec` are represented as `ParameterSpec` and `FinancialToolSpec`. Runtime callable resolver fields and donor dependencies were intentionally excluded. The active construct identities remain `dynamic_binning`, `derivative`, `angle`, `braids`, `braid_instability`, `delta`, `trap_area`, `percent_span_angle`, and `angle_momentum`; `slope` is not active.

## Validation

The required commands use `PYTHONPATH=$PWD/src;$PWD`, `PYTHONDONTWRITEBYTECODE=1`, and `QT_QPA_PLATFORM=offscreen`:

```text
python -m compileall -q src tests tools
python -m pytest -q tests/financial_tools_test
python -m pytest -q tests/core_test/test_architecture_reset.py
python -m pytest -q
git diff --check
git status --short --untracked-files=all
git diff --name-status
git diff --stat
```

The final Task 1014 PATCH 1 validation produced 60 passing focused tests, 2 passing architecture-reset tests, and 341 passing full-suite tests. The full suite retained 1,363 pre-existing Qt deprecation warnings. `git diff --check` passed. The final status contains only the eight authorized untracked Task 1014 files; no files were staged or committed.
