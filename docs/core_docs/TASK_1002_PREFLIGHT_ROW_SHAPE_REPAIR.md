# Task 1002: Preflight Table Row Shape Repair

Task 1002 repairs the Historical Download preflight crash caused by tuple presentation
rows being forwarded to the mapping-based shared table renderer.

The preflight shell now owns the conversion of GUI-local positional rows into the table's
column-keyed mapping shape. This preserves the GUI-shell boundary and avoids moving table
layout knowledge into provider, OHLCV, or persistence services.

The affected surfaces are:

- Request Summary
- Validation Checklist
- Workload Estimate

No workflow behavior, provider knowledge, persistence policy, or Research Suite code was
changed.
