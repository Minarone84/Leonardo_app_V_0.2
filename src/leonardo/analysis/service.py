"""Read saved database snapshots and delegate statistical truth to Financial Tools."""
from __future__ import annotations

import csv
from hashlib import sha256
from io import StringIO
import json
from time import time_ns
from uuid import uuid4

import numpy as np
import pandas as pd

from leonardo.data_manager.creation_models import DataManagerCreationError
from leonardo.data_manager.creation_store import DataManagerCreationStore
from leonardo.financial_tools import (
    VariationContext, fit_directional_binning, classify_directional_binning,
    fit_dynamic_binning, classify_dynamic_binning, get_financial_tool_spec,
    resolve_output_signals,
)
from .models import (
    AnalysisColumn, AnalysisRequest, AnalysisResult, BinDisplay, ColumnAnalysis,
    DatabaseCatalog, DatabaseColumns, DatabaseEntry, DatabaseReference, DistributionDisplay,
)

AVAILABILITY = "snapshot_read_time_retrospective_only"
_RESERVED = {"ts_ms", "available_at_ms"}


def _checkpoint():
    pass


def _progress(_message, _current=None, _total=None):
    pass


class AnalysisService:
    def inspect_combination(self, frozen, discovery, current, parent, pattern_id, options,
                            *, checkpoint=_checkpoint, progress=_progress, memory_limit_bytes=134217728):
        from .combination_explanations import inspect_combination
        return inspect_combination(frozen, discovery, current, parent, pattern_id, options,
            checkpoint=checkpoint, progress=progress, memory_limit_bytes=memory_limit_bytes)

    def refinement_sensitivity(self, frozen, current, omissions,
                               *, checkpoint=_checkpoint, progress=_progress, memory_limit_bytes=134217728):
        from .combination_explanations import refinement_sensitivity
        return refinement_sensitivity(frozen, current, omissions,
            checkpoint=checkpoint, progress=progress, memory_limit_bytes=memory_limit_bytes)

    def pin_pattern_set(self, binning_result, catalogue, discovery, pattern_ids,
                        *, checkpoint=_checkpoint, progress=_progress):
        from .pattern_refinement import pin_patterns
        return pin_patterns(binning_result, catalogue, discovery, pattern_ids,
                            checkpoint=checkpoint, progress=progress)

    def evaluate_pattern_set(self, frozen, refinement, *, parent=None,
                             checkpoint=_checkpoint, progress=_progress,
                             memory_limit_bytes=128 * 1024 * 1024):
        from .refinement_models import GranularRefinement
        if type(refinement) is GranularRefinement:
            from .pattern_refinement import evaluate_granular_patterns
            return evaluate_granular_patterns(frozen, refinement, parent=parent, checkpoint=checkpoint,
                progress=progress, memory_limit_bytes=memory_limit_bytes)
        from .pattern_refinement import evaluate_patterns
        return evaluate_patterns(frozen, refinement, parent=parent, checkpoint=checkpoint,
                                 progress=progress, memory_limit_bytes=memory_limit_bytes)

    def compare_pattern_evaluation(self, frozen, evaluation, *, parent=None):
        from .refinement_models import FrozenPatternSet, PatternEvaluation
        if not isinstance(frozen, FrozenPatternSet) or not isinstance(evaluation, PatternEvaluation):
            raise TypeError("comparison requires a frozen set and evaluation")
        if (evaluation.root_id != frozen.root_id or evaluation.set_id != frozen.set_id
                or (parent is not None and (not isinstance(parent, PatternEvaluation)
                    or parent.root_id != frozen.root_id or parent.set_id != frozen.set_id))):
            raise ValueError("comparison must use the same frozen root and set")
        parent_id = frozen.source_discovery_id if parent is None else parent.evaluation_id
        if evaluation.parent_id != parent_id:
            raise ValueError("comparison requires the actual retained parent")
        before = frozen.original_patterns() if parent is None else parent.frame("patterns")
        after = evaluation.frame("patterns")
        before, after = before.set_index("pattern_id"), after.set_index("pattern_id")
        rows = []
        for pattern in frozen.patterns:
            old, new = before.loc[pattern.pattern_id], after.loc[pattern.pattern_id]
            row = dict(pattern_id=pattern.pattern_id, condition=new["condition"],
                       parent_id=parent_id, evaluation_id=evaluation.evaluation_id)
            for key in ("matched", "assessable", "comparison_matched", "comparison_assessable", "difference_pp"):
                a, b = old[key], new[key]
                a = None if pd.isna(a) else a
                b = None if pd.isna(b) else b
                row.update({"parent_"+key: a, "current_"+key: b,
                            "delta_"+key: None if a is None or b is None else b-a})
            row["parent_support"] = (f"Source original rank_eligible: {old['rank_eligible']}" if parent is None
                                     else f"Current support_eligible: {old['support_eligible']}")
            row["current_support"] = f"Current support_eligible: {new['support_eligible']}"
            rows.append(row)
        return pd.DataFrame(rows, dtype=object)

    def search_family_patterns(self, frozen, binning_result, catalogue, refinement, *, parent_id,
                               checkpoint=_checkpoint, progress=_progress):
        from .pattern_refinement import _gr05_search_family_patterns
        return _gr05_search_family_patterns(frozen, binning_result, catalogue, refinement,
            parent_id=parent_id, checkpoint=checkpoint, progress=progress)

    def search_granular_patterns(self, frozen, binning_result, catalogue, definition, *, parent_id,
                                checkpoint=_checkpoint, progress=_progress, population_limit_bytes=134217728):
        from .pattern_refinement import search_granular_patterns
        return search_granular_patterns(frozen, binning_result, catalogue, definition, parent_id=parent_id,
            checkpoint=checkpoint, progress=progress, population_limit_bytes=population_limit_bytes)

    def __init__(self, store: DataManagerCreationStore, *, clock_ms=None, profile_id_factory=None,
                 classification_chunk_size: int = 10000):
        if not isinstance(store, DataManagerCreationStore):
            raise TypeError("Analysis requires the owned Data Manager creation store")
        if type(classification_chunk_size) is not int or classification_chunk_size < 1:
            raise ValueError("classification chunk size must be positive")
        self._store = store
        self._clock_ms = clock_ms or (lambda: time_ns() // 1_000_000)
        self._profile_id = profile_id_factory or (lambda: "das_" + uuid4().hex)
        self._chunk_size = classification_chunk_size

    def catalog(self, *, checkpoint=_checkpoint, progress=_progress):
        checkpoint()
        identities = self._store.list_database_ids()
        entries, issues = [], []
        for position, identity in enumerate(identities):
            checkpoint()
            progress("Reading database catalogue", position, len(identities))
            try:
                definition = self._store.load_database_definition(identity)
                head = self._store.load_database_head(identity)
                manifest = self._store.load_database_manifest(identity, head.revision_id)
                if definition.market_id != manifest.market_id or head.database_id != identity:
                    raise ValueError("database definition and revision identity disagree")
                entries.append(_entry(manifest, name=definition.display_name))
            except (DataManagerCreationError, OSError, ValueError) as exc:
                issues.append(f"{identity}: {exc}")
        checkpoint()
        return DatabaseCatalog(tuple(entries), tuple(issues))

    def load_columns(self, reference: DatabaseReference, *, checkpoint=_checkpoint, progress=_progress):
        entry, _frame, columns, _as_of = self._load(reference, checkpoint, progress)
        return DatabaseColumns(entry, columns)

    def load_utc_classification(self, reference: DatabaseReference, *,
                                checkpoint=_checkpoint, progress=_progress):
        from .models import DatabaseUtcClassification
        if not isinstance(reference, DatabaseReference):
            raise TypeError("select a pinned database reference")
        checkpoint()
        progress("Reading UTC classification")
        loaded = self._store.load_database_revision(reference.database_id, reference.revision_id)
        if (_entry(loaded.manifest).reference != reference
                or sha256(loaded.values_csv).hexdigest() != reference.values_sha256):
            raise ValueError("loaded database revision differs from the selected reference")
        checkpoint()
        return DatabaseUtcClassification(reference, loaded.utc_classification)

    def load_pattern_catalogue(self, result, *, checkpoint=_checkpoint, progress=_progress):
        catalogue, _prices = self._pattern_inputs(result, checkpoint=checkpoint, progress=progress)
        return catalogue

    def _pattern_inputs(self, result, *, capture_prices=False, checkpoint, progress):
        from .models import DatabaseUtcClassification
        from .trend_start_patterns import analysis_key, build_catalogue
        analysis_key(result)
        _entry_value, frame, _columns, as_of, loaded, rows = self._load_snapshot(result.entry.reference, checkpoint, progress)
        timestamps = tuple(int(t) for t in frame.ts_ms)
        for column in result.columns:
            checkpoint()
            if column.to_frame().ts_ms.tolist() != list(timestamps):
                raise ValueError("binning and database timestamp axes disagree")
        bundle = DatabaseUtcClassification(result.entry.reference, loaded.utc_classification)
        catalogue = build_catalogue(result, bundle, timestamps, checkpoint=checkpoint, progress=progress)
        prices = None
        if capture_prices:
            from .pattern_refinement import _gr04_capture_price_snapshot
            prices = _gr04_capture_price_snapshot(loaded, rows, as_of, checkpoint=checkpoint)
        return catalogue, prices

    def run_patterns(self, result, request, *, checkpoint=_checkpoint, progress=_progress):
        from .pattern_models import PatternRequest
        from .trend_start_patterns import run_study
        if not isinstance(request, PatternRequest) or result.entry.reference != request.reference:
            raise ValueError("pattern study must use the completed binning database revision")
        catalogue, prices = self._pattern_inputs(result, capture_prices=request.pre_event is not None,
                                                 checkpoint=checkpoint, progress=progress)
        timestamps = tuple(int(t) for t in result.columns[0].to_frame().ts_ms)
        study = run_study(result, catalogue, request, timestamps, checkpoint=checkpoint, progress=progress)
        checkpoint()
        if prices is not None:
            from .pattern_refinement import _gr04_attach_prices, _gr04_market
            _gr04_attach_prices(study, prices, _gr04_market(result.entry.market_id), checkpoint=checkpoint)
        return study

    def pattern_matches(self, study, pattern_id, cohort, *, checkpoint=_checkpoint, progress=_progress):
        checkpoint()
        progress("Locating exact pattern occurrences")
        return study.pattern_matches(pattern_id, cohort, checkpoint=checkpoint)

    def _load(self, reference, checkpoint, progress):
        return self._load_snapshot(reference, checkpoint, progress)[:4]

    def _load_snapshot(self, reference, checkpoint, progress):
        if not isinstance(reference, DatabaseReference):
            raise TypeError("select a pinned database reference")
        checkpoint()
        progress("Validating database revision")
        loaded = self._store.load_database_revision(reference.database_id, reference.revision_id)
        as_of = self._clock_ms()
        if type(as_of) is not int or not 0 <= as_of <= np.iinfo(np.int64).max:
            raise ValueError("snapshot read time must be a nonnegative int64 UTC timestamp")
        checkpoint()
        manifest = loaded.manifest
        entry = _entry(manifest)
        if entry.reference != reference or sha256(loaded.values_csv).hexdigest() != reference.values_sha256:
            raise ValueError("loaded database revision differs from the selected reference")
        progress("Preparing column metadata")
        rows = list(csv.reader(StringIO(loaded.values_csv.decode("utf-8"), newline=""), strict=True))
        header, records = rows[0], rows[1:]
        if (len(records) != manifest.row_count or len(header) != manifest.column_count
                or len(set(header)) != len(header) or set(header) != set(manifest.column_mapping.values())
                or not header or header[0] != "ts_ms" or any(len(row) != len(header) for row in records)):
            raise ValueError("parsed database shape or columns disagree with manifest")
        timestamps = np.asarray([int(row[0]) for row in records], dtype="int64")
        if (not len(timestamps) or timestamps[0] < 0 or np.any(timestamps[1:] <= timestamps[:-1])
                or int(timestamps[0]) != manifest.first_timestamp_ms
                or int(timestamps[-1]) != manifest.last_timestamp_ms):
            raise ValueError("parsed timestamps disagree with database revision")
        if int(timestamps[-1]) > as_of:
            raise ValueError("database contains future timestamps after snapshot read time")
        frame = pd.DataFrame({"ts_ms": timestamps})
        columns = []
        for index, name in enumerate(header):
            checkpoint()
            descriptor, value_type = _column_identity(manifest, name)
            definition = json.dumps(descriptor, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            version = sha256(definition.encode("utf-8")).hexdigest()
            reason = ""
            if name in _RESERVED:
                reason = "Timestamp or availability metadata"
            elif value_type in ("categorical", "boolean"):
                reason = f"Saved output is {value_type}"
            else:
                try:
                    values = np.asarray([np.nan if row[index] == "" else float(row[index]) for row in records], dtype="float64")
                except (ValueError, OverflowError):
                    reason = "Contains nonnumeric values"
                else:
                    if any(not np.isfinite(value) and row[index] != "" for value, row in zip(values, records, strict=True)):
                        reason = "Contains nonfinite numeric tokens"
                    else:
                        frame[name] = values
            columns.append(AnalysisColumn(name, not reason, reason, definition, version,
                                          type_known=value_type is not None))
        checkpoint()
        return entry, frame, tuple(columns), as_of, loaded, rows

    def run(self, request: AnalysisRequest, *, checkpoint=_checkpoint, progress=_progress):
        if not isinstance(request, AnalysisRequest):
            raise TypeError("analysis requires a validated request")
        entry, data, columns, as_of = self._load(request.reference, checkpoint, progress)
        metadata = {column.name: column for column in columns}
        for selected in request.columns:
            if selected.source not in metadata or not metadata[selected.source].eligible:
                raise ValueError(f"Column {selected.source!r} is unavailable or ineligible in this database revision")
        outcomes = []
        for position, selected in enumerate(request.columns):
            checkpoint()
            progress(f"Fitting {selected.source} ({position + 1}/{len(request.columns)})")
            column = metadata[selected.source]
            frame = data.loc[:, ["ts_ms", selected.source]].copy()
            frame.insert(1, "available_at_ms", as_of)
            raw = frame[selected.source].to_numpy(dtype="float64")
            finite = raw[np.isfinite(raw)]
            diagnostics = _base_diagnostics(entry, selected, column, as_of, raw)
            if not finite.size:
                observations = frame.rename(columns={selected.source: "raw_value"})
                observations["source"] = selected.source
                observations["measurement"] = selected.measurement
                observations["mode"] = "retrospective"
                observations["status"] = "missing_value"
                observations["support_status"] = "insufficient_reference"
                outcomes.append(ColumnAnalysis(selected, column, None, "insufficient_reference",
                    DistributionDisplay((), 0, 0), (), diagnostics + (("Outcome", "No finite observations; no profile fitted"),), observations))
                continue
            context = VariationContext(selected.source, entry.market_id, column.definition, column.parameter_version, column.unit)
            provenance = (f"database:{entry.reference.database_id}", f"revision:{entry.reference.revision_id}",
                          f"values_sha256:{entry.reference.values_sha256}", f"column:{selected.source}", f"availability:{AVAILABILITY}")
            arguments = dict(profile_id=self._profile_id(), calibration_as_of_ms=as_of, provenance=provenance, policy=selected.policy)
            if selected.measurement == "directional_intensity":
                profile = fit_directional_binning(frame, context, **arguments)
                classify = classify_directional_binning
            else:
                profile = fit_dynamic_binning(frame, context, measurement=selected.measurement, **arguments)
                classify = classify_dynamic_binning
            checkpoint()
            progress(f"Classifying {selected.source}", position, len(request.columns))
            chunks = []
            for start in range(0, len(frame), self._chunk_size):
                checkpoint()
                chunks.append(classify(frame.iloc[start:start + self._chunk_size], profile, context=context, mode="retrospective").to_frame())
                checkpoint()
            observations = pd.concat(chunks)
            bins, extra = _profile_display(profile, observations, selected.measurement)
            diagnostics += (("Profile ID", profile.profile_id), *extra)
            outcomes.append(ColumnAnalysis(selected, column, profile, "completed", _distribution(finite), bins, diagnostics, observations))
            checkpoint()
            progress(f"Completed {selected.source}", position + 1, len(request.columns))
        checkpoint()
        return AnalysisResult(entry, as_of, tuple(outcomes))


def _entry(manifest, *, name=None):
    return DatabaseEntry(DatabaseReference(manifest.database_id, manifest.revision_id, manifest.values_sha256),
                         name or manifest.display_name, manifest.market_id, manifest.row_count, manifest.column_count,
                         manifest.first_timestamp_ms, manifest.last_timestamp_ms)


def _column_identity(manifest, name):
    descriptor = {"kind": "stored_database_column", "database_id": manifest.database_id,
                  "revision_id": manifest.revision_id, "values_sha256": manifest.values_sha256,
                  "column": name, "formula": "not_recorded", "unit": "not_recorded"}
    if name in ("open", "high", "low", "close", "volume"):
        descriptor["output_name"] = name
        return descriptor, "numeric"
    output = next((o for o in getattr(manifest, "selected_outputs", ()) if o.column_name == name), None)
    member = next((m for m in getattr(manifest, "members", ())
                   if output is not None and m.version_key.logical_artifact_id == output.logical_artifact_id), None)
    if output is not None:
        descriptor["saved_output"] = output.to_dict()
    if member is None:
        return descriptor, None
    descriptor["saved_member"] = member.to_dict()
    try:
        spec = get_financial_tool_spec(member.tool_key)
    except KeyError:
        return descriptor, None
    # Saved outputs retain their provider's declared order. Bind type metadata,
    # not default formula settings, to that order when the cardinality agrees.
    signals = spec.output.signals
    if not signals and spec.key == "braids":
        # Resolve through the public authority with neutral names; types/order
        # do not depend on the unavailable saved formula parameters.
        signals = resolve_output_signals(spec.key, {"fast": "f", "mid": "m", "slow": "s"})
    if len(signals) == len(member.output_names) and output.output_name in member.output_names:
        return descriptor, signals[member.output_names.index(output.output_name)].value_type
    return descriptor, None


def _distribution(finite):
    values, counts = np.unique(finite, return_counts=True)
    probabilities = np.cumsum(counts) / len(finite)
    indices = np.unique(np.linspace(0, len(values) - 1, min(2000, len(values)), dtype=int))
    return DistributionDisplay(tuple((float(values[i]), float(probabilities[i])) for i in indices), len(values), len(finite))


def _base_diagnostics(entry, selected, column, as_of, raw):
    return (("Database", entry.name), ("Database ID", entry.reference.database_id),
            ("Revision", entry.reference.revision_id), ("Values SHA-256", entry.reference.values_sha256),
            ("Column", selected.source), ("Measurement", selected.measurement),
            ("Mode", "retrospective"), ("Snapshot read timestamp", as_of),
            ("Reference first timestamp", entry.first_timestamp_ms), ("Reference last timestamp", entry.last_timestamp_ms),
            ("Availability", "Snapshot read time; original historical availability is not asserted"),
            ("Formula / unit", "Not recorded; stored column values used without conversion"),
            ("Numeric type", "Known output type" if column.type_known else "Untyped numeric column"),
            ("Parameter definition", column.definition), ("Parameter version", column.parameter_version),
            ("Settings", json.dumps(selected.policy.to_dict(), sort_keys=True)),
            ("Override shared defaults", selected.override), ("Rows", len(raw)),
            ("Finite", int(np.isfinite(raw).sum())), ("Missing", int(np.isnan(raw).sum())),
            ("Zero", int((raw == 0).sum())), ("Positive", int((raw > 0).sum())), ("Negative", int((raw < 0).sum())))


def _profile_display(profile, frame, measurement):
    analysis = profile.analysis.to_dict()
    bins, extra = [], []
    if measurement == "directional_intensity":
        extra.append(("Reference kind", analysis["reference_kind"]))
        for direction in ("positive", "negative"):
            side = analysis[direction]
            title = direction.title()
            extra.extend(((f"{title} support", side["status"]), (f"{title} requested bins", side["bin_count"]),
                          (f"{title} occupied bins", side["occupied_bins"]), (f"{title} empty bins", side["empty_bins"])))
            extra.extend((f"{title} magnitude {key}", value) for key, value in side["magnitude_statistics"].items())
            for b in side["bins"]:
                bins.append(BinDisplay(title, b["label"], b["percentile_start"], b["percentile_end"], b["count"],
                                       b["observed_signed_minimum"], b["observed_signed_maximum"], side["status"]))
    else:
        extra.append(("Reference support", analysis["status"]))
        extra.extend((f"Measured {key}", analysis[key]) for key in ("minimum", "maximum", "mean", "std", "q1", "median", "q3"))
        bounds = (0.0, *profile.policy.cutoffs, 100.0)
        # Display the existing version-1 band vocabulary, including empty bands.
        # Counts and membership are supplied by the backend, never recomputed here.
        labels = ("very_low", "low", "below_typical", "typical", "above_typical", "high", "very_high")
        for index, count in enumerate(analysis["band_counts"]):
            observed = frame.loc[frame["bin_index"] == index, "raw_value"].dropna()
            bins.append(BinDisplay("Full reference", labels[index], bounds[index], bounds[index + 1], count,
                                   float(observed.min()) if len(observed) else None,
                                   float(observed.max()) if len(observed) else None, analysis["status"]))
    return tuple(bins), tuple(extra)
