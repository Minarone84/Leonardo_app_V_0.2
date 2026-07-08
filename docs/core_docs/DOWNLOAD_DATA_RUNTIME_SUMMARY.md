# Download Data Runtime Summary

Status: retired historical reference.

This document records a removed Runtime Manager integration that previously
described a first-class `download_data_runtime` summary section. That section is
no longer active V2 behavior.

Runtime Manager now exposes generic runtime, provider, and suite inspection
sections only. Core inspection contracts do not carry first-class
`downloads_summary`, `download_execution_summary`, or
`download_data_runtime_summary` fields. A future Connection Suite Download
Manager may supply read-only status through generic suite or provider summary
boundaries when that work is explicitly scoped.

## Current Truth

- Old sandbox/fixture Download Data execution has been removed from active
  source.
- No active source executes downloads, calls Bybit, or writes Download Data
  storage.
- Connection Suite owns future Download Manager domain behavior.
- GUI surfaces remain shell/display/local-intent only.
- Runtime Manager remains read-only and generic.

## Historical Scope

The retired summary described compact counts for workflows, selections,
preflight recaps, progress recaps, completion recaps, output references, storage
targets, partial persistence records, warnings, errors, unavailable summaries,
and last activity.

Those shapes are historical references only. They are not current Runtime
Manager snapshot fields and must not be treated as a Core-owned Download
Manager contract.
