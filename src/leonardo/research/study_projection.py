"""Resident-only projections derived from immutable full Study truth."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

from leonardo.data import MarketId
from leonardo.research.resident import ResidentOHLCVSlice
from leonardo.research.studies import ChartStudy, StudyValidationError


@dataclass(frozen=True, slots=True)
class ResidentStudyProjection:
    study_id: str
    market_id: MarketId
    dataset_fingerprint: str
    pane_role: str | None
    base_index: int
    end_index_exclusive: int
    ts_ms: tuple[int, ...]
    render_series: Mapping[str, tuple[object, ...]]
    style_driver_series: Mapping[str, tuple[object, ...]]

    def __post_init__(self) -> None:
        render = _freeze_series(self.render_series, "render_series")
        styles = _freeze_series(self.style_driver_series, "style_driver_series")
        size = self.end_index_exclusive - self.base_index
        if type(self.base_index) is not int or self.base_index < 0:
            raise StudyValidationError("base_index must be a non-negative integer")
        if type(self.end_index_exclusive) is not int or size <= 0:
            raise StudyValidationError("projection range must be non-empty")
        timestamps = tuple(self.ts_ms)
        if len(timestamps) != size:
            raise StudyValidationError("projection timestamps must match its range")
        if any(len(values) != size for values in (*render.values(), *styles.values())):
            raise StudyValidationError("projected series must match the resident range")
        object.__setattr__(self, "ts_ms", timestamps)
        object.__setattr__(self, "render_series", render)
        object.__setattr__(self, "style_driver_series", styles)


def _freeze_series(
    value: Mapping[str, Sequence[object]], field_name: str
) -> Mapping[str, tuple[object, ...]]:
    if not isinstance(value, Mapping):
        raise StudyValidationError(f"{field_name} must be a mapping")
    frozen: dict[str, tuple[object, ...]] = {}
    for name, values in value.items():
        if not isinstance(name, str) or not name:
            raise StudyValidationError(f"{field_name} names must be non-empty strings")
        if not isinstance(values, Sequence) or isinstance(values, (str, bytes, bytearray)):
            raise StudyValidationError(f"{field_name} values must be sequences")
        frozen[name] = tuple(values)
    return MappingProxyType(frozen)


def project_study(
    study: ChartStudy, resident: ResidentOHLCVSlice
) -> ResidentStudyProjection:
    """Slice one full Study result by exact resident global positions."""

    if not isinstance(study, ChartStudy):
        raise StudyValidationError("study must be a ChartStudy")
    if not isinstance(resident, ResidentOHLCVSlice):
        raise StudyValidationError("resident must be a ResidentOHLCVSlice")
    if resident.market_id != study.market_id:
        raise StudyValidationError("resident MarketId does not match Study")
    if resident.dataset_fingerprint != study.dataset_fingerprint:
        raise StudyValidationError("resident fingerprint does not match Study")
    if resident.end_index_exclusive > study.result.row_count:
        raise StudyValidationError("resident range exceeds Study result")
    start = resident.base_index
    end = resident.end_index_exclusive
    frame = study.result.to_frame()
    projected_timestamps = tuple(int(value) for value in frame["ts_ms"].iloc[start:end])
    if projected_timestamps != resident.ts_ms:
        raise StudyValidationError("Study timestamps do not match the resident timeline")
    render = {
        name: tuple(frame[name].iloc[start:end].tolist())
        for name in study.renderable_output_names
    }
    style_drivers = {
        name: tuple(frame[name].iloc[start:end].tolist())
        for name in study.style_driver_output_names
    }
    return ResidentStudyProjection(
        study_id=study.study_id,
        market_id=study.market_id,
        dataset_fingerprint=study.dataset_fingerprint,
        pane_role=study.pane_role,
        base_index=start,
        end_index_exclusive=end,
        ts_ms=projected_timestamps,
        render_series=render,
        style_driver_series=style_drivers,
    )


def project_studies(
    studies: Sequence[ChartStudy], resident: ResidentOHLCVSlice
) -> tuple[ResidentStudyProjection, ...]:
    return tuple(project_study(study, resident) for study in studies)
