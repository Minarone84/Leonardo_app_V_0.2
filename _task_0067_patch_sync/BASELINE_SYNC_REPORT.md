# Task 0067 PATCH — Research baseline synchronization

## Purpose

Integrate the validated Research Tasks 0062–0067 changes onto the newer user baseline containing merged Tasks 1001 and 1002.

## Baselines

- User baseline HEAD: `f15ddded6022be13679e2a120447bef5616b7dd6`
- User branch: `light-v2-reset`
- Research source baseline: Task 0067 POST package, originally based on `4d34a15a5323099965daf96bd4fbe4eebe01cb69`

## Merge policy

- Preserve all Task 1001 and Task 1002 Download Data changes byte-for-byte.
- Apply only the Research 0062–0067 file set and the Research composition-root additions in `src/leonardo/core/app.py`.
- Do not replace the repository wholesale with the older Task 0067 package.
- Exclude runtime/generated content: `.pytest_cache/`, `historical_data/`, `__pycache__/`, and bytecode.
- No Git write commands were executed.

## Result

The two workstreams are non-conflicting. Combined tests pass and Governance 2.3 remains byte-identical to the authoritative copies.
