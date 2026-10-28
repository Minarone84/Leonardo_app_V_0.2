"""Disposable event-study inputs and detached views, never persisted schemas."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from decimal import Decimal
import json
import re

import pandas as pd

from .models import DatabaseReference

ORIGINS = ("initial_candidate", "candidate_restart", "post_break_restart", "direct_reversal", "unknown")
MEASUREMENT_BASES = ("completed", "formation", "observed")
MOVEMENT_FIELDS = ("directional_move", "signed_move", "pivot_favorable", "pivot_adverse", "pivot_span")
DURATION_FIELDS = ("structural", "endpoint_extension", "observed_elapsed", "confirmation_delay")
PULLBACK_COHORTS = ("all_observed", "internal_recovered", "formation_recovered",
    "formation_pending_at_boundary", "continuation_started", "recovered_during_continuation",
    "currently_pending", "pending_internal_launch", "endpoint_context", "ended_unrecovered", "interrupted")
_TIME_UNITS = {"ms": 1, "seconds": 1000, "minutes": 60_000, "hours": 3_600_000, "days": 86_400_000}


@dataclass(frozen=True, slots=True)
class NumericCondition:
    """Inclusive bounds; elapsed units are normalized exactly to milliseconds."""
    field: str
    unit: str
    minimum: int | float | Decimal | None = None
    maximum: int | float | Decimal | None = None
    statistic: str | None = None

    def __post_init__(self):
        if self.field in MOVEMENT_FIELDS:
            valid = self.unit in ("points", "pct") and self.statistic is None
        elif self.field in DURATION_FIELDS:
            valid = (self.unit in ("bars", *_TIME_UNITS) and self.statistic is None
                     and not (self.field == "confirmation_delay" and self.unit == "bars"))
        elif self.field == "count":
            valid = self.unit == "count" and self.statistic is None
        elif self.field == "depth":
            valid = self.unit in ("points", "pct") and self.statistic in ("mean", "maximum")
        elif self.field == "recovered_duration":
            valid = self.unit in ("bars", *_TIME_UNITS) and self.statistic in ("mean", "maximum")
        else:
            valid = False
        if not valid:
            raise ValueError("unsupported refinement field, unit or statistic")
        for name in ("minimum", "maximum"):
            value = getattr(self, name)
            if value is None:
                continue
            if type(value) not in (int, float, Decimal):
                raise ValueError("refinement bounds must be finite numbers, not booleans")
            value = Decimal(str(value))
            if not value.is_finite():
                raise ValueError("refinement bounds must be finite")
            if self.unit in _TIME_UNITS:
                numerator, denominator = value.as_integer_ratio()
                numerator *= _TIME_UNITS[self.unit]
                if numerator % denominator:
                    raise ValueError("elapsed bounds must have exact millisecond precision")
                value = numerator // denominator
            elif self.unit == "count" or (self.unit == "bars" and self.statistic != "mean"):
                if value != value.to_integral_value():
                    raise ValueError("counts and individual bar durations require integer bounds")
                value = int(value)
            object.__setattr__(self, name, value)
        if self.unit in _TIME_UNITS:
            object.__setattr__(self, "unit", "ms")
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError("refinement bounds are reversed")

    @property
    def active(self):
        return self.minimum is not None or self.maximum is not None

    def to_dict(self):
        return {k: str(v) if isinstance(v, Decimal) else v for k, v in asdict(self).items()}

    def summary(self):
        label = {"directional_move": "net directional movement", "signed_move": "signed endpoint movement",
            "pivot_favorable": "favorable pivot excursion", "pivot_adverse": "adverse pivot excursion",
            "pivot_span": "pivot price span", "structural": "structural duration",
            "endpoint_extension": "endpoint extension", "observed_elapsed": "observed elapsed duration",
            "confirmation_delay": "formation confirmation delay", "count": "pullback count",
            "depth": "pullback depth", "recovered_duration": "recovered pullback total duration"}[self.field]
        if self.statistic:
            label = self.statistic + " " + label
        bounds = (f"{self.minimum}–{self.maximum}" if self.minimum is not None and self.maximum is not None
                  else f"≥ {self.minimum}" if self.minimum is not None else f"≤ {self.maximum}")
        return f"{label} {bounds} { {'pct': '%', 'count': 'members'}.get(self.unit, self.unit)}"


@dataclass(frozen=True, slots=True)
class PrecedingContextFilter:
    enabled: bool = False
    up: bool | None = None
    down: bool | None = None
    range: bool | None = None
    previous_direction: str | None = None
    previous_family: str | None = None

    def __post_init__(self):
        if type(self.enabled) is not bool or any(v is not None and type(v) is not bool for v in (self.up, self.down, self.range)):
            raise ValueError("preceding memberships require Any, True or False")
        if self.previous_direction not in (None, "UP", "DOWN", "NONE"):
            raise ValueError("unsupported previous confirmed direction")
        if self.previous_family is not None:
            match = (re.fullmatch(r"(UP|DOWN)/([PT]+)/([0-9]+(?:,[0-9]+)*)", self.previous_family)
                     if isinstance(self.previous_family, str) else None)
            if (self.previous_direction not in ("UP", "DOWN") or not match
                    or match[1] != self.previous_direction or match[2][0] != {"UP": "T", "DOWN": "P"}[self.previous_direction]
                    or len(match[2]) != len(match[3].split(","))):
                raise ValueError("previous formation family requires its matching exact direction")

    @property
    def active(self):
        return self.enabled and (any(v is not None for v in (self.up, self.down, self.range))
                                 or self.previous_direction is not None or self.previous_family is not None)


def _conditions(values, fields):
    values = tuple(values)
    if any(not isinstance(v, NumericCondition) or v.field not in fields for v in values):
        raise ValueError("refinement condition belongs to a different group")
    keys = [(v.field, v.unit, v.statistic) for v in values]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate refinement conditions are not permitted")
    return values


@dataclass(frozen=True, slots=True)
class PullbackFilter:
    enabled: bool = False
    cohort: str = "internal_recovered"
    conditions: tuple[NumericCondition, ...] = ()

    def __post_init__(self):
        if type(self.enabled) is not bool or self.cohort not in PULLBACK_COHORTS:
            raise ValueError("unsupported pullback selection")
        object.__setattr__(self, "conditions", _conditions(self.conditions, ("count", "depth", "recovered_duration")))

    @property
    def active(self):
        return self.enabled and any(c.active for c in self.conditions)


@dataclass(frozen=True, slots=True)
class FamilyScope:
    mode: str
    families: tuple[str, ...] = ()

    def __post_init__(self):
        if type(self.mode) is not str or self.mode not in ("exact", "selected", "all"):
            raise ValueError("family scope requires exact, selected or all")
        if not isinstance(self.families, (list, tuple)):
            raise TypeError("family members require a list or tuple")
        members = tuple(self.families)
        directions = set()
        for member in members:
            match = re.fullmatch(r"(UP|DOWN)/([PT]+)/([0-9]+(?:,[0-9]+)*)", member) if type(member) is str else None
            if (not match or match[2][0] != {"UP": "T", "DOWN": "P"}[match[1]]
                    or len(match[2]) != len(match[3].split(","))):
                raise ValueError("family scope requires exact canonical P/T family keys")
            directions.add(match[1])
        if len(directions) > 1 or len(set(members)) != len(members):
            raise ValueError("family scope forbids duplicate or opposite-direction members")
        if ((self.mode == "exact" and len(members) != 1)
                or (self.mode == "selected" and not members) or (self.mode == "all" and members)):
            raise ValueError("exact requires one family; selected requires members; all stores no members")
        object.__setattr__(self, "families", tuple(sorted(members)))

    def to_dict(self):
        return {"kind": "gr05-family-selection-v1", "mode": self.mode, "families": list(self.families)}

    @classmethod
    def from_dict(cls, value):
        if (not isinstance(value, dict) or set(value) != {"kind", "mode", "families"}
                or value["kind"] != "gr05-family-selection-v1"):
            raise ValueError("family selection requires exactly kind, mode and families")
        return cls(value["mode"], value["families"])

    def summary(self):
        if self.mode == "all":
            return "All compatible same-direction families"
        return ("Exact family: " if self.mode == "exact" else f"Selected {len(self.families)} families: ") + ", ".join(self.families)


def _gr05_source_selection(source_request):
    scope = source_request.refinement.family_scope
    return scope if scope is not None else FamilyScope("exact", (source_request.family,)) if source_request.family is not None else None


def _gr05_resolve_selection(scope, *, source_selection, universe, direction, comparison):
    if any(s is not None and type(s) is not FamilyScope for s in (scope, source_selection)):
        raise TypeError("family selection requires an exact FamilyScope or None")
    effective = scope if scope is not None else source_selection
    if effective is None:
        return None
    if direction not in ("UP", "DOWN") or comparison not in ("other_families", "other_outcomes", "non_start", "recurrence"):
        raise ValueError("family context requires a supported fixed direction and comparison")
    if not isinstance(universe, (list, tuple)) or not universe:
        raise ValueError("family scope requires a nonempty source-compatible universe")
    members = FamilyScope("selected", universe).families
    if any(not f.startswith(direction + "/") for f in members + effective.families):
        raise ValueError("family scope disagrees with the fixed source direction")
    selected = members if effective.mode == "all" else effective.families
    if not set(selected) <= set(members):
        raise ValueError("selected family is unavailable in the original source universe")
    if comparison == "other_families" and (effective.mode == "all" or
            (effective.mode == "selected" and len(selected) > 1 and selected == members)):
        raise ValueError("No outside family remains: choose another comparison in a new initial discovery")
    return dict(kind="gr05-family-scope-v1", mode=effective.mode, selected_families=list(selected),
        compatible_families=list(members), comparison=comparison,
        comparison_families=[f for f in members if f not in selected] if comparison == "other_families" else
            list(selected) if comparison == "other_outcomes" else [])


def _gr05_resolve_scope(source_request, definition, universe):
    if source_request.pre_event is None:
        raise ValueError("family scope is supported only for Pre-event combinations")
    return _gr05_resolve_selection(definition.family_scope, source_selection=_gr05_source_selection(source_request),
        universe=universe, direction=source_request.trend_direction, comparison=source_request.comparison)


def _gr05_scope_enabled(source_request, definition):
    return (definition.family_scope is not None or source_request.refinement.family_scope is not None
            or source_request.comparison == "recurrence")


@dataclass(frozen=True, slots=True)
class PatternRefinement:
    basis: str = "completed"
    preceding: PrecedingContextFilter = field(default_factory=PrecedingContextFilter)
    movement_enabled: bool = False
    movement: tuple[NumericCondition, ...] = ()
    duration_enabled: bool = False
    duration: tuple[NumericCondition, ...] = ()
    pullbacks: PullbackFilter = field(default_factory=PullbackFilter)
    family_scope: FamilyScope | None = None

    def __post_init__(self):
        if self.family_scope is not None and type(self.family_scope) is not FamilyScope:
            raise TypeError("refinement requires an exact FamilyScope or None")
        if self.basis not in MEASUREMENT_BASES:
            raise ValueError("unsupported measurement basis")
        if not isinstance(self.preceding, PrecedingContextFilter) or not isinstance(self.pullbacks, PullbackFilter):
            raise TypeError("refinement requires validated context and pullback filters")
        if type(self.movement_enabled) is not bool or type(self.duration_enabled) is not bool:
            raise ValueError("refinement group switches must be boolean")
        object.__setattr__(self, "movement", _conditions(self.movement, MOVEMENT_FIELDS))
        object.__setattr__(self, "duration", _conditions(self.duration, DURATION_FIELDS))
        if self.basis == "formation":
            if self.duration_enabled and any(c.active and c.field in ("endpoint_extension", "observed_elapsed") for c in self.duration):
                raise ValueError("frozen formation does not support endpoint extension or observed elapsed duration")
            if self.pullbacks.active and self.pullbacks.cohort not in PULLBACK_COHORTS[:4]:
                raise ValueError("cohort is unavailable for frozen formation")

    @property
    def movement_active(self):
        return self.movement_enabled and any(c.active for c in self.movement)

    @property
    def duration_active(self):
        return self.duration_enabled and any(c.active for c in self.duration)

    @property
    def measurements_active(self):
        return self.movement_active or self.duration_active or self.pullbacks.active

    @property
    def active(self):
        return self.preceding.active or self.measurements_active

    def to_dict(self):
        result = {"basis": self.basis, "preceding": asdict(self.preceding),
            "movement_enabled": self.movement_enabled, "movement": [c.to_dict() for c in self.movement],
            "duration_enabled": self.duration_enabled, "duration": [c.to_dict() for c in self.duration],
            "pullbacks": {"enabled": self.pullbacks.enabled, "cohort": self.pullbacks.cohort,
                          "conditions": [c.to_dict() for c in self.pullbacks.conditions]}}
        if self.family_scope is not None:
            result["family_scope"] = self.family_scope.to_dict()
        return result

    def summary(self):
        parts = []
        if self.preceding.active:
            parts.extend(f"preceding {name}={value}" for name, value in
                         (("UP", self.preceding.up), ("DOWN", self.preceding.down), ("RANGE", self.preceding.range)) if value is not None)
            if self.preceding.previous_direction is not None:
                parts.append("no previous confirmed episode" if self.preceding.previous_direction == "NONE"
                             else "previous confirmed " + self.preceding.previous_direction)
            if self.preceding.previous_family is not None:
                parts.append(self.preceding.previous_family)
        if self.measurements_active:
            parts.append({"completed": "completed trend", "formation": "frozen formation", "observed": "observed progress"}[self.basis])
        if self.movement_active:
            parts.extend(c.summary() for c in self.movement if c.active)
        if self.duration_active:
            parts.extend(c.summary() for c in self.duration if c.active)
        if self.pullbacks.active:
            parts.append(self.pullbacks.cohort.replace("_", " "))
            parts.extend(c.summary() for c in self.pullbacks.conditions if c.active)
        if self.family_scope is not None:
            parts.append(self.family_scope.summary())
        return " · ".join(parts) if parts else "No enrichment refinements"


@dataclass(frozen=True, slots=True)
class PreEventSpec:
    """Disposable search settings. Offsets never include the starting bar."""
    history: int = 6
    lead: int = 1
    max_terms: int = 3
    tolerance: int = 0
    overrides: tuple[tuple[str, int], ...] = ()
    chronological: bool = False
    split_ms: int | None = None
    candidate_limit: int = 100_000
    memory_limit_bytes: int = 128 * 1024 * 1024

    def __post_init__(self):
        for name, low, high in (("history", 1, 100), ("lead", 1, 100), ("max_terms", 2, 4),
                                ("tolerance", 0, 1), ("candidate_limit", 1, 100_000),
                                ("memory_limit_bytes", 1, 128 * 1024 * 1024)):
            if type(getattr(self, name)) is not int or not low <= getattr(self, name) <= high:
                raise ValueError(f"{name} must be an integer from {low} to {high}")
        overrides = tuple(tuple(item) for item in self.overrides)
        if (any(len(item) != 2 or not isinstance(item[0], str) or not item[0]
                or type(item[1]) is not int or item[1] not in (0, 1) for item in overrides)
                or len({item[0] for item in overrides}) != len(overrides)):
            raise ValueError("tolerance overrides require unique columns and radius 0 or 1")
        object.__setattr__(self, "overrides", tuple(sorted(overrides)))
        if type(self.chronological) is not bool:
            raise ValueError("chronological selection must be boolean")
        if self.split_ms is not None and (type(self.split_ms) is not int or not 0 <= self.split_ms < 2**63):
            raise ValueError("split must be integer UTC milliseconds")
        if self.split_ms is not None and not self.chronological:
            raise ValueError("a split date requires chronological inspection")

    @property
    def offsets(self):
        return tuple(range(-(self.lead + self.history - 1), 1-self.lead))

    def radius(self, column):
        return dict(self.overrides).get(column, self.tolerance)

    def to_dict(self):
        return asdict(self)


@dataclass(frozen=True, slots=True)
class PatternRequest:
    reference: DatabaseReference
    run_key: str
    instance_id: str
    event_kind: str
    trend_direction: str
    columns: tuple[str, ...]
    start_ms: int
    end_ms: int
    family: str | None = None
    origin: str | None = None
    before: int = 20
    after: int = 20
    sequence_lengths: tuple[int, ...] = (2, 3)
    comparison: str = "other_families"
    min_target: int = 20
    min_comparison: int = 20
    min_matches: int = 5
    event_role: str = "trend_start"
    refinement: PatternRefinement = field(default_factory=PatternRefinement)
    pre_event: PreEventSpec | None = None

    def __post_init__(self):
        if not isinstance(self.reference, DatabaseReference):
            raise TypeError("study requires a pinned database reference")
        if not all(isinstance(v, str) and v for v in (self.run_key, self.instance_id)):
            raise ValueError("select a completed binning run and UTC instance")
        if (self.event_kind not in ("P", "T") or self.event_role != "trend_start"
                or self.trend_direction != {"P": "DOWN", "T": "UP"}[self.event_kind]):
            raise ValueError("event kind, trend-start role and direction disagree")
        if self.family is not None:
            match = re.fullmatch(r"(UP|DOWN)/([PT]+)/([0-9]+(?:,[0-9]+)*)", self.family)
            if (not match or match[1] != self.trend_direction or match[2][0] != self.event_kind
                    or len(match[2]) != len(match[3].split(","))):
                raise ValueError("trend family disagrees with the selected starting event")
        names = tuple(self.columns)
        if (not 1 <= len(names) <= 8 or len(set(names)) != len(names)
                or any(not isinstance(n, str) or not n for n in names)):
            raise ValueError("select 1 to 8 unique analyzed columns")
        object.__setattr__(self, "columns", names)
        if self.origin is not None and self.origin not in ORIGINS:
            raise ValueError("unsupported origin")
        if self.pre_event is not None and not isinstance(self.pre_event, PreEventSpec):
            raise TypeError("pre-event mode requires validated search settings")
        if self.comparison not in (("other_families", "other_outcomes", "non_start", "recurrence")
                                   if self.pre_event is not None else ("other_families", "non_start")):
            raise ValueError("unsupported comparison")
        if not isinstance(self.refinement, PatternRefinement):
            raise TypeError("study requires a validated refinement")
        if self.refinement.family_scope is not None:
            if self.pre_event is None:
                raise ValueError("family scope is supported only for Pre-event combinations")
            if any(not f.startswith(self.trend_direction + "/") for f in self.refinement.family_scope.families):
                raise ValueError("family scope disagrees with the selected starting event")
        if self.pre_event is None and self.refinement.active and self.comparison == "non_start":
            raise ValueError("Non-start timestamps requires all enrichment refinements to be disabled")
        if self.pre_event is not None:
            if any(name not in names for name, _ in self.pre_event.overrides):
                raise ValueError("tolerance overrides must refer to selected columns")
            if self.comparison == "non_start" and (self.origin is not None or self.refinement.preceding.active):
                raise ValueError("Ordinary timestamps requires All origins and no preceding-context restrictions")
            if self.comparison == "other_outcomes" and (not self.refinement.measurements_active or self.refinement.basis != "completed"):
                raise ValueError("Different outcomes requires completed-trend basis and an active numerical outcome condition")
        for name in ("start_ms", "end_ms"):
            value = getattr(self, name)
            if type(value) is not int or not 0 <= value < 2**63:
                raise ValueError("anchor date bounds must be integer milliseconds")
        if self.start_ms > self.end_ms:
            raise ValueError("anchor date bounds are reversed")
        if self.pre_event is not None and self.pre_event.split_ms is not None:
            if not self.start_ms < self.pre_event.split_ms <= self.end_ms:
                raise ValueError("chronological split must be inside the selected date interval")
        for name in ("before", "after"):
            if type(getattr(self, name)) is not int or not 0 <= getattr(self, name) <= 100:
                raise ValueError("event windows must be 0 to 100 stored bars")
        lengths = tuple(self.sequence_lengths)
        if (len(set(lengths)) != len(lengths)
                or any(type(n) is not int or not 1 <= n <= min(5, self.before + 1) for n in lengths)):
            raise ValueError("sequence lengths must be unique, 1 to 5, and fit the lookback")
        object.__setattr__(self, "sequence_lengths", tuple(sorted(lengths)))
        for name in ("min_target", "min_comparison", "min_matches"):
            if type(getattr(self, name)) is not int or getattr(self, name) < 1:
                raise ValueError("pattern support thresholds must be positive integers")

    @property
    def role_label(self):
        return "up_start" if self.event_kind == "T" else "down_start"

    @property
    def anchor_label(self):
        return self.event_kind + "0"


@dataclass(frozen=True, slots=True)
class PatternCatalogue:
    reference: DatabaseReference
    run_key: str
    _json: str = field(repr=False)
    _selection_json: str = field(init=False, repr=False, compare=False)

    def __post_init__(self):
        # Constructed on the existing catalogue worker. Family refresh decodes
        # only validated selection projections, never copied source reports.
        instances = []
        for instance in json.loads(self._json)["instances"]:
            events = []
            for event in instance["events"]:
                witnesses = [{"artifact_id": w["artifact_id"], "report_sha256": w["report_sha256"],
                    "episode": {"episode_id": w["episode"]["episode_id"]},
                    "metrics": True if w.get("metrics") is not None else None,
                    "measurement_projections": w.get("measurement_projections", {}),
                    "context_projections": w.get("context_projections", {})} for w in event["witnesses"]]
                events.append({**{k: v for k, v in event.items() if k != "witnesses"}, "witnesses": witnesses})
            instances.append({**{k: v for k, v in instance.items() if k not in ("events", "measurement_reports")}, "events": events})
        object.__setattr__(self, "_selection_json", json.dumps(instances, sort_keys=True, separators=(",", ":")))

    def to_dict(self):
        return json.loads(self._json)

    def instance(self, identity):
        instance = next((i for i in self.to_dict()["instances"] if i["instance_id"] == identity), None)
        if instance is None:
            raise ValueError("UTC instance is absent from this pinned catalogue")
        return instance

    def families(self, identity, event_kind, *, origin=None, start_ms=0, end_ms=2**63-1, refinement=None):
        from .trend_start_patterns import family_rows
        return family_rows(self.selection_instance(identity), event_kind, origin, start_ms, end_ms, refinement=refinement)

    def selection_instance(self, identity):
        """Detached precomputed selector facts, without full source reports."""
        instance = next((i for i in self.selection_instances() if i["instance_id"] == identity), None)
        if instance is None:
            raise ValueError("UTC instance is absent from this pinned catalogue")
        return instance

    def selection_instances(self):
        return json.loads(self._selection_json)


@dataclass(frozen=True, slots=True)
class PatternStudy:
    request: PatternRequest
    context: str
    _tables: tuple[tuple[str, pd.DataFrame], ...] = field(repr=False, compare=False)
    _data: object = field(repr=False, compare=False)

    def frame(self, name):
        if self.granular_definition is not None:
            from .refinement_models import _table
            return _table(next(frame for key, frame in self._tables if key == name))
        return next(frame for key, frame in self._tables if key == name).copy(deep=True)

    def event_window(self, event_id):
        from .trend_start_patterns import event_window
        if self.granular_definition is not None:
            self.population_record(event_id)
        return event_window(self._data, self.request, event_id)

    def evidence(self, event_id):
        from .trend_start_patterns import event_evidence
        if self.granular_definition is not None:
            record = self.population_record(event_id)
            return {**event_evidence(self._data, event_id), "granular_population_record": record}
        return event_evidence(self._data, event_id)

    def pattern_matches(self, pattern_id, cohort="target", **kwargs):
        from .trend_start_patterns import pattern_matches
        return pattern_matches(self._data, pattern_id, cohort, **kwargs)

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
