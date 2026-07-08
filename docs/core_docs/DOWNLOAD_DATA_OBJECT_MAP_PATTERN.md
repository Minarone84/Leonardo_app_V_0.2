# Download Data Object Map Pattern

Status: retired historical reference.

This document records a removed read-only Object Map helper that summarized
Download Data boundary descriptors and read models. The helper is no longer
active V2 behavior.

Active Core Object Map infrastructure remains generic. Core must not own a
Connection Download Manager-specific Object Map pattern unless a future phase
explicitly introduces it through the appropriate Connection Suite boundary.

## Current Truth

- Old sandbox/fixture Download Data execution has been removed from active
  source.
- No active source executes downloads, calls Bybit, writes sandbox output, or
  writes production OHLCV storage.
- Connection Suite owns future Download Manager domain behavior.
- Provider/Connection owns provider capability and transport facts.
- Storage/Data owns future accepted persisted OHLCV truth.
- Runtime Manager remains read-only and generic.

## Historical Scope

The retired helper summarized Download Data boundary, workflow, selection,
preflight, progress, completion, storage target, output reference, and partial
persistence read models when supplied explicitly.

Those shapes are historical references only. They are not current Object Map
service behavior, and they do not imply an active Download Data execution,
storage, or provider implementation.
