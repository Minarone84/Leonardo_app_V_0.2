"""Read-only explanations of retained rules and explicit filter omissions."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from decimal import Context, Decimal, InvalidOperation, MAX_EMAX, MIN_EMIN, ROUND_HALF_EVEN, localcontext
from itertools import product
import json
import math

import pandas as pd

from .refinement_models import (
    CombinationInspection, FilterOmission, FrozenPatternSet, GranularPredicate,
    GranularRefinement, InspectionOptions, PatternEvaluation, RefinementSensitivity, _plain,
)
from .pre_event_patterns import _counts_for_masks, _stats, observe, occurrences, pattern_detail
from .trend_start_patterns import _checkpoint, _hash, _json, _progress


def numeric_summary(values):
    """Stagewise decimal50 convex interpolation; no bin fitting or financial arithmetic."""
    known, reasons = [], []
    context = Context(prec=50, rounding=ROUND_HALF_EVEN, Emin=MIN_EMIN, Emax=MAX_EMAX, traps=[])
    for value in values:
        if type(value) not in (int, float, str, Decimal):
            reasons.append("not_numeric"); continue
        with localcontext(context):
            try: number = Decimal(str(value)) if not isinstance(value, Decimal) else value
            except (InvalidOperation, ValueError): number = Decimal("NaN")
        if not number.is_finite():
            reasons.append("nonfinite_or_unparseable"); continue
        known.append(number)
    known.sort()
    result = dict(available_count=len(known), unavailable_count=len(reasons), unavailable_reasons=reasons,
        min=None, q1=None, median=None, q3=None, max=None,
        precision="50-significant-digit interpolation", status="unavailable_empty" if not known else "available")
    if not known: return result
    result.update(min=str(known[0]), max=str(known[-1]))
    for key, numerator in (("q1", 1), ("median", 2), ("q3", 3)):
        index, remainder = divmod((len(known)-1)*numerator, 4)
        if remainder == 0:
            value = known[index]
        else:
            weight = (Decimal("0"), Decimal(".25"), Decimal(".5"), Decimal(".75"))[remainder]
            with localcontext(context):
                value = known[index]*(Decimal(1)-weight) + known[index+1]*weight
        result[key] = str(value) if value.is_finite() else None
        if not value.is_finite(): result.update(status="unavailable_numerical", numerical_reason="nonfinite_interpolation")
    return result


def plan_filter_omissions(definition, omissions, *, source_request, column_profiles,
                         horizon_source, family_universe):
    """One bounded planner shared by presentation and execution; no population work."""
    from .pattern_refinement import validate_granular_definition
    if type(definition) is not GranularRefinement:
        raise ValueError("Sensitivity requires a completed granular checkpoint; explicitly Convert and Evaluate first")
    omissions = tuple(omissions)
    if not 1 <= len(omissions) <= 8:
        raise ValueError(f"omission variants requested={len(omissions)} allowed=1 through 8")
    if any(type(o) is not FilterOmission for o in omissions) or len(set(omissions)) != len(omissions):
        raise ValueError("omissions must be unique FilterOmission selections")
    result = []
    for omission in omissions:
        if omission.kind == "condition":
            groups = list(getattr(definition, omission.purpose))
            if omission.group_index >= len(groups): raise ValueError("unknown omission group")
            group = groups[omission.group_index]
            if omission.condition_index >= len(group.conditions): raise ValueError("unknown omission occurrence")
            removed = group.conditions[omission.condition_index]
            if not group.enabled or not removed.active: raise ValueError("inactive conditions cannot be omission variants")
            groups[omission.group_index] = replace(group, conditions=tuple(
                p for i, p in enumerate(group.conditions) if i != omission.condition_index))
            changed = {omission.purpose: tuple(groups)}
            description = removed.to_dict()
        else:
            removed = getattr(definition, omission.kind)
            if removed is None: raise ValueError("omission restriction is not explicitly applied")
            changed = {omission.kind: None}
            description = removed.to_dict()
        derived = replace(definition, **changed)
        status, reason = "valid", ""
        try:
            validate_granular_definition(derived, source_request=source_request,
                column_profiles=column_profiles, horizon_source=horizon_source, family_universe=family_universe)
        except (ValueError, TypeError) as exc:
            status, reason = "not_evaluated_invalid_definition", str(exc)
        result.append(dict(variant_key=omission.key, removal=_plain(omission), removed=description,
            before=definition.to_dict(), after=derived.to_dict(), before_id=definition.identity,
            after_id=derived.identity, status=status, reason=reason))
    return tuple(result)


def _canonical(value):
    if isinstance(value, pd.DataFrame):
        return {"columns":list(value.columns), "rows":_canonical(value.to_dict("records"))}
    if isinstance(value, dict): return {str(k):_canonical(v) for k,v in value.items()}
    if isinstance(value, (tuple, list)): return [_canonical(v) for v in value]
    if isinstance(value, Decimal): return str(value)
    if hasattr(value, "item"): return _canonical(value.item())
    if type(value) is float and not math.isfinite(value): return str(value)
    return value


def _table(rows, columns=()):
    return dict(columns=list(dict.fromkeys([*columns, *(k for r in rows for k in r)])), rows=_canonical(rows))


def _budget(payload, limit):
    if type(limit) is not int or not 1 <= limit <= 134217728:
        raise ValueError("report byte allowance must be 1 through 134217728")
    size = len(_json(_canonical(payload)).encode("utf-8"))
    if size > limit:
        raise ValueError(f"report_budget_exceeded: required={size} available={limit}; Clear report cache explicitly")
    return size


def _definition(result):
    return result.granular_definition or result.request.refinement


def _definition_id(result):
    return _hash(_definition(result).to_dict())


def _evaluation_digest(result):
    data = result._data
    return _hash(_canonical(dict(context=result.context, request=_plain(result.request),
        tables=[(n, _canonical(f)) for n,f in result._tables], samples=data["samples"],
        population=data.get("_gr03_population"),
        rules={k:dict(terms=[t.to_dict() for t in v["terms"]], indices=v["indices"], masks=v["masks"])
               for k,v in data["patterns"].items()}, atoms=({i:t.to_dict() for i,t in data["atoms"].items()}
                   if isinstance(data["atoms"],dict) else [t.to_dict() for t in data["atoms"]]),
        atom_masks=data["atom_masks"], populations=data["populations"], timing_mask=data["timing_mask"])))


def _bind_result(frozen, result, *, source=False, checkpoint=_checkpoint):
    from .pattern_models import PatternStudy
    from .pattern_refinement import _gr03_verify_discovery, _gr05_verify_simple, _fingerprint
    from .application import _gr03_validate_output
    checkpoint()
    definition = _definition(result)  # Reject malformed present markers.
    if source:
        if type(result) is not PatternStudy or result.request != frozen.original_request:
            raise ValueError("inspection source does not match frozen discovery")
        metadata = frozen.metadata()["source"]
        if (_canonical(json.loads(result.context)) != metadata["context"]
                or result._data.get("_pin_source_binding") != frozen._root["_gr03_source_binding"]):
            raise ValueError("inspection source context or discovery fingerprint mismatch")
        if isinstance(definition, GranularRefinement):
            _gr03_verify_discovery(result, checkpoint)
            if (result._data.get("_gr03_discovery_binding") != metadata["granular_discovery_binding"]
                    or _hash({k:v for k,v in result._data["_gr03_population"].items() if k!="accounting"})
                    != metadata["granular_population_digest"]):
                raise ValueError("inspection source population binding mismatch")
        else:
            _gr05_verify_simple(result, [r["family"] for r in json.loads(frozen.compatible_families)], checkpoint)
        columns = dict(metadata["columns"])
        for name, column in result._data["columns"].items():
            checkpoint()
            if _fingerprint(column["frame"]) != columns[name]: raise ValueError("inspection source column content mismatch")
    else:
        if (type(result) is not PatternEvaluation or result.root_id != frozen.root_id
                or result.set_id != frozen.set_id):
            raise ValueError("inspection result belongs to another frozen root/set")
        if isinstance(definition, GranularRefinement):
            _gr03_validate_output(result, frozen, definition, result.parent_id)
        elif result.evaluation_id != _hash(("gr01-evaluation-v1", frozen.set_id, result.parent_id, definition.to_dict())):
            raise ValueError("inspection evaluation definition identity mismatch")
    rows = result.frame("patterns")
    if rows.empty or not rows.pattern_id.is_unique: raise ValueError("retained rules are absent or duplicated")
    lookup = rows.set_index("pattern_id")
    if not source and set(lookup.index) != {p.pattern_id for p in frozen.patterns}:
        raise ValueError("inspection must preserve the entire pinned rule set")
    for rule in frozen.patterns:
        checkpoint()
        entry = result._data["patterns"].get(rule.pattern_id)
        if (entry is None or tuple(entry["terms"]) != rule.terms or rule.pattern_id not in lookup.index
                or _hash(tuple((t.column,t.offset,t.profile_id,t.allowed) for t in rule.terms)) != rule.pattern_id):
            raise ValueError("inspection retained rule/term identity mismatch")
        if any(result._data["columns"][t.column]["profile_id"] != t.profile_id for t in rule.terms):
            raise ValueError("inspection rule profile mismatch")
        computed = _counts_for_masks(entry["masks"], result._data["populations"], result._data["timing_mask"])
        row = lookup.loc[rule.pattern_id]
        for name, value in computed.items():
            actual = row[name]
            if value is None:
                if not pd.isna(actual): raise ValueError("tampered retained count table")
            elif actual != value: raise ValueError("tampered retained count table")
    return definition


def _active_metrics(result):
    definition = _definition(result)
    metrics = {}
    if isinstance(definition, GranularRefinement):
        for purpose in ("common", "outcome"):
            for gi, group in enumerate(getattr(definition, purpose)):
                for ci, predicate in enumerate(group.conditions):
                    if not group.enabled or not predicate.active or predicate.domain == "context" or predicate.field == "label": continue
                    row = metrics.setdefault(predicate.measurement_key, dict(predicate=replace(predicate,
                        minimum=None, maximum=None, allowed=(), lower_inclusive=True, upper_inclusive=True), paths=[]))
                    row["paths"].append(f"{purpose}/{gi}/{ci}")
    else:
        for domain, conditions, enabled, cohort in (
                ("movement", definition.movement, definition.movement_enabled, None),
                ("duration", definition.duration, definition.duration_enabled, None),
                ("pullbacks", definition.pullbacks.conditions, definition.pullbacks.enabled, definition.pullbacks.cohort)):
            for i,c in enumerate(conditions):
                if enabled and c.active:
                    p = GranularPredicate(domain, c.field, c.unit, basis=definition.basis, cohort=cohort, statistic=c.statistic)
                    metrics.setdefault(p.measurement_key, dict(predicate=p, paths=[]))["paths"].append(f"legacy/{domain}/{i}")
    return metrics


def _condition_rows(result, event_id):
    if result.granular_definition is not None:
        record = result.population_record(event_id)
        report = record["predicate_report"]
        if report is None:
            return {f"{purpose}/{gi}/{ci}":dict(status=record["evaluation_scope"],reason=record["reason"],selectors=p.to_dict())
                for purpose in ("common","outcome") for gi,g in enumerate(getattr(result.granular_definition,purpose))
                for ci,p in enumerate(g.conditions)}
        return {f"{p['purpose']}/{p['group_index']}/{p['predicate_index']}":deepcopy(p) for p in report["predicates"]}
    event = result._data["events"].get(event_id)
    if not event: return {}
    return {"legacy/"+name:deepcopy(value) for name,value in event.get("refinement",{}).get("stages",{}).items()}


def _block(timestamp, start, end):
    return min(3, (4*(timestamp-start))//(end-start+1))


class _InspectionAccounting:
    """Exact JSON contribution ownership for one inspection, including staging."""
    def __init__(self, limit, checkpoint):
        if type(limit) is not int or not 1 <= limit <= 134217728:
            raise ValueError("report byte allowance must be 1 through 134217728")
        self.limit, self.checkpoint = limit, checkpoint
        self.total = 0
        self.roots = set()
        self.units = self.emitted = 0
        self.stats = dict(scalars=0, copied_cells=0, prefix_rescans=0, snapshots=0)
        self.window_sources = []

    def tick(self, units=1, emitted=0):
        self.units += units
        self.emitted += emitted
        if self.units >= 256 or self.emitted >= 65536:
            self.checkpoint()
            self.units = self.emitted = 0

    def check(self):
        self.checkpoint()
        if self.total > self.limit:
            raise ValueError(f"report_budget_exceeded: required={self.total} available={self.limit}; Clear report cache explicitly")

    def scalar_size(self, value):
        self.checkpoint()
        size = len(_json(value).encode("utf-8"))
        self.stats["scalars"] += 1
        self.tick(emitted=size)
        self.checkpoint()
        return size

    def mapping(self, value=None):
        node = _InspectionMap(self)
        for key, child in (value or {}).items():
            node[str(key)] = child
        return node

    def array(self, value=()):
        node = _InspectionList(self)
        node.extend(value)
        return node

    def capture(self, value):
        if isinstance(value, (_InspectionMap, _InspectionList)):
            if value.owner is not self or value.parent is not None:
                raise ValueError("inspection fragment already attached")
            return value
        if isinstance(value, dict):
            return self.mapping(value)
        if isinstance(value, (list, tuple)):
            return self.array(value)
        if isinstance(value, Decimal):
            value = str(value)
        elif hasattr(value, "item"):
            return self.capture(value.item())
        elif type(value) is float and not math.isfinite(value):
            value = str(value)
        if value is not None and type(value) not in (str, int, float, bool):
            raise TypeError("unsupported inspection scalar")
        return value

    def table(self, rows, columns=()):
        names = dict.fromkeys(columns)
        for row in rows:
            self.tick()
            for key in row:
                self.tick()
                names.setdefault(key, None)
        return self.mapping(dict(columns=list(names), rows=rows))

    def finish(self, content):
        self.check()
        if self.roots != {id(content)}:
            raise ValueError("unattached inspection accounting fragments")
        payload = _inspection_encode(content, self.checkpoint)
        self.checkpoint()
        exact = len(payload.encode("utf-8"))
        if exact != self.total:
            raise ValueError(f"inspection accounting mismatch: tracked={self.total} exact={exact}")
        self.check()
        report = CombinationInspection._build(payload, self.checkpoint)
        self.checkpoint()
        return report


class _InspectionMap(dict):
    def __init__(self, owner):
        self.owner, self.parent, self.size = owner, None, 2
        self.sizes = {}
        owner.roots.add(id(self))
        owner.total += 2
        owner.check()

    def _grow(self, amount):
        self.size += amount
        if self.parent is not None:
            self.parent._grow(amount)

    def __setitem__(self, key, value):
        owner = self.owner
        owner.checkpoint()
        key = str(key)
        replacing = key in self
        if replacing:
            old = dict.__getitem__(self, key)
            old_size = old.size if isinstance(old, (_InspectionMap, _InspectionList)) else self.sizes[key]
            self._grow(-old_size)
            owner.total -= old_size
            if isinstance(old, (_InspectionMap, _InspectionList)):
                old.parent = None
        child = owner.capture(value)
        node = isinstance(child, (_InspectionMap, _InspectionList))
        size = child.size if node else owner.scalar_size(child)
        overhead = 0 if replacing else owner.scalar_size(key) + 1 + bool(self)
        change = overhead + size
        self._grow(change)
        owner.total += change - (size if node else 0)
        if node:
            owner.roots.remove(id(child))
            child.parent = self
        if key in self and isinstance(dict.__getitem__(self, key), (_InspectionMap, _InspectionList)):
            dict.__getitem__(self, key).parent = None
        dict.__setitem__(self, key, child)
        self.sizes[key] = size
        owner.check()


class _InspectionList(list):
    def __init__(self, owner):
        self.owner, self.parent, self.size = owner, None, 2
        owner.roots.add(id(self))
        owner.total += 2
        owner.check()

    def _grow(self, amount):
        self.size += amount
        if self.parent is not None:
            self.parent._grow(amount)

    def append(self, value):
        owner = self.owner
        owner.checkpoint()
        child = owner.capture(value)
        node = isinstance(child, (_InspectionMap, _InspectionList))
        size = child.size if node else owner.scalar_size(child)
        change = size + bool(self)
        self._grow(change)
        owner.total += change - (size if node else 0)
        if node:
            owner.roots.remove(id(child))
            child.parent = self
        list.append(self, child)
        owner.check()

    def extend(self, values):
        for value in values:
            self.append(value)

    def __iadd__(self, values):
        self.extend(values)
        return self


def _inspection_encode(value, checkpoint):
    """Same JSON settings as _json; checkpoints bracket indivisible scalars."""
    encoder = json.JSONEncoder(sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    pieces = []
    units = emitted = 0
    checkpoint()
    for piece in encoder.iterencode(value):
        checkpoint()
        pieces.append(piece)
        units += 1
        emitted += len(piece.encode("utf-8"))
        if units >= 256 or emitted >= 65536:
            checkpoint()
            units = emitted = 0
        checkpoint()
    checkpoint()
    result = "".join(pieces)
    checkpoint()
    return result


def _inspection_raw(value, checkpoint, counter=None):
    """Snapshot-cell encoding only; preserve floating NaN versus 'nan'."""
    counter = [0] if counter is None else counter
    counter[0] += 1
    if counter[0] >= 256:
        checkpoint()
        counter[0] = 0
    if isinstance(value, Decimal):
        return str(value)
    if hasattr(value, "item"):
        return _inspection_raw(value.item(), checkpoint, counter)
    if isinstance(value, dict):
        result = {}
        for key, child in value.items():
            counter[0] += 1
            if counter[0] >= 256:
                checkpoint()
                counter[0] = 0
            scalar_key = key.item() if hasattr(key, "item") else key
            if scalar_key is not None and type(scalar_key) not in (str, int, float, bool, Decimal):
                raise TypeError("unsupported inspection snapshot key")
            result[str(key)] = _inspection_raw(child, checkpoint, counter)
        return result
    if isinstance(value, (list, tuple)):
        return [_inspection_raw(v, checkpoint, counter) for v in value]
    if value is None or type(value) in (str, int, float, bool):
        return value
    raise TypeError("unsupported inspection snapshot cell")


def _inspection_sequence(values, checkpoint):
    """Normalize a structural sequence with bounded scalar-copy checkpoints."""
    counter = [0]
    result = []
    checkpoint()
    for value in values:
        result.append(_inspection_raw(value, checkpoint, counter))
    checkpoint()
    return result


def _inspection_equal(left, right, checkpoint, counter=None):
    counter = [0] if counter is None else counter
    counter[0] += 1
    if counter[0] >= 256:
        checkpoint()
        counter[0] = 0
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        if len(left) != len(right):
            return False
        for a, b in zip(left, right):
            if not _inspection_equal(a, b, checkpoint, counter) or not _inspection_equal(left[a], right[b], checkpoint, counter):
                return False
        return True
    if isinstance(left, list):
        return len(left) == len(right) and all(_inspection_equal(a, b, checkpoint, counter) for a, b in zip(left, right))
    if type(left) is float and math.isnan(left):
        return math.isnan(right)
    if type(left) is float and left == right == 0:
        return math.copysign(1, left) == math.copysign(1, right)
    return left == right


def _inspection_window_request(result, checkpoint=_checkpoint):
    request = result.request
    return dict(before=request.before, after=request.after,
                pre_event=None if request.pre_event is None else dict(offsets=_inspection_sequence(request.pre_event.offsets, checkpoint)))


def _inspection_same_window_inputs(left, right, checkpoint):
    checkpoint()
    if _inspection_window_request(left, checkpoint) != _inspection_window_request(right, checkpoint):
        return False
    a, b = left._data, right._data
    for name in ("timestamps", "coverage", "breaks"):
        if not _inspection_equal(_inspection_sequence(a[name], checkpoint), _inspection_sequence(b[name], checkpoint), checkpoint):
            return False
    if _inspection_sequence(a["positions"].items(), checkpoint) != _inspection_sequence(b["positions"].items(), checkpoint) or _inspection_sequence(a["columns"], checkpoint) != _inspection_sequence(b["columns"], checkpoint):
        return False
    for name, column in a["columns"].items():
        other = b["columns"][name]
        if (column["profile_id"], column["measurement"]) != (other["profile_id"], other["measurement"]):
            return False
        x, y = column["frame"], other["frame"]
        if _inspection_sequence(x.columns, checkpoint) != _inspection_sequence(y.columns, checkpoint) or len(x) != len(y):
            return False
        for i in range(len(x)):
            checkpoint()
            if not _inspection_equal(_inspection_raw(x.iloc[i].to_dict(), checkpoint),
                                     _inspection_raw(y.iloc[i].to_dict(), checkpoint), checkpoint):
                return False
    checkpoint()
    return True


def _inspection_window_source(result, store, account):
    from hashlib import sha256
    account.checkpoint()
    for previous, key in account.window_sources:
        if _inspection_same_window_inputs(previous, result, account.checkpoint):
            return key
    data = result._data
    columns = []
    for name, column in data["columns"].items():
        account.checkpoint()
        frame = column["frame"]
        names = _inspection_sequence(frame.columns, account.checkpoint)
        rows = []
        for i in range(len(frame)):
            account.checkpoint()
            row = frame.iloc[i].to_dict()
            rows.append(_inspection_sequence((row[n] for n in names), account.checkpoint))
            account.stats["copied_cells"] += len(names)
        columns.append(dict(name=name, profile_id=column["profile_id"], measurement=column["measurement"],
                            frame_columns=names, frame_rows=rows))
    snapshot = dict(timestamps=_inspection_sequence(data["timestamps"], account.checkpoint),
                    positions=_inspection_sequence(data["positions"].items(), account.checkpoint),
                    coverage=_inspection_sequence(data["coverage"], account.checkpoint),
                    breaks=_inspection_sequence(data["breaks"], account.checkpoint),
                    columns=columns, request=_inspection_window_request(result, account.checkpoint))
    payload = _inspection_encode(snapshot, account.checkpoint)
    account.checkpoint()
    key = sha256(payload.encode("utf-8")).hexdigest()
    sources = store["sources"]
    if key in sources and sources[key] != payload:
        raise ValueError("inspection snapshot digest collision")
    if key not in sources:
        sources[key] = payload
        account.stats["snapshots"] += 1
    account.window_sources.append((result, key))
    account.checkpoint()
    return key


def _support_link(content, side, key, ids):
    identity = _hash((side, key))
    content["links"][identity] = dict(side=side, row_ids=sorted(set(ids)), purpose=key)
    return identity


def _side_records(frozen, result, rule, side, metrics, checkpoint, progress, limit, storage):
    from .pattern_refinement import _statuses, resolve_inspection_measurements
    data = result._data
    population = data.get("_gr03_population")
    statuses = _statuses(result.frame("cohort_assignments").to_dict("records"), data["samples"],
                         data["timestamps"], population=population)
    samples = {s["event_id"]:(i,s) for i,s in enumerate(data["samples"])}
    entry = data["patterns"][rule.pattern_id]
    masks = entry["masks"]
    occurrence_rows={r["event_id"]:r for cohort in ("target","comparison")
        for r in occurrences(data,rule.pattern_id,cohort,checkpoint).to_dict("records")}
    measured = resolve_inspection_measurements(frozen, result, tuple(v["predicate"] for v in metrics.values()),
        checkpoint=checkpoint, progress=progress, memory_limit_bytes=limit)
    account, source_key, view_kind = storage
    records = account.mapping()
    for count,(row_id,status) in enumerate(statuses.items()):
        checkpoint()
        pair = samples.get(row_id)
        if pair is None:
            sample = dict(event_id=row_id, anchor=data["positions"].get(status["anchor_ts_ms"]), ordinary=status["ordinary"])
            bits = (None, False, False, False)
        else:
            index,sample = pair; bits = tuple(bool(mask & (1<<index)) for mask in masks)
            occurrence=occurrence_rows[row_id]
            if (occurrence["assessable"],occurrence["matched"],occurrence["exact_match"])!=(bits[0],bits[2],bits[3]):
                raise ValueError("retained masks disagree with canonical observations")
        event = data["events"].get(row_id)
        record = dict(row_id=row_id, side=side, **deepcopy(status), family=None if status["ordinary"] else event["family"],
            block=_block(status["anchor_ts_ms"],frozen.original_request.start_ms,frozen.original_request.end_ms),
            assessable=bits[0], matched=bits[2], exact_match=bits[3], added_by_tolerance=bits[2] and not bits[3],
            ready_timing=bool(pair and bits[1] and sample["timing"]),
            cutoff_ms=None if pair is None else sample["cutoff_ms"],
            terms=[], conditions=_condition_rows(result,row_id), metrics=measured.get(row_id,{}))
        for ti,term in enumerate(rule.terms):
            checkpoint()
            anchor=sample["anchor"]
            actual, ready, hit, center = observe(data,sample,(term,)) if type(anchor) is int else (None,False,False,False)
            position=None if anchor is None else anchor+term.offset
            cell=(data["columns"][term.column]["frame"].iloc[position].to_dict()
                  if position is not None and 0<=position<len(data["timestamps"]) else {})
            record["terms"].append(dict(index=ti, **term.to_dict(), actual=None if actual is None else actual[0],
                available=actual is not None, matched=hit if actual is not None else None,
                representative_match=center if actual is not None else None, ready_reference=ready,
                raw_value=_canonical(cell.get("raw_value")), source_cell=_canonical(cell),
                source_ts_ms=None if not cell else data["timestamps"][position],
                range_meaning="observed occupancy; not decision boundaries"))
        if population is not None: record["population_evidence"]=result.population_record(row_id)
        else: record["legacy_evidence"]=deepcopy(event.get("refinement",{})) if event else None
        # Retain canonical event evidence, not a fabricated S/F/E/O projection for controls.
        evidence=result.evidence(row_id)
        evidence.pop("copied_measurement_reports",None)
        evidence.pop("granular_population_record",None)
        record["event_evidence"]=_canonical(evidence)
        record["event_window"]=dict(source_key=source_key, event_id=row_id,
            anchor_ts_ms=status["anchor_ts_ms"], view_kind=view_kind)
        records[row_id]=record
        account.check()
    checkpoint()
    return records


def _count_rows(content, side, result, rule, checkpoint):
    data=result._data; entry=data["patterns"][rule.pattern_id]; masks=entry["masks"]
    samples=data["samples"]; ledger=content["records"][side]
    saved=result.frame("patterns").set_index("pattern_id").loc[rule.pattern_id].to_dict()
    counts=[]; four=[]; families=[]; blocks=[]
    groups=[("all",None)]+[("family",f) for f in content["header"]["families"]]+[("family","ordinary")]+[("block",i) for i in range(4)]
    for period in ("discovery","later","eligible_combined","excluded"):
        for group,value in groups:
            checkpoint()
            populations={}
            for cohort in ("target","comparison"):
                population=0
                for i,s in enumerate(samples):
                    r=ledger[s["event_id"]]
                    if s["cohort"]!=cohort or (s["partition"] not in ("discovery","later") if period=="eligible_combined" else s["partition"]!=period): continue
                    if group=="family" and ("ordinary" if r["ordinary"] else r["family"])!=value: continue
                    if group=="block" and r["block"]!=value: continue
                    population|=1<<i
                populations[cohort]=population
                stats=_stats(*masks,population,data["timing_mask"])
                row=dict(side=side,period=period,cohort=cohort,group=group,group_value=value,**stats,
                    support_kind="original discovery support" if not isinstance(result,PatternEvaluation) else "current support",
                    support=saved.get("support_eligible",saved.get("rank_eligible")),
                    support_reason=saved.get("support_reason",saved.get("rank_reason")), qualified=period!="excluded")
                valid,ready,matched,exact=masks; timing=data["timing_mask"]
                supports=dict(total=population,assessable=population&valid,excluded=population&~valid,
                    matched=population&matched,exact_matched=population&exact,added_by_tolerance=population&matched&~exact,
                    exact_ready_matched=population&exact&ready&timing,ready_assessable=population&ready&timing,
                    ready_matched=population&matched&ready&timing,timing_withheld=population&valid&~timing)
                for name,mask in supports.items():
                    ids=[s["event_id"] for i,s in enumerate(samples) if mask&(1<<i)]
                    row[name+"_rows"]=_support_link(content,side,[period,group,value,cohort,name],ids)
                if group=="family": families.append(row)
                elif group=="block":
                    start,end=content["header"]["root_interval"]; span=end-start+1
                    row.update(block_start_ms=start+(value*span+3)//4,block_end_ms=start+((value+1)*span+3)//4-1)
                    ts=[data["timestamps"][s["anchor"]] for i,s in enumerate(samples) if population&(1<<i)]
                    row.update(observed_min_ms=min(ts,default=None),observed_max_ms=max(ts,default=None),empty_block=row["block_end_ms"]<row["block_start_ms"])
                    blocks.append(row)
                else: counts.append(row)
            if group!="all" or period=="excluded": continue
            for exact_mode in (False,True):
                for ready_only in (False,True):
                    assess=masks[0] & (masks[1]&data["timing_mask"] if ready_only else -1)
                    match=masks[3] if exact_mode else masks[2]
                    cells={"a":populations["target"]&assess&match,"b":populations["target"]&assess&~match,
                           "c":populations["comparison"]&assess&match,"d":populations["comparison"]&assess&~match}
                    values={k:m.bit_count() for k,m in cells.items()}
                    a,b,c,d=(values[k] for k in "abcd")
                    question=content["header"]["comparison"]
                    row=dict(side=side,period=period,matching="representative exact center" if exact_mode else "original allowed sets",
                        ready_only=ready_only,comparison=question,
                        target_frequency=a/(a+b) if a+b else None,
                        comparison_frequency=c/(c+d) if c+d and question!="recurrence" else None,
                        difference_pp=100*(a/(a+b)-c/(c+d)) if a+b and c+d and question!="recurrence" else None,
                        interpretation=("Historical desired-outcome share among matches in this selected universe"
                                        if question=="other_outcomes" else "Cohort frequency comparison" if question!="recurrence" else "Recurrence; no comparison or outcome share"))
                    if question=="other_outcomes":
                        row.update(values,historical_desired_outcome_share=a/(a+c) if a+c else None)
                    else:
                        row.update(target_matched=a,target_nonmatched=b)
                        if question!="recurrence":row.update(comparison_matched=c,comparison_nonmatched=d)
                        else:
                            row.pop("comparison_frequency");row.pop("difference_pp")
                    for name,mask in cells.items():
                        if question=="recurrence" and name in "cd":continue
                        label=name if question=="other_outcomes" else dict(a="target_matched",b="target_nonmatched",c="comparison_matched",d="comparison_nonmatched")[name]
                        row[label+"_rows"]=_support_link(content,side,["cells",period,exact_mode,ready_only,name],
                            [s["event_id"] for i,s in enumerate(samples) if mask&(1<<i)])
                    for label,mask in (("target_denominator",cells["a"]|cells["b"]),("comparison_denominator",cells["c"]|cells["d"]),
                            ("share_denominator",cells["a"]|cells["c"])):
                        if label=="share_denominator" and question!="other_outcomes" or label=="comparison_denominator" and question=="recurrence":continue
                        row[label+"_rows"]=_support_link(content,side,["denominator",period,exact_mode,ready_only,label],
                            [s["event_id"] for i,s in enumerate(samples) if mask&(1<<i)])
                    four.append(row)
    return counts,four,families,blocks


def _distribution_rows(content, side, records, metrics, checkpoint, limit, rows):
    for key,metric in metrics.items():
        for period in ("discovery","later","eligible_combined","excluded"):
            for cohort in ("target","comparison"):
                for matched in (False,True):
                    base=[r for r in records.values() if r["cohort"]==cohort and r["assessable"] is True and r["matched"]==matched
                        and (r["partition"] in ("discovery","later") if period=="eligible_combined" else r["partition"]==period)]
                    for ready_only in (False,True):
                        available=[r for r in base if not ready_only or r["ready_timing"]]
                        groups={(None,None)}
                        for r in available:
                            family="ordinary" if r["ordinary"] else r["family"]
                            groups.update(((family,None),(None,r["block"]),(family,r["block"])))
                        for family,block in sorted(groups,key=lambda pair:(str(pair[0]),str(pair[1]))):
                            checkpoint()
                            selected=[r for r in available if (family is None or ("ordinary" if r["ordinary"] else r["family"])==family)
                                and (block is None or r["block"]==block)]
                            known=[r for r in selected if r["metrics"].get(key,{}).get("known")]
                            withheld=[r for r in known if r["metrics"][key]["timing_withheld"] and period!="excluded"]
                            ids_withheld={r["row_id"] for r in withheld}
                            summarized=[r for r in known if r["row_id"] not in ids_withheld]
                            row=dict(side=side,period=period,cohort=cohort,matched=matched,ready_only=ready_only,
                                family=family,block=block,measurement_key=key,selectors=metric["predicate"].to_dict(),
                                condition_paths=metric["paths"],inspection_only=not bool(metric["paths"]),
                                base_selected=len(selected),values_known=len(known),source_coherence_unavailable=len(selected)-len(known),
                                metric_timing_withheld=len(withheld),values_summarized=len(summarized),
                                **numeric_summary(r["metrics"][key]["value"] for r in summarized))
                            for label,support in (("base",selected),("known",known),("timing_withheld",withheld),("summarized",summarized),
                                    ("unavailable",[r for r in selected if not r["metrics"].get(key,{}).get("known")])):
                                row[label+"_rows"]=_support_link(content,side,["metric",key,period,cohort,matched,ready_only,family,block,label],
                                    [r["row_id"] for r in support])
                            rows.append(row)
                            rows.owner.check()
    return rows


def inspect_combination(frozen, discovery, current, parent, pattern_id, options,
                        *, checkpoint=_checkpoint, progress=_progress, memory_limit_bytes=134217728):
    """Build detached linked diagnostics from the exact completed checkpoint."""
    from .pattern_refinement import _changes
    checkpoint()
    if type(frozen) is not FrozenPatternSet or type(options) is not InspectionOptions:
        raise TypeError("inspection requires a frozen set and InspectionOptions")
    _bind_result(frozen,discovery,source=True,checkpoint=checkpoint)
    rule=next((p for p in frozen.patterns if p.pattern_id==pattern_id),None)
    if rule is None: raise ValueError("inspection requires a retained pinned rule")
    source_current=current is discovery
    if not source_current: _bind_result(frozen,current,checkpoint=checkpoint)
    actual_parent=None if source_current else current.parent_id
    if source_current and parent is not None: raise ValueError("source discovery has no parent")
    if not source_current:
        if actual_parent==frozen.source_discovery_id:
            if parent is not None and parent is not discovery: raise ValueError("wrong actual parent")
            parent=discovery
        elif parent is None or parent.evaluation_id!=actual_parent: raise ValueError("actual saved parent is required")
        else: _bind_result(frozen,parent,checkpoint=checkpoint)
    product_size=math.prod(len(t.centers) for t in rule.terms)
    if product_size>4096: raise ValueError(f"exact-center products requested={product_size} allowed=4096")
    sides={"source":discovery,"current":current}
    if parent is not None: sides["parent"]=parent
    header=dict(root_id=frozen.root_id,set_id=frozen.set_id,source_discovery_id=frozen.source_discovery_id,
        checkpoint_id=frozen.source_discovery_id if source_current else current.evaluation_id,
        actual_parent_id=actual_parent,pattern_id=pattern_id,definition_id=_definition_id(current),
        applied_definition=_definition(current).to_dict(),options_id=options.identity,
        extra_metrics=[p.to_dict() for p in options.extra_metrics],rule=[t.to_dict() for t in rule.terms],
        original_order=rule.original_order,original_row=json.loads(rule.original_row),
        source_provenance=frozen.metadata(),root_interval=[frozen.original_request.start_ms,frozen.original_request.end_ms],
        comparison=frozen.original_request.comparison,families=[r["family"] for r in json.loads(frozen.compatible_families)],
        condition_paths={},metric_keys={},metric_descriptors={},
        limitations=["Retrospective/full-history preprocessing", "Repeated adaptive refinement remains exploratory",
            "Overlapping events and blocks are not independent samples", "Unknown and snapshot-only timing remain explicit",
            "Observed bin occupancy is not a decision boundary", "Low support/empty comparisons remain visible",
            "Family mix may change pooled counts; no predictive accuracy, calibrated probability or causal importance"])
    account = _InspectionAccounting(memory_limit_bytes, checkpoint)
    content=account.mapping(dict(header=header,tables={},records={},links={},
        window_store=dict(schema="gr06-inspection-window-store-v1",sources={})))
    header=content["header"]
    all_counts=account.array();all_four=account.array();all_families=account.array();all_blocks=account.array()
    distributions=account.array();simpler=account.array();centers=account.array();effects=account.array();retention=account.array()
    if any(p.measurement_key in _active_metrics(current) for p in options.extra_metrics):
        raise ValueError("inspection metric duplicates an active measurement")
    for side,result in sides.items():
        checkpoint()
        metrics=_active_metrics(result)
        for p in options.extra_metrics:
            if p.measurement_key in metrics: continue
            metrics[p.measurement_key]=dict(predicate=p,paths=[],inspection_only=True)
        if len(metrics)>40: raise ValueError(f"numeric measurements requested={len(metrics)} allowed=40")
        header["metric_keys"][side]=list(metrics)
        header["metric_descriptors"][side]=[{"measurement_key":k,"selectors":v["predicate"].to_dict(),
            "condition_paths":v["paths"],"inspection_only":not bool(v["paths"])} for k,v in metrics.items()]
        source_key=_inspection_window_source(result,content["window_store"],account)
        view_kind="evaluation" if isinstance(result,PatternEvaluation) else "study"
        records=_side_records(frozen,result,rule,side,metrics,checkpoint,progress,memory_limit_bytes,
            (account,source_key,view_kind))
        content["records"][side]=records
        header["condition_paths"][side]=sorted({p for r in records.values() for p in r["conditions"]})
        counts,four,families,blocks=_count_rows(content,side,result,rule,checkpoint)
        all_counts+=counts;all_four+=four;all_families+=families;all_blocks+=blocks
        _distribution_rows(content,side,records,metrics,checkpoint,memory_limit_bytes,distributions)
        for period in ("discovery","later","eligible_combined","excluded"):
            data=result._data
            populations={}
            for prefix,cohort in (("","target"),("comparison_","comparison"),("later_","target"),("later_comparison_","comparison")):
                populations[prefix]=sum(1<<i for i,s in enumerate(data["samples"]) if s["cohort"]==cohort
                    and (s["partition"] in ("discovery","later") if period=="eligible_combined" else s["partition"]==period))
            detail=pattern_detail({**data,"populations":populations},pattern_id,checkpoint)
            for index,row in enumerate(detail["simpler_on_same_assessable_rows"]):
                terms=tuple(t for t in rule.terms if t.to_dict() in row["conditions"])
                diagnostic=dict(side=side,period=period,subset_index=index,**row)
                for prefix,mask in populations.items():
                    sample_rows=[s for i,s in enumerate(data["samples"]) if mask&(1<<i) and records[s["event_id"]]["assessable"] is True]
                    observed=[(s,observe(data,s,terms)) for s in sample_rows]
                    for kind,ids in (("assessable",[s["event_id"] for s in sample_rows]),
                            ("matched",[s["event_id"] for s,o in observed if o[2]]),
                            ("exact_matched",[s["event_id"] for s,o in observed if o[3]]),
                            ("added_by_tolerance",[s["event_id"] for s,o in observed if o[2] and not o[3]])):
                        diagnostic[prefix+kind+"_rows"]=_support_link(content,side,["simpler",period,index,prefix,kind],ids)
                simpler.append(diagnostic)
            for index,row in enumerate(detail["exact_center_aliases"]):
                diagnostic=dict(side=side,period=period,alias_index=index,**row)
                for prefix,mask in populations.items():
                    ids=[s["event_id"] for i,s in enumerate(data["samples"]) if mask&(1<<i)
                        and observe(data,s,rule.terms)[0]==tuple(row["centers"])]
                    diagnostic[prefix+"exact_matched_rows"]=_support_link(content,side,["center",period,index,prefix],ids)
                centers.append(diagnostic)
        for path in header["condition_paths"][side]:
            for status in sorted({r["conditions"][path]["status"] for r in records.values() if path in r["conditions"]}):
                ids=[r["row_id"] for r in records.values() if r["conditions"].get(path,{}).get("status")==status]
                effects.append(dict(side=side,path=path,status=status,count=len(ids),
                    rows=_support_link(content,side,["condition",path,status],ids),interpretation="Overlapping evidence states; not additive causal attribution"))
        account.check()
        progress("Explaining completed combination",len(content["records"]),len(sides))
    current_records=content["records"]["current"]
    for reference in ("source","parent"):
        if reference not in content["records"]: continue
        before=content["records"][reference]
        status_keys=("anchor_ts_ms","ordinary","cohort","partition","reason","partition_reason")
        changes=_changes({k:{n:r[n] for n in status_keys} for k,r in before.items()},
                         {k:{n:r[n] for n in status_keys} for k,r in current_records.items()})
        for row in changes:
            if row["event_id"] in current_records and reference=="parent": current_records[row["event_id"]]["population_change"]=row["change"]
        for cohort in ("target","comparison","all"):
            def ids(rows): return {k for k,r in rows.items() if r["cohort"] in ("target","comparison")
                and r["partition"] in ("discovery","later") and (cohort=="all" or r["cohort"]==cohort)}
            old,new=ids(before),ids(current_records)
            intersection=old&new
            retention.append(dict(reference=reference,cohort=cohort,reference_count=len(old),current_count=len(new),
                intersection=len(intersection),retained_share=len(intersection)/len(old) if old else None,
                population_size_ratio=len(new)/len(old) if old else None,
                numerator_rows=_support_link(content,"current",["retained",reference,cohort],intersection),
                denominator_rows=_support_link(content,reference,["reference",cohort],old)))
        content["tables"]["changes_"+reference]=account.table(account.array(changes))
    for name,rows in (("counts",all_counts),("comparison",all_four),("families",all_families),("time_blocks",all_blocks),
            ("distributions",distributions),("simpler",simpler),("centers",centers),("filter_effects",effects),("retention",retention)):
        content["tables"][name]=account.table(rows)
    content["tables"]["rules"]=account.table(account.array([json.loads(p.original_row) for p in frozen.patterns]))
    return account.finish(content)


def refinement_sensitivity(frozen, current, omissions, *, checkpoint=_checkpoint, progress=_progress,
                           memory_limit_bytes=134217728):
    from .service import AnalysisService
    from .pattern_refinement import _gr03_charge
    checkpoint()
    source=not isinstance(current,PatternEvaluation)
    _bind_result(frozen,current,source=source,checkpoint=checkpoint)
    context=frozen.filter_context()
    plan=plan_filter_omissions(_definition(current),omissions,source_request=frozen.original_request,
        column_profiles={n:c["profile_id"] for n,c in context["columns"].items()},
        horizon_source=context.get("horizon_source"),family_universe=context.get("family_scope_context",{}).get("families"))
    content=dict(header=dict(root_id=frozen.root_id,set_id=frozen.set_id,source_discovery_id=frozen.source_discovery_id,
        checkpoint_id=frozen.source_discovery_id if source else current.evaluation_id,
        definition_id=_definition_id(current),rule_ids=[p.pattern_id for p in frozen.patterns],
        planned_variants=len(plan),valid_variants=sum(p["status"]=="valid" for p in plan),
        interpretation="Sensitivity variants, not checkpoints; descriptive filter dependence, not causal importance"),
        plan=plan,tables={},evaluation_digests={})
    evaluations=[];charged=0
    for index,row in enumerate(plan):
        checkpoint();progress("Comparing explicit omissions",index,len(plan))
        if row["status"]!="valid": continue
        remaining=memory_limit_bytes-charged-_budget(content,memory_limit_bytes)
        if remaining<1: raise ValueError(f"sensitivity budget exhausted: available={remaining}; Clear report cache explicitly")
        # The accepted stateless service route owns selection of the evaluator.
        value=AnalysisService.evaluate_pattern_set(None,frozen,GranularRefinement.from_dict(row["after"]),
            parent=None if source else current,checkpoint=checkpoint,progress=progress,memory_limit_bytes=remaining)
        checkpoint()
        _bind_result(frozen,value,checkpoint=checkpoint)
        expected_parent=frozen.source_discovery_id if source else current.evaluation_id
        if value.parent_id!=expected_parent: raise ValueError("sensitivity returned an alien parent")
        charged+=json.loads(value.context)["estimated_retained_match_state_bytes"]+_gr03_charge(value._data["_gr03_population"])
        key=row["variant_key"]
        evaluations.append((key,value));content["evaluation_digests"][key]=_evaluation_digest(value)
        for name in ("patterns","population_changes","population","family_population"):
            if any(n==name for n,_ in value._tables): content["tables"][key+"/"+name]=_canonical(value.frame(name))
        if charged+_budget(content,memory_limit_bytes)>memory_limit_bytes:
            raise ValueError(f"sensitivity report budget exceeded: required={charged+len(_json(content).encode('utf-8'))} available={memory_limit_bytes}")
    checkpoint();progress("Sensitivity complete",len(plan),len(plan))
    report=RefinementSensitivity(_json(_canonical(content)),tuple(evaluations))
    if report.retained_bytes>memory_limit_bytes: raise ValueError("sensitivity report exceeds retained allowance")
    return report
