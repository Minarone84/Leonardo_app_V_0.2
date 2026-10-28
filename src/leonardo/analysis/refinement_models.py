"""Disposable frozen-combination values; no persistence or session ownership."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field, fields, is_dataclass
from decimal import Decimal
import json

import pandas as pd

from .pattern_models import PatternRequest, PatternRefinement, FamilyScope, _gr05_source_selection
from .pre_event_patterns import Term, occurrences
from .trend_start_patterns import _checkpoint, _json, event_evidence, event_window


def _plain(value):
    if isinstance(value, Decimal):
        return str(value)
    if is_dataclass(value):
        return {f.name: _plain(getattr(value, f.name)) for f in fields(value)
                if not (f.name == "family_scope" and isinstance(value, (PatternRefinement, GranularRefinement))
                        and getattr(value, f.name) is None)
                and not (f.name == "anchor_range" and isinstance(value, GranularRefinement)
                         and getattr(value, f.name) is None)}
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(v) for v in value]
    return value


def _table(frame):
    """Pandas deep copying alone does not detach mutable object cells or attrs."""
    result = frame.copy(deep=True)
    for name in result.columns:
        if result[name].dtype == object:
            result[name] = pd.Series([
                _json(_plain(v)) if isinstance(v, (dict, list, tuple)) else deepcopy(v)
                for v in result[name]], index=result.index, dtype=object)
    result.attrs = deepcopy(frame.attrs)
    return result


_OCCURRENCE_COLUMNS = (
    "event_id", "anchor_ts_ms", "cutoff_ms", "partition", "partition_reason", "assessable",
    "matched", "exact_match", "added_by_tolerance", "ready_reference", "verified_timing",
    "ranking_support", "observations", "evidence_start_ms", "evidence_end_ms",
)


@dataclass(frozen=True, slots=True)
class FrozenPattern:
    pattern_id: str
    terms: tuple[Term, ...]
    original_order: int
    original_row: str

    def __post_init__(self):
        terms = tuple(self.terms)
        if (not isinstance(self.pattern_id, str) or not self.pattern_id or not terms
                or any(not isinstance(t, Term) for t in terms)
                or type(self.original_order) is not int or self.original_order < 1):
            raise ValueError("frozen pattern requires an identity, terms and original row position")
        if not isinstance(self.original_row, str) or not isinstance(json.loads(self.original_row), dict):
            raise ValueError("original row metadata must be immutable JSON")
        object.__setattr__(self, "terms", tuple(Term(t.column, t.offset, t.profile_id,
            tuple(t.centers), tuple(t.allowed), t.metadata) for t in terms))


@dataclass(frozen=True, slots=True)
class FrozenPatternSet:
    root_id: str
    source_discovery_id: str
    set_id: str
    original_request: PatternRequest
    resolved_split: int | None
    compatible_families: str
    patterns: tuple[FrozenPattern, ...]
    _metadata: str = field(repr=False)
    _root: object = field(repr=False, compare=False)

    def __post_init__(self):
        patterns = tuple(self.patterns)
        if (not 1 <= len(patterns) <= 500 or any(not isinstance(p, FrozenPattern) for p in patterns)
                or len({p.pattern_id for p in patterns}) != len(patterns)):
            raise ValueError("pin 1 to 500 unique frozen patterns")
        if not isinstance(self.original_request, PatternRequest):
            raise TypeError("frozen set requires the original request")
        object.__setattr__(self, "patterns", patterns)

    def metadata(self):
        return json.loads(self._metadata)

    def original_patterns(self):
        return pd.DataFrame([json.loads(p.original_row) for p in self.patterns], dtype=object)

    @property
    def granular_definition(self):
        return _gr03_definition(self._root)

    def filter_context(self):
        result = deepcopy(self._root.get("_gr03_filter_context", {}))
        if result:
            selection = _gr05_source_selection(self.original_request)
            result["family_scope_context"] = dict(families=sorted(r["family"] for r in json.loads(self.compatible_families)),
                direction=self.original_request.trend_direction, comparison=self.original_request.comparison,
                source_selection=None if selection is None else selection.to_dict())
        return result


@dataclass(frozen=True, slots=True)
class PatternEvaluation:
    root_id: str
    set_id: str
    evaluation_id: str
    parent_id: str
    request: PatternRequest
    context: str
    _tables: tuple[tuple[str, pd.DataFrame], ...] = field(repr=False, compare=False)
    _data: object = field(repr=False, compare=False)

    def frame(self, name):
        self.granular_definition  # A malformed present marker must never fall back to legacy.
        for key, frame in self._tables:
            if key == name:
                return _table(frame)
        raise KeyError(f"unknown evaluation table: {name}")

    def pattern_matches(self, pattern_id, cohort="target", *, checkpoint=_checkpoint):
        checkpoint()
        if pattern_id not in self._data["patterns"]:
            raise ValueError("unknown frozen pattern ID")
        if cohort not in ("target", "comparison"):
            raise ValueError("select target or comparison observations")
        frame = occurrences(self._data, pattern_id, cohort, checkpoint)
        if frame.empty and not len(frame.columns):
            attrs = deepcopy(frame.attrs)
            frame = pd.DataFrame(columns=_OCCURRENCE_COLUMNS, dtype=object)
            frame.attrs = attrs
        checkpoint()
        return _table(frame)

    def _check_event(self, event_id):
        if self.granular_definition is not None:
            self.population_record(event_id)
            return
        if (not isinstance(event_id, str) or
                (event_id not in self._data["events"] and event_id not in self._data["control_ids"])):
            raise ValueError("event/control ID is not in this evaluation universe")

    def event_window(self, event_id):
        self._check_event(event_id)
        return _table(event_window(self._data, self.request, event_id))

    def evidence(self, event_id):
        self._check_event(event_id)
        result = deepcopy(event_evidence(self._data, event_id))
        if self.granular_definition is not None:
            result["granular_population_record"] = self.population_record(event_id)
        return result

    @property
    def granular_definition(self):
        from .refinement_models import _gr03_definition
        return _gr03_definition(self._data)

    def population_report(self):
        from copy import deepcopy
        from .refinement_models import _gr03_population
        return deepcopy(_gr03_population(self._data))

    def population_record(self, row_id):
        from .refinement_models import _gr03_population_record
        return _gr03_population_record(self._data, row_id)


# Task 1078: granular predicate foundation.
from collections.abc import Mapping as _granular_Mapping
from decimal import localcontext as _granular_localcontext
import re as _granular_re
from .pattern_models import (
    NumericCondition as _granular_NumericCondition,
    PrecedingContextFilter as _granular_PrecedingContextFilter,
    MEASUREMENT_BASES as _granular_BASES,
    MOVEMENT_FIELDS as _granular_MOVEMENT_FIELDS,
    DURATION_FIELDS as _granular_DURATION_FIELDS,
    PULLBACK_COHORTS as _granular_COHORTS,
)
from .trend_start_patterns import _hash as _granular_hash


def _granular_sequence(value, name):
    if not isinstance(value, (list, tuple)):
        raise TypeError(f"{name} requires a list or tuple")
    return tuple(value)


def _granular_token(value, name):
    if not isinstance(value, str) or not value.strip() or "\0" in value:
        raise ValueError(f"{name} requires a nonempty literal string without NUL")
    return value


def _granular_number(value):
    if type(value) not in (int, float, Decimal):
        raise TypeError("granular numeric values require int, float or Decimal, excluding bool")
    number = Decimal(str(value))
    if not number.is_finite():
        raise ValueError("granular numeric values must be finite")
    return number


def _granular_decimal_string(value):
    number = _granular_number(value)
    sign, digits, exponent = number.as_tuple()
    if not any(digits):
        return "0"
    digits = list(digits)
    while digits[-1] == 0:
        digits.pop()
        exponent += 1
    return ("-" if sign else "") + "".join(str(d) for d in digits) + "e" + str(exponent)


def _granular_family(value):
    _granular_token(value, "previous family")
    if value != "NONE":
        _granular_PrecedingContextFilter(previous_direction=value.split("/")[0], previous_family=value)


def _granular_schema(value, expected, name):
    if not isinstance(value, _granular_Mapping) or set(value) != set(expected):
        raise ValueError(f"{name} requires exactly the defined keys")


def _granular_parse_bound(value):
    if isinstance(value, str):
        if _granular_re.fullmatch(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?", value) is None:
            raise ValueError("invalid decimal bound syntax")
        with _granular_localcontext():
            value = Decimal(value)
    return value


@dataclass(frozen=True, slots=True)
class GranularPredicate:
    domain: str
    field: str
    unit: str
    basis: str | None = None
    cohort: str | None = None
    statistic: str | None = None
    column: str | None = None
    profile_id: str | None = None
    offset: int | None = None
    minimum: int | float | Decimal | None = None
    maximum: int | float | Decimal | None = None
    lower_inclusive: bool = True
    upper_inclusive: bool = True
    allowed: tuple[bool | str, ...] = ()
    enabled: bool = True
    horizon_bars: int | None = None

    def __post_init__(self):
        for name in ("domain", "field", "unit"):
            _granular_token(getattr(self, name), name)
        if any(type(getattr(self, name)) is not bool for name in ("enabled", "lower_inclusive", "upper_inclusive")):
            raise TypeError("enabled and inclusivity flags require actual bool values")
        allowed = _granular_sequence(self.allowed, "allowed")
        if self.domain != "horizon" and self.horizon_bars is not None:
            raise ValueError("only horizon predicates accept horizon_bars")
        numeric = self.domain in ("movement", "duration", "pullbacks", "horizon") or (self.domain == "column" and self.field == "raw_value")
        if self.domain in ("movement", "duration", "pullbacks"):
            if self.basis not in _granular_BASES or any(v is not None for v in (self.column, self.profile_id, self.offset)):
                raise ValueError("UTC predicates require a measurement basis and no column selectors")
            if self.domain == "pullbacks":
                if self.cohort not in _granular_COHORTS or self.field not in ("count", "depth", "recovered_duration"):
                    raise ValueError("unsupported pullback field or cohort")
            elif self.cohort is not None or self.field not in (_granular_MOVEMENT_FIELDS if self.domain == "movement" else _granular_DURATION_FIELDS):
                raise ValueError("unsupported field or cohort for the UTC domain")
            condition = _granular_NumericCondition(self.field, self.unit, self.minimum, self.maximum, self.statistic)
            for name in ("unit", "minimum", "maximum"):
                object.__setattr__(self, name, getattr(condition, name))
        elif self.domain == "horizon":
            if (self.field not in ("terminal_signed", "terminal_directional", "favorable_excursion", "adverse_excursion")
                    or self.unit not in ("points", "pct") or type(self.horizon_bars) is not int
                    or not 1 <= self.horizon_bars <= 1000):
                raise ValueError("horizon requires a supported field, points/pct and integer N from 1 through 1000")
            if any(v is not None for v in (self.basis, self.cohort, self.statistic, self.column, self.profile_id, self.offset)):
                raise ValueError("horizon uses stored event close without UTC or column selectors")
            for name in ("minimum", "maximum"):
                if getattr(self, name) is not None:
                    object.__setattr__(self, name, _granular_number(getattr(self, name)))
        elif self.domain == "context":
            if any(v is not None for v in (self.basis, self.cohort, self.statistic, self.column, self.profile_id, self.offset)):
                raise ValueError("context predicates cannot carry measurement selectors")
            if self.field in ("up", "down", "range"):
                if self.unit != "boolean" or len(allowed) > 1 or any(type(v) is not bool for v in allowed):
                    raise ValueError("context membership selects Any or one actual bool")
            elif self.field == "previous_direction":
                if self.unit != "category":
                    raise ValueError("previous direction requires category units")
                for value in allowed:
                    _granular_token(value, "previous direction")
                    _granular_PrecedingContextFilter(previous_direction=value)
            elif self.field == "previous_family":
                if self.unit != "category":
                    raise ValueError("previous family requires category units")
                for value in allowed:
                    _granular_family(value)
            else:
                raise ValueError("unsupported context field")
        elif self.domain == "column":
            if any(v is not None for v in (self.basis, self.cohort, self.statistic)):
                raise ValueError("column predicates cannot carry UTC selectors")
            _granular_token(self.column, "column")
            if self.profile_id is not None:
                _granular_token(self.profile_id, "profile ID")
            if type(self.offset) is not int or not -199 <= self.offset <= -1:
                raise ValueError("column offsets must be integers from -199 through -1")
            if self.field == "raw_value" and self.unit == "native":
                for name in ("minimum", "maximum"):
                    if getattr(self, name) is not None:
                        object.__setattr__(self, name, _granular_number(getattr(self, name)))
            elif self.field == "label" and self.unit == "label" and self.profile_id is not None:
                for value in allowed:
                    _granular_token(value, "label")
            else:
                raise ValueError("unsupported column measure or missing label profile")
        else:
            raise ValueError("unsupported granular predicate domain")
        if numeric:
            if allowed:
                raise ValueError("numeric predicates do not accept allowed members")
            if self.minimum is not None and self.maximum is not None:
                if self.minimum > self.maximum or (self.minimum == self.maximum and not (self.lower_inclusive and self.upper_inclusive)):
                    raise ValueError("reversed or empty numeric interval")
        elif self.minimum is not None or self.maximum is not None or not (self.lower_inclusive and self.upper_inclusive):
            raise ValueError("categorical predicates require absent bounds and inclusive flags")
        if len(allowed) != len(set(allowed)):
            raise ValueError("duplicate allowed members")
        object.__setattr__(self, "allowed", tuple(sorted(allowed)))

    @property
    def active(self):
        return self.enabled and (self.minimum is not None or self.maximum is not None or bool(self.allowed))

    @property
    def measurement_key(self):
        selectors = {name: getattr(self, name) for name in
            ("domain", "field", "unit", "basis", "cohort", "statistic", "column", "profile_id", "offset")}
        if self.domain == "horizon":
            selectors["horizon_bars"] = self.horizon_bars
            return _granular_hash(("gr04-measure-v1", selectors))
        return _granular_hash(("gr03-measure-v1", selectors))

    @property
    def predicate_key(self):
        payload = self.to_dict()
        payload.pop("enabled")
        return _granular_hash(("gr04-predicate-v1" if self.domain == "horizon" else "gr03-predicate-v1", payload))

    def to_dict(self):
        result = {f.name: getattr(self, f.name) for f in fields(self)
                  if f.name != "horizon_bars" or self.domain == "horizon"}
        result["allowed"] = list(self.allowed)
        for name in ("minimum", "maximum"):
            if result[name] is not None:
                result[name] = _granular_decimal_string(result[name])
        return result


@dataclass(frozen=True, slots=True)
class GranularGroup:
    operator: str = "ALL"
    conditions: tuple[GranularPredicate, ...] = ()
    enabled: bool = True

    def __post_init__(self):
        if type(self.enabled) is not bool or self.operator not in ("ALL", "ANY"):
            raise ValueError("group requires ALL or ANY and a boolean enabled flag")
        conditions = _granular_sequence(self.conditions, "conditions")
        if len(conditions) > 32 or any(type(c) is not GranularPredicate for c in conditions):
            raise ValueError("group requires at most 32 predicate rows, without nested groups")
        keys = [c.predicate_key for c in conditions]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate predicate within group")
        object.__setattr__(self, "conditions", conditions)

    @property
    def active(self):
        return self.enabled and any(c.active for c in self.conditions)

    def to_dict(self):
        return {"operator": self.operator, "conditions": [c.to_dict() for c in self.conditions], "enabled": self.enabled}


@dataclass(frozen=True, slots=True)
class AnchorDateRange:
    start_ms: int
    end_ms: int

    def __post_init__(self):
        if any(type(v) is not int or not 0 <= v < 2**63 for v in (self.start_ms, self.end_ms)):
            raise ValueError("anchor dates require exact nonnegative int64 UTC milliseconds")
        if self.start_ms > self.end_ms:
            raise ValueError("anchor date start must not exceed end")

    def to_dict(self):
        return dict(kind="gr-date-anchor-range-v1", start_ms=self.start_ms, end_ms=self.end_ms)

    @classmethod
    def from_dict(cls, mapping):
        _granular_schema(mapping, ("kind", "start_ms", "end_ms"), "anchor range")
        if mapping["kind"] != "gr-date-anchor-range-v1":
            raise ValueError("unsupported anchor range kind")
        return cls(mapping["start_ms"], mapping["end_ms"])

    def contains(self, timestamp_ms):
        if type(timestamp_ms) is not int or not 0 <= timestamp_ms < 2**63:
            raise ValueError("anchor timestamp requires exact nonnegative int64 UTC milliseconds")
        return self.start_ms <= timestamp_ms <= self.end_ms


@dataclass(frozen=True, slots=True)
class GranularRefinement:
    common: tuple[GranularGroup, ...] = ()
    outcome: tuple[GranularGroup, ...] = ()
    family_scope: FamilyScope | None = None
    anchor_range: AnchorDateRange | None = None

    def __post_init__(self):
        if self.anchor_range is not None and type(self.anchor_range) is not AnchorDateRange:
            raise TypeError("granular refinement requires an exact AnchorDateRange or None")
        if self.family_scope is not None and type(self.family_scope) is not FamilyScope:
            raise TypeError("granular refinement requires an exact FamilyScope or None")
        for name in ("common", "outcome"):
            groups = _granular_sequence(getattr(self, name), name)
            if any(type(g) is not GranularGroup for g in groups):
                raise TypeError("refinement purposes require granular groups")
            object.__setattr__(self, name, groups)
        if len(self.common) + len(self.outcome) > 8 or self.active_count > 32:
            raise ValueError("refinement permits at most eight stored groups and 32 active occurrences")
        horizons = {p.horizon_bars for g in self.common + self.outcome if g.enabled
                    for p in g.conditions if p.active and p.domain == "horizon"}
        if len(horizons) > 8:
            raise ValueError("refinement permits at most eight distinct active horizons")
        for group in self.common + self.outcome:
            for predicate in group.conditions:
                if group.enabled and predicate.active and predicate.basis == "formation":
                    if predicate.domain == "duration" and predicate.field in ("endpoint_extension", "observed_elapsed"):
                        raise ValueError("frozen formation does not support this duration")
                    if predicate.domain == "pullbacks" and predicate.cohort not in _granular_COHORTS[:4]:
                        raise ValueError("cohort is unavailable for frozen formation")

    @property
    def active_count(self):
        return sum(c.active for group in self.common + self.outcome if group.enabled for c in group.conditions)

    @property
    def active(self):
        return self.active_count > 0

    @property
    def identity(self):
        return _granular_hash(self.to_dict())

    def to_dict(self):
        has_horizon = any(p.domain == "horizon" for g in self.common + self.outcome for p in g.conditions)
        result = {"kind": "gr04-filter-spec-v1" if has_horizon else "gr03-filter-spec-v1", "common": [g.to_dict() for g in self.common],
                "outcome": [g.to_dict() for g in self.outcome]}
        if self.family_scope is not None:
            result.update(kind="gr05-filter-spec-v1", family_scope=self.family_scope.to_dict())
        if self.anchor_range is not None:
            result.update(kind="gr-date-filter-spec-v1",
                family_scope=None if self.family_scope is None else self.family_scope.to_dict(),
                anchor_range=self.anchor_range.to_dict())
        return result

    @classmethod
    def from_dict(cls, mapping):
        dated = isinstance(mapping, _granular_Mapping) and mapping.get("kind") == "gr-date-filter-spec-v1"
        scoped = isinstance(mapping, _granular_Mapping) and mapping.get("kind") == "gr05-filter-spec-v1"
        keys = ("kind", "common", "outcome", "family_scope", "anchor_range") if dated else (
            ("kind", "common", "outcome", "family_scope") if scoped else ("kind", "common", "outcome"))
        _granular_schema(mapping, keys, "refinement")
        scope = FamilyScope.from_dict(mapping["family_scope"]) if scoped or dated and mapping["family_scope"] is not None else None
        anchor_range = AnchorDateRange.from_dict(mapping["anchor_range"]) if dated else None
        if mapping["kind"] not in ("gr03-filter-spec-v1", "gr04-filter-spec-v1", "gr05-filter-spec-v1", "gr-date-filter-spec-v1"):
            raise ValueError("unsupported granular definition kind")
        purposes = {}
        for purpose in ("common", "outcome"):
            groups = []
            for group in _granular_sequence(mapping[purpose], purpose):
                _granular_schema(group, ("operator", "conditions", "enabled"), "group")
                conditions = []
                for condition in _granular_sequence(group["conditions"], "conditions"):
                    horizon = isinstance(condition, _granular_Mapping) and condition.get("domain") == "horizon"
                    if horizon and mapping["kind"] not in ("gr04-filter-spec-v1", "gr05-filter-spec-v1", "gr-date-filter-spec-v1"):
                        raise ValueError("horizon requires gr04-filter-spec-v1")
                    _granular_schema(condition, (f.name for f in fields(GranularPredicate)
                        if f.name != "horizon_bars" or horizon), "predicate")
                    payload = dict(condition)
                    for name in ("minimum", "maximum"):
                        payload[name] = _granular_parse_bound(payload[name])
                    conditions.append(GranularPredicate(**payload))
                groups.append(GranularGroup(group["operator"], conditions, group["enabled"]))
            purposes[purpose] = groups
        result = cls(**purposes, family_scope=scope, anchor_range=anchor_range)
        if result.to_dict()["kind"] != mapping["kind"]:
            raise ValueError("definition kind disagrees with stored domains")
        return result


@dataclass(frozen=True, slots=True)
class ResolvedFilterValue:
    value: int | float | Decimal | bool | str | None = None
    unavailable_reason: str | None = None

    def __post_init__(self):
        if self.value is None:
            _granular_token(self.unavailable_reason, "unavailable reason")
        elif self.unavailable_reason is not None:
            raise ValueError("a resolved value cannot also be unavailable")
        elif type(self.value) is bool:
            pass
        elif isinstance(self.value, str):
            _granular_token(self.value, "categorical value")
        else:
            object.__setattr__(self, "value", _granular_number(self.value))

    @property
    def known(self):
        return self.value is not None


# Task 1080: consumers of the accepted granular values; no new persisted fields.
def _gr03_definition(data):
    if "_gr03_definition" not in data:
        return None
    value = data["_gr03_definition"]
    if type(value) is not GranularRefinement:
        raise TypeError("malformed retained granular definition")
    return value


def _gr03_population(data):
    if _gr03_definition(data) is None:
        raise ValueError("no granular population evidence is attached")
    report = data.get("_gr03_population")
    if not isinstance(report, dict) or report.get("kind") != "gr03-population-report-v1":
        raise ValueError("malformed retained granular population")
    return report


def _gr03_population_record(data, row_id):
    if type(row_id) is not str:
        raise TypeError("population row ID must be a string")
    report = _gr03_population(data)
    index = data.get("_gr03_population_index")
    if index is None:
        index = {r["row_id"]: r for r in report["records"]}
        data["_gr03_population_index"] = index
    return deepcopy(index[row_id])


def convert_legacy_refinement(refinement, *, comparison):
    from .pattern_models import PatternRefinement
    if type(refinement) is not PatternRefinement:
        raise TypeError("conversion requires an exact PatternRefinement")
    if comparison not in ("other_families", "other_outcomes", "non_start", "recurrence"):
        raise ValueError("unsupported comparison")
    if comparison == "other_outcomes" and (not refinement.measurements_active or refinement.basis != "completed"):
        raise ValueError("other_outcomes requires active completed-trend outcome filters")
    if comparison == "non_start" and refinement.preceding.active:
        raise ValueError("non_start does not support preceding-context restrictions")
    preceding = refinement.preceding
    context = tuple(GranularPredicate("context", name, "boolean" if name in ("up", "down", "range") else "category",
        allowed=() if getattr(preceding, name) is None else (getattr(preceding, name),))
        for name in ("up", "down", "range", "previous_direction", "previous_family"))
    groups = []
    for domain, conditions, enabled, cohort in (
        ("movement", refinement.movement, refinement.movement_enabled, None),
        ("duration", refinement.duration, refinement.duration_enabled, None),
        ("pullbacks", refinement.pullbacks.conditions, refinement.pullbacks.enabled, refinement.pullbacks.cohort)):
        groups.append(GranularGroup("ALL", tuple(GranularPredicate(domain, c.field, c.unit,
            basis=refinement.basis, cohort=cohort, statistic=c.statistic, minimum=c.minimum, maximum=c.maximum)
            for c in conditions), enabled))
    return GranularRefinement((GranularGroup("ALL", context, preceding.enabled),), tuple(groups), refinement.family_scope)


def summarize_granular_refinement(definition):
    if type(definition) is not GranularRefinement:
        raise TypeError("summary requires GranularRefinement")
    sections = []
    for purpose, empty in (("common", "unrestricted"), ("outcome", "no outcome definition")):
        groups = []
        for group in getattr(definition, purpose):
            if not group.active:
                continue
            rows = []
            for p in group.conditions:
                if not p.active:
                    continue
                selectors = "/".join(str(v) for v in (p.domain, p.field, p.basis, p.cohort, p.statistic) if v is not None)
                if p.domain == "horizon":
                    selectors += f" N={p.horizon_bars} reference=event_close"
                if p.column is not None:
                    selectors += f" {p.column}[{p.offset}] profile={p.profile_id}"
                bounds = []
                if p.minimum is not None:
                    bounds.append((">=" if p.lower_inclusive else ">") + str(p.minimum))
                if p.maximum is not None:
                    bounds.append(("<=" if p.upper_inclusive else "<") + str(p.maximum))
                value = " and ".join(bounds) if bounds else "in {" + ", ".join(map(str, p.allowed)) + "}"
                rows.append(f"{selectors} {value} {p.unit}")
            groups.append(group.operator + "(" + "; ".join(rows) + ")")
        sections.append(purpose + ": " + (" ALL ".join(groups) if groups else empty))
    if definition.family_scope is not None:
        sections.append(definition.family_scope.summary())
    if definition.anchor_range is not None:
        sections.append(f"Anchor timestamps: {definition.anchor_range.start_ms} through {definition.anchor_range.end_ms} UTC ms, inclusive")
    disabled = sum(not g.enabled or not c.enabled for g in definition.common + definition.outcome for c in g.conditions)
    return " | ".join(sections) + (f" | {disabled} disabled rows retained" if disabled else "")


# Task1084: recomputable, in-session explanation values.
@dataclass(frozen=True, slots=True)
class InspectionOptions:
    extra_metrics: tuple[GranularPredicate, ...] = ()

    def __post_init__(self):
        metrics = _granular_sequence(self.extra_metrics, "inspection metrics")
        if len(metrics) > 8:
            raise ValueError(f"inspection metrics requested={len(metrics)} allowed=8")
        keys = set()
        for p in metrics:
            if (type(p) is not GranularPredicate or not p.enabled or p.minimum is not None
                    or p.maximum is not None or p.allowed or not p.lower_inclusive or not p.upper_inclusive
                    or p.domain == "context" or (p.domain == "column" and p.field != "raw_value")):
                raise ValueError("inspection requires enabled, bounds-free numeric measurement descriptors")
            if p.measurement_key in keys:
                raise ValueError("duplicate inspection measurement")
            keys.add(p.measurement_key)
        object.__setattr__(self, "extra_metrics", metrics)

    @property
    def identity(self):
        return _granular_hash(("gr06-inspection-options-v1", [p.to_dict() for p in self.extra_metrics]))


@dataclass(frozen=True, slots=True)
class FilterOmission:
    kind: str
    purpose: str | None = None
    group_index: int | None = None
    condition_index: int | None = None

    def __post_init__(self):
        if self.kind == "condition":
            if self.purpose not in ("common", "outcome") or any(
                    type(v) is not int or v < 0 for v in (self.group_index, self.condition_index)):
                raise ValueError("condition omission requires an exact purpose/group/condition path")
        elif self.kind not in ("anchor_range", "family_scope") or any(
                v is not None for v in (self.purpose, self.group_index, self.condition_index)):
            raise ValueError("restriction omission requires a known kind without a condition path")

    @property
    def key(self):
        return self.kind if self.kind != "condition" else f"{self.purpose}/{self.group_index}/{self.condition_index}"


@dataclass(frozen=True, slots=True)
class CombinationInspection:
    payload: str = field(repr=False)
    report_id: str = field(init=False)

    def __post_init__(self):
        canonical, identity = self._prepare(self.payload, lambda: None)
        object.__setattr__(self, "payload", canonical)
        object.__setattr__(self, "report_id", identity)

    @classmethod
    def _build(cls, payload, checkpoint):
        checkpoint()
        canonical, identity = cls._prepare(payload, checkpoint)
        result = object.__new__(cls)
        object.__setattr__(result, "payload", canonical)
        object.__setattr__(result, "report_id", identity)
        checkpoint()
        return result

    @staticmethod
    def _prepare(payload, checkpoint):
        from .combination_explanations import _inspection_encode
        checkpoint()
        content = json.loads(payload)
        checkpoint()
        legacy = {"header", "tables", "records", "links"}
        if not isinstance(content, dict) or set(content) not in (legacy, legacy | {"window_store"}):
            raise ValueError("invalid combination inspection payload")
        if not isinstance(content["header"], dict) or not isinstance(content["records"], dict):
            raise ValueError("invalid report binding or records")
        domain = "gr06-inspection-v1"
        if "window_store" in content:
            CombinationInspection._validate_store(content, checkpoint)
            domain = "gr06-inspection-v2"
        canonical = _inspection_encode(content, checkpoint)
        checkpoint()
        identity = _granular_hash((domain, canonical))
        checkpoint()
        return canonical, identity

    @staticmethod
    def _validate_store(content, checkpoint):
        from hashlib import sha256
        store = content["window_store"]
        if (not isinstance(store, dict) or set(store) != {"schema", "sources"}
                or store["schema"] != "gr06-inspection-window-store-v1"
                or not isinstance(store["sources"], dict)):
            raise ValueError("invalid inspection window store schema")
        sources = store["sources"]
        for key, payload in sources.items():
            checkpoint()
            if type(key) is not str or type(payload) is not str or sha256(payload.encode("utf-8")).hexdigest() != key:
                raise ValueError("inspection snapshot digest mismatch")
            snapshot = json.loads(payload)
            checkpoint()
            if (not isinstance(snapshot, dict) or set(snapshot) !=
                    {"timestamps", "positions", "coverage", "breaks", "columns", "request"}):
                raise ValueError("invalid inspection snapshot content")
            for name in ("timestamps", "positions", "coverage", "breaks", "columns"):
                if type(snapshot[name]) is not list:
                    raise ValueError("invalid inspection snapshot arrays")
            timestamps = snapshot["timestamps"]
            for stamp in timestamps:
                checkpoint()
                if type(stamp) is not int:
                    raise ValueError("invalid inspection timestamp")
            if len(snapshot["coverage"]) != len(timestamps) or len(snapshot["breaks"]) != len(timestamps):
                raise ValueError("invalid inspection coverage length")
            for pair in snapshot["positions"]:
                checkpoint()
                if (type(pair) is not list or len(pair) != 2 or any(type(v) is not int for v in pair)
                        or not 0 <= pair[1] < len(timestamps) or timestamps[pair[1]] != pair[0]):
                    raise ValueError("invalid inspection position pair")
            names = set()
            for column in snapshot["columns"]:
                checkpoint()
                if (type(column) is not dict or set(column) !=
                        {"name", "profile_id", "measurement", "frame_columns", "frame_rows"}
                        or any(type(column[k]) is not str for k in ("name", "measurement"))
                        or (column["profile_id"] is not None and type(column["profile_id"]) is not str)
                        or column["name"] in names or type(column["frame_columns"]) is not list
                        or any(type(n) is not str for n in column["frame_columns"])
                        or len(set(column["frame_columns"])) != len(column["frame_columns"])
                        or type(column["frame_rows"]) is not list
                        or len(column["frame_rows"]) != len(timestamps)):
                    raise ValueError("invalid inspection snapshot column")
                names.add(column["name"])
                for row in column["frame_rows"]:
                    checkpoint()
                    if type(row) is not list or len(row) != len(column["frame_columns"]):
                        raise ValueError("invalid inspection snapshot row")
            request = snapshot["request"]
            if (type(request) is not dict or set(request) != {"before", "after", "pre_event"}
                    or any(type(request[k]) is not int or request[k] < 0 for k in ("before", "after"))):
                raise ValueError("invalid inspection snapshot request")
            pre = request["pre_event"]
            if pre is not None:
                if (type(pre) is not dict or set(pre) != {"offsets"} or type(pre["offsets"]) is not list
                        or not pre["offsets"] or any(type(i) is not int for i in pre["offsets"])):
                    raise ValueError("invalid inspection snapshot offsets")
        for records in content["records"].values():
            if type(records) is not dict:
                raise ValueError("invalid compact inspection records")
            for row_key, row in records.items():
                checkpoint()
                descriptor = row.get("event_window") if isinstance(row, dict) else None
                if (type(descriptor) is not dict or set(descriptor) !=
                        {"source_key", "event_id", "anchor_ts_ms", "view_kind"}
                        or type(descriptor["source_key"]) is not str or descriptor["source_key"] not in sources
                        or type(descriptor["event_id"]) is not str or type(descriptor["anchor_ts_ms"]) is not int
                        or descriptor["view_kind"] not in ("study", "evaluation")):
                    raise ValueError("invalid inspection window descriptor/reference")
        checkpoint()

    @staticmethod
    def _validate_window_bindings(content):
        # Defer semantic row/header checks until validation/publication, as in
        # legacy reports. A new digest cannot change a descriptor's owner/view.
        header = content["header"]
        source_id = header.get("source_discovery_id")
        expected_views = {}
        if source_id is not None and "checkpoint_id" in header:
            expected_views = dict(source="study",
                current="evaluation" if header.get("variant_evaluation_id") or header["checkpoint_id"] != source_id else "study",
                parent="study" if header.get("actual_parent_id") == source_id else "evaluation")
        if source_id is not None:
            provenance = header.get("source_provenance", {}).get("source", {})
            request, context = provenance.get("request", {}), provenance.get("context", {})
            if not request or "profiles" not in context or "mined_offsets" not in context:
                raise ValueError("inspection snapshot provenance binding missing")
            profiles = {name: (measurement, profile_id) for name, measurement, profile_id in context["profiles"]}
            for encoded in content["window_store"]["sources"].values():
                snapshot = json.loads(encoded)
                columns = snapshot["columns"]
                if ([c["name"] for c in columns] != request["columns"]
                        or {c["name"]:(c["measurement"],c["profile_id"]) for c in columns} != profiles):
                    raise ValueError("inspection snapshot column/profile binding mismatch")
                expected_request = dict(before=request["before"],after=request["after"],
                    pre_event=None if request["pre_event"] is None else dict(offsets=context["mined_offsets"]))
                if snapshot["request"] != expected_request:
                    raise ValueError("inspection snapshot request binding mismatch")
        for side, records in content["records"].items():
            for key, row in records.items():
                descriptor = row["event_window"]
                if descriptor["event_id"] != key or descriptor["anchor_ts_ms"] != row.get("anchor_ts_ms"):
                    raise ValueError("inspection window descriptor binding mismatch")
                if key.startswith("control:") and key != "control:"+str(descriptor["anchor_ts_ms"]):
                    raise ValueError("inspection ordinary anchor binding mismatch")
                if side in expected_views and descriptor["view_kind"] != expected_views[side]:
                    raise ValueError("inspection window view binding mismatch")

    def _checked_content(self):
        compact = self.report_id == _granular_hash(("gr06-inspection-v2", self.payload))
        if not compact and self.report_id != _granular_hash(("gr06-inspection-v1", self.payload)):
            raise ValueError("inspection report digest mismatch")
        content = json.loads(self.payload)
        if compact != ("window_store" in content):
            raise ValueError("inspection report digest domain mismatch")
        if compact:
            self._validate_window_bindings(content)
        return content

    def validate(self):
        self._checked_content()
        return self

    @property
    def header(self):
        return self._checked_content()["header"]

    @property
    def retained_bytes(self):
        self.validate()
        return len(self.payload.encode("utf-8"))

    def frame(self, name):
        table = self._checked_content()["tables"].get(name)
        if table is None:
            raise KeyError(f"unknown inspection table: {name}")
        return _table(pd.DataFrame(table["rows"], columns=table["columns"], dtype=object))

    def record(self, side, row_id):
        content = self._checked_content()
        records = content["records"]
        if side not in records or row_id not in records[side]:
            raise ValueError("unknown inspection side/row identity")
        record = records[side][row_id]
        if "window_store" in content:
            from types import SimpleNamespace
            from .trend_start_patterns import event_window
            from .combination_explanations import _canonical
            descriptor = record["event_window"]
            snapshot = json.loads(content["window_store"]["sources"][descriptor["source_key"]])
            columns = {c["name"]: dict(profile_id=c["profile_id"], measurement=c["measurement"],
                frame=pd.DataFrame(c["frame_rows"], columns=c["frame_columns"], dtype=object))
                for c in snapshot["columns"]}
            data = dict(timestamps=snapshot["timestamps"], positions=dict(snapshot["positions"]),
                coverage=snapshot["coverage"], breaks=snapshot["breaks"], columns=columns,
                events={descriptor["event_id"]: dict(anchor_ts_ms=descriptor["anchor_ts_ms"])})
            request = dict(snapshot["request"])
            if request["pre_event"] is not None:
                request["pre_event"] = SimpleNamespace(offsets=tuple(request["pre_event"]["offsets"]))
            window = event_window(data, SimpleNamespace(**request), descriptor["event_id"])
            if descriptor["view_kind"] == "evaluation":
                window = _table(window)
            record["event_window"] = _canonical(window)
        return record

    def ledger(self, selector, *, offset=0, limit=50):
        content = self._checked_content()
        if (not isinstance(selector, dict) or type(offset) is not int or offset < 0
                or type(limit) is not int or not 1 <= limit <= 50):
            raise ValueError("ledger requires finite selectors, nonnegative offset and page size 1 through 50")
        allowed = {"side", "cohort", "period", "family", "block", "match_class", "ready_only", "link",
                   "condition_path", "condition_status", "metric_key", "metric_status", "population_change"}
        if set(selector) - allowed:
            raise ValueError("unsupported ledger selector")
        side = selector.get("side", "current")
        if side not in content["records"]:
            raise ValueError("unknown ledger side")
        records = list(content["records"][side].values())
        total = len(records)
        for key, choices in (("cohort", ("target", "comparison", "excluded")),
                ("period", ("discovery", "later", "eligible_combined", "excluded", "all")),
                ("match_class", ("all", "assessable", "unassessable", "matched", "nonmatched", "exact", "tolerance")),
                ("metric_status", ("summarized", "known", "unavailable", "timing_withheld")),
                ("population_change", ("included", "excluded", "reassigned", "unchanged", "status_changed"))):
            if key in selector and selector[key] not in choices:
                raise ValueError(f"invalid {key} selector")
        if "ready_only" in selector and type(selector["ready_only"]) is not bool:
            raise ValueError("ready_only requires bool")
        if "block" in selector and (type(selector["block"]) is not int or selector["block"] not in range(4)):
            raise ValueError("block requires 0 through 3")
        if "family" in selector and selector["family"] not in content["header"]["families"] + ["ordinary"]:
            raise ValueError("unknown family selector")
        if "link" in selector:
            link = content["links"].get(selector["link"])
            if link is None or link["side"] != side:
                raise ValueError("unknown or wrong-side support link")
            ids = set(link["row_ids"])
            records = [r for r in records if r["row_id"] in ids]
        if "condition_status" in selector and "condition_path" not in selector:
            raise ValueError("condition status requires its occurrence path")
        if "metric_status" in selector and "metric_key" not in selector:
            raise ValueError("metric status requires its measurement key")
        if "condition_path" in selector and selector["condition_path"] not in content["header"]["condition_paths"].get(side, []):
            raise ValueError("unknown condition occurrence")
        if "metric_key" in selector and selector["metric_key"] not in content["header"]["metric_keys"].get(side, []):
            raise ValueError("unknown measurement selector")
        selected = []
        for row in records:
            if "cohort" in selector and row["cohort"] != selector["cohort"]: continue
            period = selector.get("period", "all")
            if period == "eligible_combined":
                if row["partition"] not in ("discovery", "later") or row["cohort"] not in ("target", "comparison"): continue
            elif period != "all" and row["partition"] != period: continue
            if "family" in selector and ("ordinary" if row["ordinary"] else row["family"]) != selector["family"]: continue
            if "block" in selector and row["block"] != selector["block"]: continue
            match = selector.get("match_class", "all")
            if match == "assessable" and not row["assessable"]: continue
            if match == "unassessable" and row["assessable"] is not False: continue
            if match == "matched" and not row["matched"]: continue
            if match == "nonmatched" and not (row["assessable"] and not row["matched"]): continue
            if match == "exact" and not row["exact_match"]: continue
            if match == "tolerance" and not row["added_by_tolerance"]: continue
            if selector.get("ready_only") and not row["ready_timing"]: continue
            if "population_change" in selector and row.get("population_change") != selector["population_change"]: continue
            if "condition_path" in selector:
                condition = row["conditions"].get(selector["condition_path"])
                if condition is None or ("condition_status" in selector and condition["status"] != selector["condition_status"]): continue
            if "metric_key" in selector:
                metric = row["metrics"].get(selector["metric_key"])
                if metric is None: continue
                status = selector.get("metric_status")
                if status == "known" and not metric["known"]: continue
                if status == "unavailable" and metric["known"]: continue
                if status == "timing_withheld" and not metric["timing_withheld"]: continue
                if status == "summarized" and not (metric["known"] and not metric["timing_withheld"]): continue
            selected.append(row)
        selected.sort(key=lambda r: (r["anchor_ts_ms"], r["ordinary"], r["row_id"]))
        columns = ("row_id", "anchor_ts_ms", "ordinary", "family", "cohort", "partition", "reason",
                   "assessable", "matched", "exact_match", "added_by_tolerance", "ready_timing", "terms", "metrics")
        frame = _table(pd.DataFrame(selected[offset:offset+limit], columns=columns, dtype=object))
        frame.attrs.update(side=side, selector=deepcopy(selector), offset=offset, page_size=limit,
                           visible=len(frame), support_set_total=len(selected), retained_total=total)
        return frame


@dataclass(frozen=True, slots=True)
class RefinementSensitivity:
    payload: str = field(repr=False)
    evaluations: tuple[tuple[str, PatternEvaluation], ...] = field(repr=False, compare=False)
    report_id: str = field(init=False)

    def __post_init__(self):
        content = json.loads(self.payload)
        if not isinstance(content, dict) or set(content) != {"header", "plan", "tables", "evaluation_digests"}:
            raise ValueError("invalid sensitivity report payload")
        evaluations = tuple(self.evaluations)
        if len(evaluations) > 8 or len({k for k, _ in evaluations}) != len(evaluations):
            raise ValueError("invalid sensitivity variant count/identities")
        if set(content["evaluation_digests"]) != {k for k, _ in evaluations}:
            raise ValueError("sensitivity result membership differs from payload")
        canonical = _json(content)
        object.__setattr__(self, "payload", canonical)
        object.__setattr__(self, "evaluations", evaluations)
        object.__setattr__(self, "report_id", _granular_hash(("gr06-sensitivity-v1", canonical)))

    def validate(self):
        from .combination_explanations import _evaluation_digest
        if self.report_id != _granular_hash(("gr06-sensitivity-v1", self.payload)):
            raise ValueError("sensitivity report digest mismatch")
        digests = json.loads(self.payload)["evaluation_digests"]
        for key, evaluation in self.evaluations:
            if _evaluation_digest(evaluation) != digests[key]:
                raise ValueError("sensitivity transient evaluation was changed")
        return self

    @property
    def header(self):
        self.validate()
        return json.loads(self.payload)["header"]

    @property
    def plan(self):
        self.validate()
        return tuple(json.loads(self.payload)["plan"])

    @property
    def retained_bytes(self):
        from .pattern_refinement import _gr03_charge
        self.validate()
        populations = {id(e._data["_gr03_population"]): e._data["_gr03_population"] for _, e in self.evaluations}
        return (len(self.payload.encode("utf-8")) + sum(_gr03_charge(p) for p in populations.values())
                + sum(json.loads(e.context)["estimated_retained_match_state_bytes"] for _, e in self.evaluations))

    def variant(self, key):
        self.validate()
        for name, evaluation in self.evaluations:
            if name == key: return evaluation
        raise ValueError("variant is absent or was not evaluated")

    def frame(self, name):
        self.validate()
        content = json.loads(self.payload)
        if name == "plan": return _table(pd.DataFrame(content["plan"], dtype=object))
        table = content["tables"].get(name)
        if table is None: raise KeyError(f"unknown sensitivity table: {name}")
        return _table(pd.DataFrame(table["rows"], columns=table["columns"], dtype=object))
