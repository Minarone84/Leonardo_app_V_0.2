"""Bounded, retrospective conjunction mining over independent stored labels."""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from itertools import combinations, product
import json

import pandas as pd

from .pattern_models import PatternStudy
from .pre_event_cohorts import build_cohorts, overlap_groups


@dataclass(frozen=True, slots=True)
class Term:
    column: str
    offset: int
    profile_id: str | None
    centers: tuple[str, ...]
    allowed: tuple[str, ...]
    metadata: str

    def __post_init__(self):
        if type(self.offset) is not int or self.offset >= 0:
            raise ValueError("pre-event conditions require strictly negative offsets")
        if not self.centers or not self.allowed or any(c not in self.allowed for c in self.centers):
            raise ValueError("condition centers must belong to their allowed set")

    @property
    def center(self):
        return self.centers[0]

    def to_dict(self):
        return {"column": self.column, "offset": self.offset, "profile_id": self.profile_id,
                "center": self.center, "center_aliases": self.centers, "allowed": self.allowed,
                "bins": json.loads(self.metadata)}


def terms_for_column(column, name, offsets, radius):
    """The profile, never observed occupancy or lexicographic order, owns neighbors."""
    profile = column.profile
    if column.request.measurement != "directional_intensity":
        if radius:
            raise ValueError(f"{name}: neighboring tolerance requires directional-bin metadata; choose exact matching")
        from leonardo.financial_tools.variation_models import _BANDS
        categories = [(label, (label,), ()) for label in _BANDS] if profile is not None else []
    else:
        if profile is None:
            if radius:
                raise ValueError(f"{name}: no fitted directional profile; choose exact matching")
            return ()
        categories = []
        for side in (profile.analysis.negative, profile.analysis.positive):
            payload = side.to_dict()
            if payload["status"] in ("absent_reference", "degenerate_reference"):
                continue
            bins = payload["bins"]
            for index, entry in enumerate(bins):
                neighbors = bins[max(0, index-radius):min(len(bins), index+radius+1)]
                metadata = tuple({k: b[k] for k in ("label", "bin_index", "percentile_start", "percentile_end",
                    "observed_signed_minimum", "observed_signed_maximum", "count")} for b in neighbors)
                categories.append((entry["label"], tuple(b["label"] for b in neighbors), metadata))
        if profile.analysis.zero_count:
            categories.append(("Zero", ("Zero",), ({"label": "Zero", "description": "exact zero"},)))
    grouped = {}
    for center, allowed, metadata in categories:
        if allowed not in grouped:
            grouped[allowed] = ([], json.dumps(metadata, sort_keys=True))
        grouped[allowed][0].append(center)
    return tuple(Term(name, offset, profile.profile_id if profile else None, tuple(centers), allowed, metadata)
                 for offset in offsets for allowed, (centers, metadata) in grouped.items())


def observe(data, sample, terms):
    """The sole cell-availability and label-match predicate used by search and inspection."""
    from .trend_start_patterns import _condition
    actual, ready = _condition(data, sample["anchor"], tuple((t.column, t.offset) for t in terms),
                               ordinary=sample["ordinary"])
    if actual is None:
        return None, False, False, False
    matched = all(value in term.allowed for term, value in zip(terms, actual, strict=True))
    exact = all(value == term.center for term, value in zip(terms, actual, strict=True))
    return actual, ready, matched, exact


def _mask(samples, cohort, partition):
    return sum(1 << i for i, s in enumerate(samples) if s["cohort"] == cohort and s["partition"] == partition)


def _stats(valid, ready, matched, exact, population, timing):
    assessable = (valid & population).bit_count()
    count = (matched & population).bit_count()
    return {"total": population.bit_count(), "assessable": assessable,
            "excluded": population.bit_count()-assessable, "matched": count,
            "frequency": count/assessable if assessable else None,
            "exact_matched": (exact & population).bit_count(), "added_by_tolerance": ((matched & ~exact) & population).bit_count(),
            "exact_frequency": (exact & population).bit_count()/assessable if assessable else None,
            "exact_ready_matched": (exact & ready & timing & population).bit_count(),
            "ready_assessable": (ready & timing & population).bit_count(),
            "ready_matched": (matched & ready & timing & population).bit_count(),
            "timing_withheld": (valid & ~timing & population).bit_count()}


