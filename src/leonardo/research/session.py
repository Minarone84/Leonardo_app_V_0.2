"""Chart-session state for accepted historical Research datasets.

This module owns the mutable state of one Research chart session.  It keeps
accepted full-dataset truth separate from disposable resident projections and
uses generation/request tokens to reject late asynchronous results.  It owns no
viewport mathematics, Qt widgets, persistence, Financial Tool calculations, or
Core task lifecycle.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass
from threading import RLock
from uuid import uuid4

from leonardo.data import MarketId, canonicalize_market_id
from leonardo.research.dataset import HistoricalDataset
from leonardo.research.resident import ResidentOHLCVSlice
from leonardo.research.studies import (
    ChartStudy,
    ChartStudyRegistry,
    PreparedStudy,
    StudyApplyAttempt,
    StudyDependencyError,
    StudyEditAttempt,
    StudySaveAttempt,
    StudySaveOutcome,
    StudyValidationError,
)
from leonardo.research.study_presentation import (
    StudyFillStyle,
    StudyLineStyle,
    StudyManagerEntry,
    StudyPresentation,
    StudyPresentationRegistry,
)


class ChartSessionDisposedError(RuntimeError):
    """Raised when new work is requested after a chart session is disposed."""


class ChartSessionStateError(RuntimeError):
    """Raised when an operation requires chart-session truth that is unavailable."""


@dataclass(frozen=True, slots=True)
class DatasetOpenAttempt:
    """Owner-local correlation token for one asynchronous dataset-open attempt."""

    session_id: str
    generation: int
    market_id: MarketId

    def __post_init__(self) -> None:
        if not isinstance(self.session_id, str) or not self.session_id:
            raise ValueError("session_id must be a non-empty string")
        if type(self.generation) is not int or self.generation <= 0:
            raise ValueError("generation must be a positive integer")
        _require_canonical_market(self.market_id)


@dataclass(frozen=True, slots=True)
class ResidentSliceAttempt:
    """Owner-local correlation token for one asynchronous resident-slice request."""

    session_id: str
    generation: int
    request_id: str
    market_id: MarketId
    dataset_fingerprint: str

    def __post_init__(self) -> None:
        if not isinstance(self.session_id, str) or not self.session_id:
            raise ValueError("session_id must be a non-empty string")
        if type(self.generation) is not int or self.generation <= 0:
            raise ValueError("generation must be a positive integer")
        if not isinstance(self.request_id, str) or not self.request_id:
            raise ValueError("request_id must be a non-empty string")
        _require_canonical_market(self.market_id)
        if not isinstance(self.dataset_fingerprint, str) or not self.dataset_fingerprint:
            raise ValueError("dataset_fingerprint must be a non-empty string")


class ChartSessionState:
    """Canonical mutable data state for one historical Research chart.

    The session retains shared references to immutable :class:`HistoricalDataset`
    and :class:`ResidentOHLCVSlice` values.  It does not duplicate full timelines,
    timestamp maps, or OHLCV arrays.  A new dataset-open generation supersedes all
    earlier dataset and slice attempts.  A new slice request supersedes the older
    slice request for the current generation.
    """

    def __init__(self, *, session_id: str | None = None) -> None:
        resolved_session_id = session_id or uuid4().hex
        if not isinstance(resolved_session_id, str) or not resolved_session_id.strip():
            raise ValueError("session_id must be a non-empty string")
        self._session_id = resolved_session_id.strip()
        self._generation = 0
        self._selected_market_id: MarketId | None = None
        self._dataset: HistoricalDataset | None = None
        self._resident: ResidentOHLCVSlice | None = None
        self._open_attempt: DatasetOpenAttempt | None = None
        self._slice_attempt: ResidentSliceAttempt | None = None
        self._studies = ChartStudyRegistry()
        self._presentations = StudyPresentationRegistry()
        self._study_apply_attempts: dict[str, StudyApplyAttempt] = {}
        self._study_edit_attempts: dict[str, StudyEditAttempt] = {}
        self._study_save_attempts: dict[str, StudySaveAttempt] = {}
        self._disposed = False
        self._lock = RLock()

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def generation(self) -> int:
        with self._lock:
            return self._generation

    @property
    def is_disposed(self) -> bool:
        with self._lock:
            return self._disposed

    @property
    def selected_market_id(self) -> MarketId | None:
        with self._lock:
            return self._selected_market_id

    @property
    def dataset(self) -> HistoricalDataset | None:
        with self._lock:
            return self._dataset

    @property
    def resident(self) -> ResidentOHLCVSlice | None:
        with self._lock:
            return self._resident

    @property
    def dataset_fingerprint(self) -> str | None:
        with self._lock:
            return None if self._dataset is None else self._dataset.file_sha256

    @property
    def dataset_open_pending(self) -> bool:
        with self._lock:
            return self._open_attempt is not None

    @property
    def resident_slice_pending(self) -> bool:
        with self._lock:
            return self._slice_attempt is not None

    @property
    def dataset_count(self) -> int:
        with self._lock:
            return 0 if self._dataset is None else self._dataset.row_count

    @property
    def resident_count(self) -> int:
        with self._lock:
            return 0 if self._resident is None else self._resident.row_count

    @property
    def study_registry(self) -> ChartStudyRegistry:
        return self._studies

    @property
    def studies(self) -> tuple[ChartStudy, ...]:
        with self._lock:
            return self._studies.snapshot()

    @property
    def study_count(self) -> int:
        with self._lock:
            return len(self._studies)

    def study_presentations(self) -> tuple[StudyPresentation, ...]:
        with self._lock:
            return self._presentations.snapshot()

    def study_manager_entries(self) -> tuple[StudyManagerEntry, ...]:
        with self._lock:
            return self._presentations.manager_entries(self._studies.snapshot())

    @property
    def study_apply_pending(self) -> int:
        with self._lock:
            return len(self._study_apply_attempts)

    @property
    def study_save_pending(self) -> int:
        with self._lock:
            return len(self._study_save_attempts)

    @property
    def study_edit_pending(self) -> int:
        with self._lock:
            return len(self._study_edit_attempts)

    def begin_dataset_open(self, market_id: MarketId) -> DatasetOpenAttempt:
        """Begin a new dataset generation and release all previous data truth."""

        market = _require_canonical_market(market_id)
        with self._lock:
            self._ensure_active_locked()
            self._generation += 1
            attempt = DatasetOpenAttempt(
                session_id=self._session_id,
                generation=self._generation,
                market_id=market,
            )
            self._selected_market_id = market
            self._dataset = None
            self._resident = None
            self._open_attempt = attempt
            self._slice_attempt = None
            self._studies.clear()
            self._presentations.clear()
            self._study_apply_attempts.clear()
            self._study_edit_attempts.clear()
            self._study_save_attempts.clear()
            return attempt

    def accept_dataset_open(
        self,
        attempt: DatasetOpenAttempt,
        dataset: HistoricalDataset,
    ) -> bool:
        """Publish a current accepted dataset; return ``False`` for a stale result."""

        _validate_open_attempt(attempt)
        if not isinstance(dataset, HistoricalDataset):
            raise TypeError("dataset must be a HistoricalDataset")
        with self._lock:
            self._require_attempt_session_locked(attempt.session_id)
            if self._disposed or attempt != self._open_attempt:
                return False
            if dataset.market_id != attempt.market_id:
                raise ValueError("dataset MarketId does not match the open attempt")
            if self._selected_market_id != attempt.market_id:
                return False
            self._dataset = dataset
            self._resident = None
            self._open_attempt = None
            self._slice_attempt = None
            return True

    def settle_dataset_open_failure(self, attempt: DatasetOpenAttempt) -> bool:
        """Settle the current open failure without accepting any dataset truth."""

        _validate_open_attempt(attempt)
        with self._lock:
            self._require_attempt_session_locked(attempt.session_id)
            if self._disposed or attempt != self._open_attempt:
                return False
            self._open_attempt = None
            self._dataset = None
            self._resident = None
            self._slice_attempt = None
            return True

    def begin_resident_slice_request(self) -> ResidentSliceAttempt:
        """Create the latest resident-slice request for the accepted dataset."""

        with self._lock:
            self._ensure_active_locked()
            dataset = self._require_dataset_locked()
            attempt = ResidentSliceAttempt(
                session_id=self._session_id,
                generation=self._generation,
                request_id=uuid4().hex,
                market_id=dataset.market_id,
                dataset_fingerprint=dataset.file_sha256,
            )
            self._slice_attempt = attempt
            return attempt

    def accept_resident_slice(
        self,
        attempt: ResidentSliceAttempt,
        resident: ResidentOHLCVSlice,
    ) -> bool:
        """Publish the current resident result; return ``False`` when it is stale."""

        _validate_slice_attempt(attempt)
        if not isinstance(resident, ResidentOHLCVSlice):
            raise TypeError("resident must be a ResidentOHLCVSlice")
        with self._lock:
            self._require_attempt_session_locked(attempt.session_id)
            if self._disposed or attempt != self._slice_attempt:
                return False
            dataset = self._require_dataset_locked()
            self._validate_current_slice_locked(attempt, resident, dataset)
            self._resident = resident
            self._slice_attempt = None
            self._studies.reproject(resident)
            return True

    def settle_resident_slice_failure(self, attempt: ResidentSliceAttempt) -> bool:
        """Settle the current resident request without replacing resident truth."""

        _validate_slice_attempt(attempt)
        with self._lock:
            self._require_attempt_session_locked(attempt.session_id)
            if self._disposed or attempt != self._slice_attempt:
                return False
            self._slice_attempt = None
            return True

    def exact_global_index_for_timestamp(self, timestamp_ms: int) -> int | None:
        if type(timestamp_ms) is not int:
            raise TypeError("timestamp_ms must be an integer")
        with self._lock:
            timestamps = self._require_dataset_locked().ts_ms
            position = bisect.bisect_left(timestamps, timestamp_ms)
            if position < len(timestamps) and timestamps[position] == timestamp_ms:
                return position
            return None

    def nearest_global_index_for_timestamp(self, timestamp_ms: int) -> int:
        """Return the nearest candle index, preferring the earlier candle on ties."""

        if type(timestamp_ms) is not int:
            raise TypeError("timestamp_ms must be an integer")
        with self._lock:
            timestamps = self._require_dataset_locked().ts_ms
            position = bisect.bisect_left(timestamps, timestamp_ms)
            if position <= 0:
                return 0
            if position >= len(timestamps):
                return len(timestamps) - 1
            previous = position - 1
            if abs(timestamps[previous] - timestamp_ms) <= abs(
                timestamps[position] - timestamp_ms
            ):
                return previous
            return position

    def timestamp_for_global_index(self, global_index: int) -> int | None:
        if type(global_index) is not int:
            raise TypeError("global_index must be an integer")
        with self._lock:
            timestamps = self._require_dataset_locked().ts_ms
            if 0 <= global_index < len(timestamps):
                return timestamps[global_index]
            return None

    def resident_index_for_global(self, global_index: int) -> int | None:
        if type(global_index) is not int:
            raise TypeError("global_index must be an integer")
        with self._lock:
            resident = self._require_resident_locked()
            if not resident.contains_global_index(global_index):
                return None
            return global_index - resident.base_index

    def global_index_for_resident(self, resident_index: int) -> int:
        if type(resident_index) is not int:
            raise TypeError("resident_index must be an integer")
        with self._lock:
            resident = self._require_resident_locked()
            if not 0 <= resident_index < resident.row_count:
                raise IndexError("resident_index is outside the resident slice")
            return resident.base_index + resident_index

    def begin_study_apply(self) -> StudyApplyAttempt:
        """Create one independently correlated Apply attempt for this generation."""

        with self._lock:
            self._ensure_active_locked()
            dataset = self._require_dataset_locked()
            attempt = StudyApplyAttempt(
                session_id=self._session_id,
                generation=self._generation,
                request_id=uuid4().hex,
                study_id=uuid4().hex,
                market_id=dataset.market_id,
                dataset_fingerprint=dataset.file_sha256,
            )
            self._study_apply_attempts[attempt.request_id] = attempt
            return attempt

    def accept_study_apply(
        self, attempt: StudyApplyAttempt, prepared: PreparedStudy
    ) -> bool:
        """Accept one current full Study and project it onto the latest resident."""

        if not isinstance(attempt, StudyApplyAttempt):
            raise TypeError("attempt must be a StudyApplyAttempt")
        if not isinstance(prepared, PreparedStudy):
            raise TypeError("prepared must be a PreparedStudy")
        with self._lock:
            self._require_attempt_session_locked(attempt.session_id)
            pending = self._study_apply_attempts.pop(attempt.request_id, None)
            if self._disposed or pending != attempt:
                return False
            dataset = self._dataset
            if (
                dataset is None
                or attempt.generation != self._generation
                or attempt.market_id != dataset.market_id
                or attempt.dataset_fingerprint != dataset.file_sha256
            ):
                return False
            study = prepared.study
            if (
                study.study_id != attempt.study_id
                or study.session_id != attempt.session_id
                or study.generation != attempt.generation
                or study.market_id != attempt.market_id
                or study.dataset_fingerprint != attempt.dataset_fingerprint
            ):
                raise StudyValidationError("prepared Study does not match its Apply attempt")
            if study.result.row_count != dataset.row_count:
                raise StudyValidationError(
                    "prepared Study row count does not match the active dataset"
                )
            study_timestamps = tuple(
                int(value) for value in study.result.to_frame()["ts_ms"]
            )
            if study_timestamps != dataset.ts_ms:
                raise StudyValidationError(
                    "prepared Study timeline does not match the active dataset"
                )
            for dependency in study.source_studies:
                try:
                    source = self._studies.get(dependency.study_id)
                except KeyError:
                    return False
                if (
                    source.session_id != self._session_id
                    or source.generation != self._generation
                    or source.market_id != dataset.market_id
                    or source.dataset_fingerprint != dataset.file_sha256
                    or dependency.output_name not in source.result.output_names
                ):
                    return False
                if source.result.row_count != dataset.row_count:
                    return False
                source_timestamps = tuple(
                    int(value) for value in source.result.to_frame()["ts_ms"]
                )
                if source_timestamps != dataset.ts_ms:
                    return False
            self._presentations.register(study)
            try:
                self._studies.register(study, resident=self._resident)
            except Exception:
                self._presentations.remove(study.study_id)
                raise
            return True

    def settle_study_apply_failure(self, attempt: StudyApplyAttempt) -> bool:
        if not isinstance(attempt, StudyApplyAttempt):
            raise TypeError("attempt must be a StudyApplyAttempt")
        with self._lock:
            self._require_attempt_session_locked(attempt.session_id)
            pending = self._study_apply_attempts.pop(attempt.request_id, None)
            return not self._disposed and pending == attempt

    def begin_study_save(self, study_id: str) -> StudySaveAttempt:
        """Create the sole pending Save attempt for one current Study."""

        if not isinstance(study_id, str) or not study_id.strip():
            raise ValueError("study_id must be a non-empty string")
        with self._lock:
            self._ensure_active_locked()
            dataset = self._require_dataset_locked()
            study = self._studies.get(study_id)
            if study_id in self._study_edit_attempts:
                raise ChartSessionStateError("an Edit is already pending for this Study")
            if study_id in self._study_save_attempts:
                raise ChartSessionStateError("a Save is already pending for this Study")
            attempt = StudySaveAttempt(
                session_id=self._session_id,
                generation=self._generation,
                request_id=uuid4().hex,
                study_id=study.study_id,
                market_id=dataset.market_id,
                dataset_fingerprint=dataset.file_sha256,
            )
            self._study_save_attempts[study_id] = attempt
            return attempt

    def accept_study_save(
        self, attempt: StudySaveAttempt, outcome: StudySaveOutcome
    ) -> bool:
        """Publish a durable link onto the same Study when the callback is current."""

        if not isinstance(attempt, StudySaveAttempt):
            raise TypeError("attempt must be a StudySaveAttempt")
        if not isinstance(outcome, StudySaveOutcome):
            raise TypeError("outcome must be a StudySaveOutcome")
        with self._lock:
            self._require_attempt_session_locked(attempt.session_id)
            pending = self._study_save_attempts.pop(attempt.study_id, None)
            if self._disposed or pending != attempt:
                return False
            dataset = self._dataset
            if (
                dataset is None
                or attempt.generation != self._generation
                or attempt.market_id != dataset.market_id
                or attempt.dataset_fingerprint != dataset.file_sha256
                or outcome.study_id != attempt.study_id
            ):
                return False
            try:
                study = self._studies.get(attempt.study_id)
            except KeyError:
                return False
            if (
                study.generation != attempt.generation
                or study.market_id != attempt.market_id
                or study.dataset_fingerprint != attempt.dataset_fingerprint
            ):
                return False
            self._studies.replace_saved_link(attempt.study_id, outcome.saved_link)
            return True

    def settle_study_save_failure(self, attempt: StudySaveAttempt) -> bool:
        if not isinstance(attempt, StudySaveAttempt):
            raise TypeError("attempt must be a StudySaveAttempt")
        with self._lock:
            self._require_attempt_session_locked(attempt.session_id)
            pending = self._study_save_attempts.pop(attempt.study_id, None)
            return not self._disposed and pending == attempt

    def begin_study_edit(self, study_id: str) -> StudyEditAttempt:
        if not isinstance(study_id, str) or not study_id.strip():
            raise ValueError("study_id must be a non-empty string")
        with self._lock:
            self._ensure_active_locked()
            dataset = self._require_dataset_locked()
            study = self._studies.get(study_id)
            if study_id in self._study_save_attempts:
                raise ChartSessionStateError("a Save is already pending for this Study")
            if study_id in self._study_edit_attempts:
                raise ChartSessionStateError("an Edit is already pending for this Study")
            blockers = tuple(
                candidate.study_id
                for candidate in self._studies.snapshot()
                if any(
                    dependency.study_id == study_id
                    for dependency in candidate.source_studies
                )
            )
            if blockers:
                raise StudyDependencyError(
                    f"Study {study_id} cannot be edited while required by: "
                    f"{', '.join(blockers)}",
                    blockers=blockers,
                )
            attempt = StudyEditAttempt(
                session_id=self._session_id,
                generation=self._generation,
                request_id=uuid4().hex,
                study_id=study.study_id,
                market_id=dataset.market_id,
                dataset_fingerprint=dataset.file_sha256,
            )
            self._study_edit_attempts[study_id] = attempt
            return attempt

    def accept_study_edit(
        self, attempt: StudyEditAttempt, prepared: PreparedStudy
    ) -> bool:
        if not isinstance(attempt, StudyEditAttempt):
            raise TypeError("attempt must be a StudyEditAttempt")
        if not isinstance(prepared, PreparedStudy):
            raise TypeError("prepared must be a PreparedStudy")
        with self._lock:
            self._require_attempt_session_locked(attempt.session_id)
            pending = self._study_edit_attempts.pop(attempt.study_id, None)
            if self._disposed or pending != attempt:
                return False
            dataset = self._dataset
            if (
                dataset is None
                or attempt.generation != self._generation
                or attempt.market_id != dataset.market_id
                or attempt.dataset_fingerprint != dataset.file_sha256
            ):
                return False
            try:
                current = self._studies.get(attempt.study_id)
            except KeyError:
                return False
            replacement = prepared.study
            if (
                replacement.study_id != attempt.study_id
                or replacement.session_id != attempt.session_id
                or replacement.generation != attempt.generation
                or replacement.market_id != attempt.market_id
                or replacement.dataset_fingerprint != attempt.dataset_fingerprint
            ):
                raise StudyValidationError(
                    "prepared Study does not match its Edit attempt"
                )
            if replacement.result.tool_key != current.result.tool_key:
                raise StudyValidationError(
                    "edited Study tool key must remain unchanged"
                )
            if replacement.display_name != current.display_name:
                raise StudyValidationError(
                    "edited Study display name must remain unchanged"
                )
            if replacement.user_metadata != current.user_metadata:
                raise StudyValidationError(
                    "edited Study user metadata must remain unchanged"
                )
            blockers = tuple(
                candidate.study_id
                for candidate in self._studies.snapshot()
                if any(
                    dependency.study_id == attempt.study_id
                    for dependency in candidate.source_studies
                )
            )
            if blockers:
                raise StudyDependencyError(
                    f"Study {attempt.study_id} cannot be edited while required by: "
                    f"{', '.join(blockers)}",
                    blockers=blockers,
                )
            if replacement.result.row_count != dataset.row_count:
                raise StudyValidationError(
                    "edited Study row count does not match the active dataset"
                )
            if tuple(
                int(value) for value in replacement.result.to_frame()["ts_ms"]
            ) != dataset.ts_ms:
                raise StudyValidationError(
                    "edited Study timeline does not match the active dataset"
                )
            if any(
                dependency.study_id == attempt.study_id
                for dependency in replacement.source_studies
            ):
                raise StudyValidationError("a Study may not depend on itself")
            for dependency in replacement.source_studies:
                try:
                    source = self._studies.get(dependency.study_id)
                except KeyError:
                    return False
                if (
                    source.session_id != self._session_id
                    or source.generation != self._generation
                    or source.market_id != dataset.market_id
                    or source.dataset_fingerprint != dataset.file_sha256
                    or dependency.output_name not in source.result.output_names
                    or source.result.row_count != dataset.row_count
                    or tuple(
                        int(value) for value in source.result.to_frame()["ts_ms"]
                    )
                    != dataset.ts_ms
                ):
                    return False
            projection = None
            if self._resident is not None:
                from leonardo.research.study_projection import project_study

                projection = project_study(replacement, self._resident)
            presentation = self._presentations.reconcile_for_edit(
                current, replacement
            )
            self._studies.replace_for_edit(
                attempt.study_id,
                replacement,
                projection=projection,
            )
            self._presentations.replace_for_edit(replacement, presentation)
            return True

    def settle_study_edit_failure(self, attempt: StudyEditAttempt) -> bool:
        if not isinstance(attempt, StudyEditAttempt):
            raise TypeError("attempt must be a StudyEditAttempt")
        with self._lock:
            self._require_attempt_session_locked(attempt.session_id)
            pending = self._study_edit_attempts.pop(attempt.study_id, None)
            return not self._disposed and pending == attempt

    def remove_study(self, study_id: str) -> ChartStudy:
        with self._lock:
            self._ensure_active_locked()
            removed = self._studies.remove(study_id)
            self._presentations.remove(study_id)
            self._study_edit_attempts.pop(study_id, None)
            self._study_save_attempts.pop(study_id, None)
            return removed

    def set_study_visibility(
        self, study_id: str, visible: bool
    ) -> StudyPresentation:
        with self._lock:
            self._ensure_active_locked()
            return self._presentations.set_visibility(
                self._studies.get(study_id), visible
            )

    def replace_study_line_style(
        self, study_id: str, output_name: str, style: StudyLineStyle
    ) -> StudyPresentation:
        with self._lock:
            self._ensure_active_locked()
            return self._presentations.replace_line_style(
                self._studies.get(study_id), output_name, style
            )

    def replace_study_fill_style(
        self, study_id: str, fill_id: str, style: StudyFillStyle
    ) -> StudyPresentation:
        with self._lock:
            self._ensure_active_locked()
            return self._presentations.replace_fill_style(
                self._studies.get(study_id), fill_id, style
            )

    def reset_study_presentation(self, study_id: str) -> StudyPresentation:
        with self._lock:
            self._ensure_active_locked()
            return self._presentations.reset(self._studies.get(study_id))

    def dispose(self) -> bool:
        """Seal the session, invalidate attempts, and release dataset references."""

        with self._lock:
            if self._disposed:
                return False
            self._disposed = True
            self._generation += 1
            self._selected_market_id = None
            self._dataset = None
            self._resident = None
            self._open_attempt = None
            self._slice_attempt = None
            self._studies.clear()
            self._presentations.clear()
            self._study_apply_attempts.clear()
            self._study_edit_attempts.clear()
            self._study_save_attempts.clear()
            return True

    def _validate_current_slice_locked(
        self,
        attempt: ResidentSliceAttempt,
        resident: ResidentOHLCVSlice,
        dataset: HistoricalDataset,
    ) -> None:
        if attempt.generation != self._generation:
            raise ValueError("resident attempt generation does not match the session")
        if attempt.market_id != dataset.market_id:
            raise ValueError("resident attempt MarketId does not match the active dataset")
        if attempt.dataset_fingerprint != dataset.file_sha256:
            raise ValueError("resident attempt fingerprint does not match the active dataset")
        if resident.market_id != dataset.market_id:
            raise ValueError("resident MarketId does not match the active dataset")
        if resident.dataset_fingerprint != dataset.file_sha256:
            raise ValueError("resident fingerprint does not match the active dataset")
        if resident.end_index_exclusive > dataset.row_count:
            raise ValueError("resident range exceeds the active dataset")
        start = resident.base_index
        end = resident.end_index_exclusive
        expected_columns = (
            dataset.ts_ms[start:end],
            dataset.open[start:end],
            dataset.high[start:end],
            dataset.low[start:end],
            dataset.close[start:end],
            dataset.volume[start:end],
        )
        resident_columns = (
            resident.ts_ms,
            resident.open,
            resident.high,
            resident.low,
            resident.close,
            resident.volume,
        )
        if resident_columns != expected_columns:
            raise ValueError("resident OHLCV values do not match the active dataset range")

    def _ensure_active_locked(self) -> None:
        if self._disposed:
            raise ChartSessionDisposedError("chart session is disposed")

    def _require_dataset_locked(self) -> HistoricalDataset:
        self._ensure_active_locked()
        if self._dataset is None:
            raise ChartSessionStateError("chart session has no accepted dataset")
        return self._dataset

    def _require_resident_locked(self) -> ResidentOHLCVSlice:
        self._ensure_active_locked()
        if self._resident is None:
            raise ChartSessionStateError("chart session has no resident slice")
        return self._resident

    def _require_attempt_session_locked(self, session_id: str) -> None:
        if session_id != self._session_id:
            raise ValueError("attempt belongs to a different chart session")


def _validate_open_attempt(attempt: DatasetOpenAttempt) -> None:
    if not isinstance(attempt, DatasetOpenAttempt):
        raise TypeError("attempt must be a DatasetOpenAttempt")


def _validate_slice_attempt(attempt: ResidentSliceAttempt) -> None:
    if not isinstance(attempt, ResidentSliceAttempt):
        raise TypeError("attempt must be a ResidentSliceAttempt")


def _require_canonical_market(market_id: MarketId) -> MarketId:
    if not isinstance(market_id, MarketId):
        raise TypeError("market_id must be a MarketId")
    canonical = canonicalize_market_id(
        market_id.exchange,
        market_id.market_type,
        market_id.symbol,
        market_id.timeframe,
    )
    if canonical != market_id:
        raise ValueError(f"market_id must already be canonical: {canonical!r}")
    return market_id
