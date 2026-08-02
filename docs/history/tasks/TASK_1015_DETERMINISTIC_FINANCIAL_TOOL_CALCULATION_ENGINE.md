# Task 1015: Deterministic Financial Tool Calculation Engine

## Purpose

Task 1015 adds deterministic, historical, full-frame calculation for the 26 financial tools defined by Task 1014. It does not add GUI integration, persistence, realtime execution, Core task submission, progress, cancellation, artifacts, or recipes.

## Canonical Authorities

`leonardo.financial_tools.specifications` remains the authority for canonical tool identity, kinds, inputs, parameter defaults and validation, output semantics, and the accepted 26-tool inventory. `leonardo.financial_tools.naming` remains the authority for aliases, source tokens, and output names.

`leonardo.financial_tools.calculation` owns the calculation boundary. It canonicalizes the requested tool, resolves Task 1014 parameters, validates the input frame and bindings, dispatches to one private calculator, verifies output identity and alignment, and constructs the result. Formula implementations remain private under `leonardo.financial_tools._calculation`.

## Public API

Task 1015 adds two package-root exports:

- `calculate_financial_tool` is the single calculation entry point.
- `FinancialToolCalculationResult` is the frozen, slotted owner-local result model.

The result exposes the canonical tool key and kind, immutable resolved parameters and bindings, exact output names, row and timestamp bounds, defensive analysis data, and a defensive frame copy from `to_frame()`. `FinancialToolCalculationResult` independently validates its canonical structural configuration against Task 1014, including parameters, bindings, runtime constraints, output names, exact frame columns, index identity, and timestamps. The calculation entry point and persisted-artifact consumers reuse this result-model authority.

The output frame preserves the input index and `ts_ms` exactly. Its columns are `ts_ms` followed by the Task 1014 output names. Numeric outputs are `float32`, Universal Trend Classifier boolean outputs are `bool`, and HCK color states remain `red`, `silver`, or `green`. Dynamic Binning has no plotted output columns and returns its in-memory result through `analysis`.

`FinancialToolCalculationResult` is the runtime output authority. It derives ordered runtime types from canonical Task 1014 signals and validates exact output dtypes and value domains: numeric outputs are `float32`, boolean outputs are non-null `bool`, and HCK and Strategy colors are non-null object strings limited to `red`, `silver`, and `green`. Braids preserves its Task 1014 categorical semantic classification while its accepted Task 1015 ambient-state runtime is numeric `float32`, limited to states 1 through 6 or NaN.

## Input and Binding Boundary

The calculation boundary requires a non-empty `pandas.DataFrame` with unique columns, a unique monotonically increasing index, and a non-null, integer-valued, strictly increasing `ts_ms` column. Required source columns use exact lowercase Task 1014 names and contain numeric values or nulls. Uppercase `Volume` is not accepted as an alias. The caller's frame is never sorted, reset, mutated, or persisted.

`derivative` and `angle` require exactly one `source` binding naming an existing numeric column. Other tools reject bindings. Construct source declarations such as `fast`, `mid`, `slow`, and `source_columns` remain canonical parameters.

## Formula Families

The private calculation package contains:

- indicators: SMA, EMA, TEMA, HMA, KAMA, Bollinger Bands, HCK, Strategy, and Peaks & Troughs;
- historical Universal Trend Classifier with private strict Peaks & Troughs dependencies;
- oscillators: RSI, ARSI, TDI RSI, SMI, MFI, OBV, and Volume;
- constructs: Derivative, Angle, Braids, Braid Instability, Delta, Trap Area, Percent Span Angle, and Angle Momentum;
- in-memory Dynamic Binning variation analysis, edge fitting, labeling, and JSON-safe analysis projection.

Strategy composes the same private formula owners used by standalone tools, including one shared SMA value helper. Universal Trend Classifier keeps custom trend dependencies isolated from internally generated range dependencies, including when their source names collide, and has no public realtime surface. Dynamic Binning uses the variation quantile method only for variation analysis; fitted bin edges preserve the donor's default NumPy quantile behavior.

## Preserved Boundaries

Calculation modules do not import Qt, GUI, Research, Core, OHLCV, storage, database libraries, retired financial-tool contracts, or donor compatibility facades. They do not discover plugins, register calculators publicly, write files, or expose private calculators.

The implementation intentionally does not recreate donor request/result contracts, public calculator registries, realtime state, time/timeframe passthrough columns, uppercase volume compatibility, permissive coercion, hidden donor parameters, filesystem persistence, or artifact identity.

## Characterization Authority

The 640-row Task 1015 input CSV and corrected PATCH 1 expected JSON characterize default behavior for all 26 tools. PATCH 1 fixture version 1.2 supersedes the original higher-precision expected values for Angle and SMI and is calculated from the frozen seven-decimal CSV. Numeric comparison uses `rtol=1e-6`, `atol=1e-6`, and equal-NaN semantics. Boolean and categorical values compare exactly. Dynamic Binning analysis compares recursively with floating tolerance only for numeric values.

## Validation

Validation uses repository-first imports, disabled bytecode generation, and offscreen Qt:

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

Task 1015 is nonvisual; manual visual validation is not required.