def _counts_for_masks(masks, populations, timing):
    valid, ready, matched, exact = masks
    out = {}
    for prefix, population in populations.items():
        out.update({prefix+k: v for k, v in _stats(valid, ready, matched, exact, population, timing).items()})
    for prefix in ("", "later_"):
        frequency, baseline = out[prefix+"frequency"], out[prefix+"comparison_frequency"]
        out[prefix+"difference_pp"] = 100*(frequency-baseline) if frequency is not None and baseline is not None else None
        out[prefix+"frequency_ratio"] = frequency/baseline if frequency is not None and baseline else None
    return out


def _merge_masks(items):
    masks = list(items[0])
    for other in items[1:]:
        masks = [a & b for a, b in zip(masks, other, strict=True)]
    return tuple(masks)


def mine(data, parent, request, checkpoint, progress):
    from .trend_start_patterns import _hash, _json
    spec = request.pre_event
    samples = data["samples"]
    populations = {prefix: _mask(samples, cohort, partition) for prefix, cohort, partition in
        (("", "target", "discovery"), ("comparison_", "comparison", "discovery"),
         ("later_", "target", "later"), ("later_comparison_", "comparison", "later"))}
    timing = sum(1 << i for i, s in enumerate(samples) if s["timing"])
    data.update(populations=populations, timing_mask=timing)
    stats = {"complete": True, "reason": "", "examined": 0, "estimated_match_bytes": 0, "stage": "atoms"}
    atoms, masks, rows, level = [], [], [], []
    if (request.family is None and data.get("_gr05_scope") is None) or not populations[""]:
        stats["reason"] = "Choose an exact family" if request.family is None and data.get("_gr05_scope") is None else "No discovery target observations"
        return rows, stats
    def budget(extra=0):
        if stats["examined"] >= spec.candidate_limit:
            stats.update(complete=False, reason="candidate_limit")
            return False
        if stats["estimated_match_bytes"]+extra > spec.memory_limit_bytes:
            stats.update(complete=False, reason="match_state_memory_limit")
            return False
        return True
    def record(indices, combined):
        terms = tuple(atoms[i] for i in indices)
        primary = len({t.column for t in terms}) >= 2 and len({t.offset for t in terms}) >= 2
        if len(terms) > 1 and not primary:
            return
        counts = _counts_for_masks(combined, populations, timing)
        if not counts["matched"]:
            return
        identity = _hash(tuple((t.column, t.offset, t.profile_id, t.allowed) for t in terms))
        definition = _json([t.to_dict() for t in terms])
        # Retained result state is included in the conservative memory estimate.
        # Fixed-size estimates cannot let later-period bit contents affect discovery limits.
        cost = 2048 + len(definition.encode()) + 4 * (32 + (len(samples)+7)//8)
        if stats["estimated_match_bytes"]+cost > spec.memory_limit_bytes:
            stats.update(complete=False, reason="match_state_memory_limit")
            return
        stats["estimated_match_bytes"] += cost
        rank = (primary and counts["ready_assessable"] >= request.min_target
                and counts["comparison_ready_assessable"] >= request.min_comparison
                and counts["ready_matched"] >= request.min_matches and counts["difference_pp"] is not None)
        row = {"pattern_id": identity, "kind": "combination" if primary else "single baseline",
            "condition": " AND ".join(f"{t.column}[{t.offset:+d}] in {{{', '.join(t.allowed)}}}" for t in terms),
            **counts, "term_count": len(terms), "additional_allowed_bins": sum(len(t.allowed)-1 for t in terms),
            "rank_eligible": rank, "rank_reason": "supported historical contrast" if rank else
                "single baseline" if not primary else "below_support_or_unavailable_comparison",
            "conditions": definition, "interpretation": "retrospective_full_history", "empirical_group": ""}
        data["patterns"][identity] = {"terms": terms, "masks": combined, "indices": indices}
        rows.append(row)
    selected = {c.request.source: c for c in parent.columns}
    for name in sorted(request.columns):
        checkpoint()
        terms = terms_for_column(selected[name], name, spec.offsets, spec.radius(name))
        for term in terms:
            checkpoint()
            estimate = 1024 + 4 * (32 + (len(samples)+7)//8) + len(term.metadata.encode())
            if not budget(estimate):
                break
            stats["examined"] += 1
            valid = ready = matched = exact = 0
            for i, sample in enumerate(samples):
                if i % 128 == 0:
                    checkpoint()
                actual, supported, hit, center = observe(data, sample, (term,))
                bit = 1 << i
                if actual is not None:
                    valid |= bit
                if supported:
                    ready |= bit
                if hit:
                    matched |= bit
                if center:
                    exact |= bit
            if not (matched & populations[""]):
                continue
            index = len(atoms)
            atoms.append(term); masks.append((valid, ready, matched, exact))
            stats["estimated_match_bytes"] += estimate
            record((index,), masks[-1])
            if (matched & populations[""]).bit_count() >= request.min_matches:
                level.append((index,))
            if not stats["complete"]:
                break
        if not stats["complete"]:
            break
    primary_enabled = len(request.columns) >= 2 and spec.history >= 2
    for length in range(2, spec.max_terms+1):
        if not stats["complete"] or not primary_enabled or not level:
            break
        stats["stage"] = f"{length} conditions"
        next_level, previous = [], set(level)
        buckets = defaultdict(list)
        for candidate in level:
            buckets[candidate[:-1]].append(candidate)
        for prefix in sorted(buckets):
            for left, right in combinations(sorted(buckets[prefix]), 2):
                checkpoint()
                indices = left+(right[-1],)
                cells = [(atoms[i].column, atoms[i].offset) for i in indices]
                if len(set(cells)) != len(cells) or any(tuple(part) not in previous for part in combinations(indices, length-1)):
                    continue
                if not budget(256):
                    break
                stats["examined"] += 1
                combined = _merge_masks([masks[i] for i in indices])
                if (combined[2] & populations[""]).bit_count() >= request.min_matches:
                    next_level.append(indices)
                    stats["estimated_match_bytes"] += 256
                    record(indices, combined)
                if stats["examined"] % 128 == 0:
                    progress("Searching pre-event label combinations", stats["examined"], spec.candidate_limit)
                if not stats["complete"]:
                    break
            if not stats["complete"]:
                break
        level = next_level
    if not stats["complete"]:
        for row in rows:
            row.update(rank_eligible=False, rank_reason="incomplete_search")
    rows.sort(key=lambda r: (not r["rank_eligible"],
        -(r["difference_pp"] if r["difference_pp"] is not None else -101), -r["matched"],
        r["term_count"], r["additional_allowed_bins"], r["pattern_id"]))
    equivalent = defaultdict(list)
    for row in rows:
        entry = data["patterns"][row["pattern_id"]]
        # Only discovery observations identify empirical redundancy.
        key = entry["masks"][2] & (populations[""] | populations["comparison_"])
        equivalent[key].append(row)
    for group in equivalent.values():
        if len(group) > 1:
            identity = _hash(sorted(r["pattern_id"] for r in group))[:12]
            for row in group:
                row["empirical_group"] = identity
    data["atoms"], data["atom_masks"] = tuple(atoms), tuple(masks)
    return rows, stats


def pattern_detail(data, pattern_id, checkpoint):
    """Small detached diagnostics, evaluated on the combination's assessable rows."""
    from .trend_start_patterns import _json
    entry = data["patterns"][pattern_id]
    indices, terms, combined = entry["indices"], entry["terms"], entry["masks"]
    populations = {k: v & combined[0] for k, v in data["populations"].items()}
    subsets = {(i,) for i in indices}
    if len(indices) > 1:
        subsets.update(tuple(i for i in indices if i != omitted) for omitted in indices)
    simpler = []
    for subset in sorted(subsets):
        masks = _merge_masks([data["atom_masks"][i] for i in subset])
        simpler.append({"conditions": [data["atoms"][i].to_dict() for i in subset],
            **_counts_for_masks(masks, populations, data["timing_mask"])})
    aliases = []
    for centers in product(*(t.centers for t in terms)):
        exact = 0
        for i, sample in enumerate(data["samples"]):
            if i % 128 == 0:
                checkpoint()
            actual, _, _, _ = observe(data, sample, terms)
            if actual == centers:
                exact |= 1 << i
        aliases.append({"centers": centers, **{k+"exact_matched": (p & exact).bit_count()
                                               for k, p in data["populations"].items()}})
    result = {"conditions": [t.to_dict() for t in terms], "exact_center_aliases": aliases,
            "simpler_on_same_assessable_rows": simpler,
            "note": "Ordinal tolerance; observed ranges are not decision boundaries. Simpler-rule counts use the combination's assessable rows."}
    if "_gr05_scope" in data:
        from copy import deepcopy
        result.update(family_scope=deepcopy(data["_gr05_scope"]), family_breakdown=_gr05_family_breakdown(data, pattern_id, checkpoint))
    return result


def occurrences(data, pattern_id, cohort, checkpoint):
    """Return a detached cohort ledger so matches AND every denominator can be inspected."""
    from .trend_start_patterns import _json
    if cohort not in ("target", "comparison"):
        raise ValueError("select target or comparison observations")
    terms = data["patterns"][pattern_id]["terms"]
    rows = []
    for sample in data["samples"]:
        checkpoint()
        if sample["cohort"] != cohort:
            continue
        actual, ready, matched, exact = observe(data, sample, terms)
        deviations = []
        if actual is not None:
            for term, value in zip(terms, actual, strict=True):
                bins = json.loads(term.metadata)
                indexes = {b["label"]: b.get("bin_index") for b in bins}
                distance = (indexes[value]-indexes[term.center] if indexes.get(value) is not None
                            and indexes.get(term.center) is not None else 0 if value == term.center else None)
                deviations.append({"column": term.column, "offset": term.offset, "actual": value,
                    "center": term.center, "allowed": term.allowed, "ordinal_deviation": distance,
                    "ts_ms": data["timestamps"][sample["anchor"]+term.offset], "profile_id": term.profile_id})
        rows.append({"event_id": sample["event_id"], "anchor_ts_ms": data["timestamps"][sample["anchor"]],
            "cutoff_ms": sample["cutoff_ms"], "partition": sample["partition"], "partition_reason": sample["partition_reason"],
            "assessable": actual is not None, "matched": matched, "exact_match": exact,
            "added_by_tolerance": matched and not exact, "ready_reference": ready, "verified_timing": sample["timing"],
            "ranking_support": ready and sample["timing"] and sample["partition"] == "discovery",
            "observations": _json(deviations), "evidence_start_ms": sample["evidence_start_ms"],
            "evidence_end_ms": sample["evidence_end_ms"]})
    frame = pd.DataFrame(rows, dtype=object)
    frame.attrs["pattern_detail"] = _json(pattern_detail(data, pattern_id, checkpoint))
    return frame


def run_pre_event(parent, instance, request, timestamps, checkpoint, progress):
    from .trend_start_patterns import (_axis_and_columns, _continuity, _event_row, _frequencies,
                                      _json, family_rows)
    columns = _axis_and_columns(parent, timestamps, request.columns, checkpoint)
    breaks, coverage = _continuity(timestamps, parent.entry.market_id.timeframe, instance, checkpoint)
    data = {"pre_event": True, "timestamps": timestamps, "positions": {t: i for i, t in enumerate(timestamps)},
        "columns": columns, "breaks": breaks, "coverage": coverage, "events": {e["event_id"]: e for e in instance["events"]},
        "measurement_reports": instance["measurement_reports"], "patterns": {}}
    from .pattern_refinement import _pin_source_binding
    data["_pin_source_binding"] = _pin_source_binding(
        parent, instance, timestamps, checkpoint=checkpoint
    )
    targets, assignments, funnel, excluded_starts = build_cohorts(data, instance, request, checkpoint)
    rows, search = mine(data, parent, request, checkpoint, progress)
    groups = defaultdict(list)
    for event in data["targets"]:
        groups[event["family"]].append(data["positions"][event["anchor_ts_ms"]])
    frequencies = _frequencies(data, groups, request, checkpoint)
    spec = request.pre_event
    context = {"database": parent.entry.name, "database_id": request.reference.database_id,
        "revision_id": request.reference.revision_id, "values_sha256": request.reference.values_sha256,
        "binning_run": request.run_key, "profiles": [(n, columns[n]["measurement"], columns[n]["profile_id"]) for n in sorted(columns)],
        "instance_id": request.instance_id, "utc_parameters": instance["parameters"], "rule_version": instance["rule_version"],
        "event_kind": request.event_kind, "role": request.role_label, "direction": request.trend_direction,
        "family": request.family, "origin": request.origin, "start_ms": request.start_ms, "end_ms": request.end_ms,
        "comparison": request.comparison, "pre_event": spec.to_dict(), "mined_offsets": spec.offsets,
        "after_inspection_only": request.after, "split_ms": data["split_ms"], "search": search,
        "refinement": request.refinement.to_dict(), "refinement_summary": request.refinement.summary(),
        "interpretation": "retrospective_full_history", "snapshot_read_ms": parent.snapshot_read_ms}
    diagnostics = [("Mode", "Pre-event combinations"), ("Search status", "Complete" if search["complete"] else "Incomplete search"),
        ("Search reason", search["reason"]), ("Examined candidates", search["examined"]),
        ("Estimated retained match-state bytes", search["estimated_match_bytes"]), ("Limits", f"{spec.candidate_limit} candidates / {spec.memory_limit_bytes} bytes"),
        ("Interpretation", "Retrospective full-history labels; no forecasting probability or significance"),
        ("Mined offsets", str(spec.offsets)), ("After window", "Inspection only; never used to discover or score rules"),
        ("Comparison question", request.comparison), ("Excluded background starts by direction", _json(excluded_starts)),
        ("Selected starts", len(targets)), ("Comparison observations", len(data["controls"])),
        ("Chronological inspection", "Retrospective temporal stability" if spec.chronological else "Full selected period discovery"),
        ("Split timestamp", data["split_ms"]), ("Refinement", request.refinement.summary()),
        ("Further refinement", "Change filters and rerun; previous results are invalidated. Reusing a later period remains exploratory."),
        ("Primary search", "Enabled" if len(request.columns) >= 2 and spec.history >= 2 else "Disabled: at least two columns and two history bars required; single baselines only"),
        ("Overlapping window groups", overlap_groups(data["samples"], spec.history, spec.lead)),
        ("Duplicate UTC witnesses", instance["duplicate_witnesses"]),
        ("Partition exclusions", _json(dict(Counter(s["partition_reason"] for s in data["samples"] if s["partition"] == "excluded"))))]
    for cohort in ("target", "comparison"):
        group = [s for s in data["samples"] if s["cohort"] == cohort]
        blocks = Counter(min(3, int(4*(data["timestamps"][s["anchor"]]-request.start_ms)/max(1, request.end_ms-request.start_ms+1))) for s in group)
        diagnostics.append((cohort.title()+" observations by four chronological blocks", _json(dict(sorted(blocks.items())))))
    event_rows = []
    assigned = {a["event_id"]: a for a in assignments}
    for event in targets:
        row = _event_row(event, data["positions"], timestamps)
        row.update({k: v for k, v in assigned[event["event_id"]].items() if k not in ("family", "anchor_ts_ms")})
        event_rows.append(row)
    tables = (("families", pd.DataFrame(family_rows(instance, request.event_kind, request.origin, request.start_ms, request.end_ms,
                    refinement=request.refinement), dtype=object)), ("refinement_funnel", pd.DataFrame(funnel, dtype=object)),
        ("cohort_assignments", pd.DataFrame(assignments, dtype=object)), ("frequencies", pd.DataFrame(frequencies, dtype=object)),
        ("patterns", pd.DataFrame(rows, dtype=object)), ("events", pd.DataFrame(event_rows, dtype=object)),
        ("diagnostics", pd.DataFrame(diagnostics, columns=("field", "value"), dtype=object)))
    checkpoint()
    if "_gr05_scope" in data:
        from .pattern_refinement import _gr05_family_population, _gr05_discovery_stamp
        summary = _gr05_family_population(assignments, data["samples"], data["events"], timestamps,
            data["_gr05_scope"], checkpoint=checkpoint)
        data["_gr05_family_population"] = summary
        context.update(family_scope=data["_gr05_scope"], family_population=summary)
        tables += (("family_population", pd.DataFrame(summary, dtype=object)),)
        study = PatternStudy(request, _json(context), tables, data)
        data["_gr05_discovery_binding"] = _gr05_discovery_stamp(study)
        return study
    return PatternStudy(request, _json(context), tables, data)


def _gr05_family_breakdown(data, pattern_id, checkpoint):
    scope = data["_gr05_scope"]
    grouped = {}
    for i, sample in enumerate(data["samples"]):
        if i % 128 == 0:
            checkpoint()
        family = None if sample["ordinary"] else data["events"][sample["event_id"]]["family"]
        key = (family, sample["ordinary"], sample["cohort"], sample["partition"])
        grouped[key] = grouped.get(key, 0) | (1 << i)
    rows = []
    groups = [(f, False) for f in scope["compatible_families"]]
    if scope["comparison"] == "non_start":
        groups.append((None, True))
    for family, ordinary in groups:
        checkpoint()
        for cohort in (("comparison",) if ordinary else ("target", "comparison")):
            for partition in ("discovery", "later", "excluded"):
                checkpoint()
                population = grouped.get((family, ordinary, cohort, partition), 0)
                rows.append(dict(family=family, ordinary=ordinary, scope_selected=family in scope["selected_families"],
                    cohort=cohort, partition=partition,
                    **_stats(*data["patterns"][pattern_id]["masks"], population, data["timing_mask"])))
    return rows
