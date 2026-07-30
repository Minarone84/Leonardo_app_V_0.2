"""Immutable version-1 Research Workspace Snapshot models."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from leonardo.data import MarketId, canonicalize_market_id
from leonardo.financial_tools import get_financial_tool_spec
from leonardo.research.dataset import HistoricalDataset
from leonardo.research.studies import ChartStudy
from leonardo.research.study_environment import EnvironmentV1
from leonardo.research.study_presentation import StudyPresentation


_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_MODES = frozenset({"scroll_4", "fit_8"})


class ResearchWorkspaceSnapshotValidationError(ValueError):
    """Raised when a workspace snapshot violates schema version 1."""


class ResearchWorkspaceSnapshotNotFoundError(KeyError):
    """Raised when an exact workspace snapshot does not exist."""


class ResearchWorkspaceSnapshotAlreadyExistsError(FileExistsError):
    """Raised when a snapshot identity or display name already exists."""


def _text(value: object, name: str, *, empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ResearchWorkspaceSnapshotValidationError(f"{name} must be a string")
    if not empty and (not value or value != value.strip()):
        raise ResearchWorkspaceSnapshotValidationError(
            f"{name} must be canonical non-empty text"
        )
    return value


def _identifier(value: object, name: str) -> str:
    value = _text(value, name)
    if _ID_RE.fullmatch(value) is None:
        raise ResearchWorkspaceSnapshotValidationError(
            f"{name} is not a canonical identifier"
        )
    return value


def _integer(value: object, name: str, *, minimum: int | None = None) -> int:
    if type(value) is not int:
        raise ResearchWorkspaceSnapshotValidationError(f"{name} must be an integer")
    if minimum is not None and value < minimum:
        raise ResearchWorkspaceSnapshotValidationError(f"{name} is below minimum")
    return value


def _utc(value: object, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ResearchWorkspaceSnapshotValidationError(f"{name} must be timezone-aware")
    if value.utcoffset().total_seconds() != 0:
        raise ResearchWorkspaceSnapshotValidationError(f"{name} must be UTC")
    return value


def _parse_utc(value: object, name: str) -> datetime:
    text = _text(value, name)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ResearchWorkspaceSnapshotValidationError(f"{name} is invalid") from exc
    return _utc(parsed, name)


def _market(value: object) -> MarketId:
    if not isinstance(value, MarketId):
        raise ResearchWorkspaceSnapshotValidationError("market_id must be a MarketId")
    canonical = canonicalize_market_id(
        value.exchange, value.market_type, value.symbol, value.timeframe
    )
    if canonical != value:
        raise ResearchWorkspaceSnapshotValidationError("market_id must be canonical")
    return value


def _market_to_dict(value: MarketId) -> dict[str, str]:
    return {
        "exchange": value.exchange,
        "market_type": value.market_type,
        "symbol": value.symbol,
        "timeframe": value.timeframe,
    }


def _market_from_dict(value: object) -> MarketId:
    if not isinstance(value, Mapping):
        raise ResearchWorkspaceSnapshotValidationError("market_id must be an object")
    _require_keys(value, {"exchange", "market_type", "symbol", "timeframe"}, "market_id")
    try:
        return MarketId(
            exchange=value["exchange"],
            market_type=value["market_type"],
            symbol=value["symbol"],
            timeframe=value["timeframe"],
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ResearchWorkspaceSnapshotValidationError("market_id is invalid") from exc


def canonical_json_bytes(value: Mapping[str, object]) -> bytes:
    try:
        text = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ResearchWorkspaceSnapshotValidationError(
            "workspace snapshot is not canonical JSON"
        ) from exc
    return (text + "\n").encode("utf-8")


def _content_hash(value: Mapping[str, object]) -> str:
    payload = dict(value)
    payload.pop("content_hash", None)
    serialized = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


@dataclass(frozen=True, slots=True)
class WorkspaceSnapshotViewportV1:
    center_timestamp_ms: int
    visible_count: int

    def __post_init__(self) -> None:
        _integer(self.center_timestamp_ms, "center_timestamp_ms")
        _integer(self.visible_count, "visible_count", minimum=1)

    def to_dict(self) -> dict[str, int]:
        return {
            "center_timestamp_ms": self.center_timestamp_ms,
            "visible_count": self.visible_count,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "WorkspaceSnapshotViewportV1":
        _require_keys(value, {"center_timestamp_ms", "visible_count"}, "viewport")
        return cls(**dict(value))


@dataclass(frozen=True, slots=True)
class WorkspaceSnapshotPriceScaleV1:
    autoscale_enabled: bool
    manual_low: float | None = None
    manual_high: float | None = None

    def __post_init__(self) -> None:
        if type(self.autoscale_enabled) is not bool:
            raise ResearchWorkspaceSnapshotValidationError("autoscale_enabled must be boolean")
        if self.autoscale_enabled:
            if self.manual_low is not None or self.manual_high is not None:
                raise ResearchWorkspaceSnapshotValidationError(
                    "autoscale price scale must not contain manual bounds"
                )
            return
        if type(self.manual_low) not in (int, float) or type(self.manual_high) not in (
            int,
            float,
        ):
            raise ResearchWorkspaceSnapshotValidationError(
                "manual price scale requires numeric bounds"
            )
        low, high = float(self.manual_low), float(self.manual_high)
        if not math.isfinite(low) or not math.isfinite(high) or low >= high:
            raise ResearchWorkspaceSnapshotValidationError("manual price bounds are invalid")
        object.__setattr__(self, "manual_low", low)
        object.__setattr__(self, "manual_high", high)

    def to_dict(self) -> dict[str, object]:
        return {
            "autoscale_enabled": self.autoscale_enabled,
            "manual_low": self.manual_low,
            "manual_high": self.manual_high,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "WorkspaceSnapshotPriceScaleV1":
        _require_keys(
            value,
            {"autoscale_enabled", "manual_low", "manual_high"},
            "price_scale",
        )
        return cls(**dict(value))


@dataclass(frozen=True, slots=True)
class WorkspaceSnapshotPaneSizeV1:
    pane_ref: str
    size: int

    def __post_init__(self) -> None:
        _text(self.pane_ref, "pane_ref")
        _integer(self.size, "pane size", minimum=1)

    def to_dict(self) -> dict[str, object]:
        return {"pane_ref": self.pane_ref, "size": self.size}

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "WorkspaceSnapshotPaneSizeV1":
        _require_keys(value, {"pane_ref", "size"}, "pane_size")
        return cls(**dict(value))


@dataclass(frozen=True, slots=True)
class WorkspaceSnapshotChartV1:
    chart_ref: str
    workspace_position: int
    detached: bool
    market_id: MarketId
    viewport: WorkspaceSnapshotViewportV1
    price_scale: WorkspaceSnapshotPriceScaleV1
    volume_visible: bool
    pane_sizes: tuple[WorkspaceSnapshotPaneSizeV1, ...]
    study_environment: EnvironmentV1 | None

    def __post_init__(self) -> None:
        _identifier(self.chart_ref, "chart_ref")
        if not 1 <= _integer(self.workspace_position, "workspace_position") <= 8:
            raise ResearchWorkspaceSnapshotValidationError("workspace_position must be 1..8")
        if type(self.detached) is not bool or type(self.volume_visible) is not bool:
            raise ResearchWorkspaceSnapshotValidationError("chart flags must be boolean")
        _market(self.market_id)
        if not isinstance(self.viewport, WorkspaceSnapshotViewportV1):
            raise ResearchWorkspaceSnapshotValidationError("viewport is invalid")
        if not isinstance(self.price_scale, WorkspaceSnapshotPriceScaleV1):
            raise ResearchWorkspaceSnapshotValidationError("price_scale is invalid")
        panes = tuple(self.pane_sizes)
        if not panes or not all(isinstance(item, WorkspaceSnapshotPaneSizeV1) for item in panes):
            raise ResearchWorkspaceSnapshotValidationError("pane_sizes are invalid")
        refs = tuple(item.pane_ref for item in panes)
        if len(set(refs)) != len(refs) or refs[0] != "price":
            raise ResearchWorkspaceSnapshotValidationError("pane refs must be unique and start with price")
        expected_prefix = ["price"]
        if len(refs) > 1 and refs[1] == "volume":
            expected_prefix.append("volume")
        if list(refs[: len(expected_prefix)]) != expected_prefix:
            raise ResearchWorkspaceSnapshotValidationError("pane refs are not in canonical order")
        study_refs = refs[len(expected_prefix) :]
        if any(not item.startswith("study:") for item in study_refs):
            raise ResearchWorkspaceSnapshotValidationError("unknown pane reference")
        environment = self.study_environment
        if environment is None:
            if study_refs:
                raise ResearchWorkspaceSnapshotValidationError("Study panes require an environment")
        else:
            if not isinstance(environment, EnvironmentV1):
                raise ResearchWorkspaceSnapshotValidationError("study_environment is invalid")
            entries = {entry.entry_id: entry for entry in environment.entries}
            for pane_ref in study_refs:
                entry_id = pane_ref.removeprefix("study:")
                entry = entries.get(entry_id)
                if (
                    entry is None
                    or get_financial_tool_spec(entry.tool_key).behavior.output_mode
                    != "oscillator-pane"
                ):
                    raise ResearchWorkspaceSnapshotValidationError(
                        "Study pane does not refer to an oscillator environment entry"
                    )
        object.__setattr__(self, "pane_sizes", panes)

    def to_dict(self) -> dict[str, object]:
        return {
            "chart_ref": self.chart_ref,
            "workspace_position": self.workspace_position,
            "detached": self.detached,
            "market_id": _market_to_dict(self.market_id),
            "viewport": self.viewport.to_dict(),
            "price_scale": self.price_scale.to_dict(),
            "volume_visible": self.volume_visible,
            "pane_sizes": [item.to_dict() for item in self.pane_sizes],
            "study_environment": None
            if self.study_environment is None
            else self.study_environment.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "WorkspaceSnapshotChartV1":
        _require_keys(
            value,
            {
                "chart_ref",
                "workspace_position",
                "detached",
                "market_id",
                "viewport",
                "price_scale",
                "volume_visible",
                "pane_sizes",
                "study_environment",
            },
            "chart",
        )
        data = dict(value)
        environment = data["study_environment"]
        return cls(
            chart_ref=data["chart_ref"],
            workspace_position=data["workspace_position"],
            detached=data["detached"],
            market_id=_market_from_dict(data["market_id"]),
            viewport=WorkspaceSnapshotViewportV1.from_dict(data["viewport"]),
            price_scale=WorkspaceSnapshotPriceScaleV1.from_dict(data["price_scale"]),
            volume_visible=data["volume_visible"],
            pane_sizes=tuple(
                WorkspaceSnapshotPaneSizeV1.from_dict(item)
                for item in _sequence(data["pane_sizes"], "pane_sizes")
            ),
            study_environment=None
            if environment is None
            else EnvironmentV1.from_dict(environment),
        )


@dataclass(frozen=True, slots=True)
class WorkspaceSnapshotStateV1:
    visualization_mode: str
    pan_anchor_enabled: bool
    active_chart_ref: str

    def __post_init__(self) -> None:
        if self.visualization_mode not in _MODES:
            raise ResearchWorkspaceSnapshotValidationError("visualization mode is invalid")
        if type(self.pan_anchor_enabled) is not bool:
            raise ResearchWorkspaceSnapshotValidationError("pan_anchor_enabled must be boolean")
        _identifier(self.active_chart_ref, "active_chart_ref")

    def to_dict(self) -> dict[str, object]:
        return {
            "visualization_mode": self.visualization_mode,
            "pan_anchor_enabled": self.pan_anchor_enabled,
            "active_chart_ref": self.active_chart_ref,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "WorkspaceSnapshotStateV1":
        _require_keys(
            value,
            {"visualization_mode", "pan_anchor_enabled", "active_chart_ref"},
            "workspace",
        )
        return cls(**dict(value))


@dataclass(frozen=True, slots=True)
class ResearchWorkspaceSnapshotV1:
    snapshot_id: str
    content_hash: str
    display_name: str
    description: str
    created_at_utc: datetime
    updated_at_utc: datetime
    workspace: WorkspaceSnapshotStateV1
    charts: tuple[WorkspaceSnapshotChartV1, ...]
    notebook_id: str | None = None
    schema_version: str = "1.1"
    object_type: str = "research_workspace_snapshot"

    def __post_init__(self) -> None:
        _identifier(self.snapshot_id, "snapshot_id")
        if _SHA_RE.fullmatch(_text(self.content_hash, "content_hash")) is None:
            raise ResearchWorkspaceSnapshotValidationError("content_hash must be lowercase SHA-256")
        _text(self.display_name, "display_name")
        _text(self.description, "description", empty=True)
        created = _utc(self.created_at_utc, "created_at_utc")
        updated = _utc(self.updated_at_utc, "updated_at_utc")
        if updated < created:
            raise ResearchWorkspaceSnapshotValidationError("updated timestamp precedes creation")
        if (
            self.schema_version not in {"1.0", "1.1"}
            or self.object_type != "research_workspace_snapshot"
        ):
            raise ResearchWorkspaceSnapshotValidationError("unsupported snapshot schema")
        if self.schema_version == "1.0":
            if self.notebook_id is not None:
                raise ResearchWorkspaceSnapshotValidationError(
                    "schema 1.0 snapshots cannot contain notebook_id"
                )
        elif self.notebook_id is not None:
            _identifier(self.notebook_id, "notebook_id")
        if not isinstance(self.workspace, WorkspaceSnapshotStateV1):
            raise ResearchWorkspaceSnapshotValidationError("workspace is invalid")
        charts = tuple(self.charts)
        if not 1 <= len(charts) <= 8:
            raise ResearchWorkspaceSnapshotValidationError("snapshot must contain one to eight charts")
        if not all(isinstance(item, WorkspaceSnapshotChartV1) for item in charts):
            raise ResearchWorkspaceSnapshotValidationError("charts are invalid")
        if tuple(sorted(charts, key=lambda item: item.workspace_position)) != charts:
            raise ResearchWorkspaceSnapshotValidationError("charts must be in workspace-position order")
        refs = tuple(item.chart_ref for item in charts)
        positions = tuple(item.workspace_position for item in charts)
        if len(set(refs)) != len(refs) or len(set(positions)) != len(positions):
            raise ResearchWorkspaceSnapshotValidationError("chart refs and positions must be unique")
        if self.workspace.active_chart_ref not in refs:
            raise ResearchWorkspaceSnapshotValidationError("active chart ref does not exist")
        object.__setattr__(self, "charts", charts)

    def to_dict(self) -> dict[str, object]:
        value = {
            "schema_version": self.schema_version,
            "object_type": self.object_type,
            "snapshot_id": self.snapshot_id,
            "content_hash": self.content_hash,
            "display_name": self.display_name,
            "description": self.description,
            "created_at_utc": self.created_at_utc.isoformat(),
            "updated_at_utc": self.updated_at_utc.isoformat(),
            "workspace": self.workspace.to_dict(),
            "charts": [item.to_dict() for item in self.charts],
        }
        if self.schema_version == "1.1":
            value["notebook_id"] = self.notebook_id
        return value

    def canonical_json_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    @classmethod
    def build(
        cls,
        *,
        snapshot_id: str,
        display_name: str,
        description: str,
        created_at_utc: datetime,
        updated_at_utc: datetime,
        workspace: WorkspaceSnapshotStateV1,
        charts: Sequence[WorkspaceSnapshotChartV1],
        notebook_id: str | None = None,
    ) -> "ResearchWorkspaceSnapshotV1":
        data = {
            "schema_version": "1.1",
            "object_type": "research_workspace_snapshot",
            "snapshot_id": snapshot_id,
            "display_name": display_name,
            "description": description,
            "created_at_utc": created_at_utc.isoformat(),
            "updated_at_utc": updated_at_utc.isoformat(),
            "workspace": workspace.to_dict(),
            "charts": [item.to_dict() for item in charts],
            "notebook_id": notebook_id,
        }
        return cls(content_hash=_content_hash(data), **{
            "snapshot_id": snapshot_id,
            "display_name": display_name,
            "description": description,
            "created_at_utc": created_at_utc,
            "updated_at_utc": updated_at_utc,
            "workspace": workspace,
            "charts": tuple(charts),
            "notebook_id": notebook_id,
        })

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "ResearchWorkspaceSnapshotV1":
        schema_version = value.get("schema_version")
        if schema_version == "1.0":
            expected_keys = {
                "schema_version",
                "object_type",
                "snapshot_id",
                "content_hash",
                "display_name",
                "description",
                "created_at_utc",
                "updated_at_utc",
                "workspace",
                "charts",
            }
        elif schema_version == "1.1":
            expected_keys = {
                "schema_version",
                "object_type",
                "snapshot_id",
                "content_hash",
                "display_name",
                "description",
                "created_at_utc",
                "updated_at_utc",
                "workspace",
                "charts",
                "notebook_id",
            }
        else:
            raise ResearchWorkspaceSnapshotValidationError(
                "unsupported snapshot schema"
            )
        _require_keys(
            value,
            expected_keys,
            "snapshot",
        )
        data = dict(value)
        expected_hash = _content_hash(data)
        if data.get("content_hash") != expected_hash:
            raise ResearchWorkspaceSnapshotValidationError("workspace snapshot content hash is invalid")
        return cls(
            snapshot_id=data["snapshot_id"],
            content_hash=data["content_hash"],
            display_name=data["display_name"],
            description=data["description"],
            created_at_utc=_parse_utc(data["created_at_utc"], "created_at_utc"),
            updated_at_utc=_parse_utc(data["updated_at_utc"], "updated_at_utc"),
            workspace=WorkspaceSnapshotStateV1.from_dict(data["workspace"]),
            charts=tuple(
                WorkspaceSnapshotChartV1.from_dict(item)
                for item in _sequence(data["charts"], "charts")
            ),
            notebook_id=(
                None if schema_version == "1.0" else data["notebook_id"]
            ),
            schema_version=data["schema_version"],
            object_type=data["object_type"],
        )


@dataclass(frozen=True, slots=True)
class ResearchWorkspaceSnapshotDraft:
    display_name: str
    description: str
    workspace: WorkspaceSnapshotStateV1
    charts: tuple[WorkspaceSnapshotChartV1, ...]
    snapshot_id: str | None = None

    def __post_init__(self) -> None:
        _text(self.display_name, "display_name")
        _text(self.description, "description", empty=True)
        if self.snapshot_id is not None:
            _identifier(self.snapshot_id, "snapshot_id")
        charts = tuple(self.charts)
        ResearchWorkspaceSnapshotV1.build(
            snapshot_id=self.snapshot_id or "snapshot_validation",
            display_name=self.display_name,
            description=self.description,
            created_at_utc=datetime.fromisoformat("2000-01-01T00:00:00+00:00"),
            updated_at_utc=datetime.fromisoformat("2000-01-01T00:00:00+00:00"),
            workspace=self.workspace,
            charts=charts,
        )
        object.__setattr__(self, "charts", charts)


@dataclass(frozen=True, slots=True)
class ResearchWorkspaceSnapshotSummary:
    snapshot_id: str
    display_name: str
    description: str
    chart_count: int
    created_at_utc: datetime | None
    updated_at_utc: datetime | None
    valid: bool = True
    rejection_reason: str = ""
    notebook_id: str | None = None


@dataclass(frozen=True, slots=True)
class WorkspaceSnapshotChartCompatibility:
    chart_ref: str
    workspace_position: int
    compatible: bool
    blockers: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ResearchWorkspaceSnapshotCompatibilityReport:
    snapshot_id: str
    mode: str
    compatible: bool
    charts: tuple[WorkspaceSnapshotChartCompatibility, ...]
    blockers: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    append_positions: tuple[tuple[str, int], ...] = ()


@dataclass(frozen=True, slots=True)
class WorkspaceSnapshotChartCapture:
    chart_ref: str
    workspace_position: int
    detached: bool
    market_id: MarketId
    dataset: HistoricalDataset
    studies: tuple[ChartStudy, ...]
    presentations: tuple[StudyPresentation, ...]
    viewport: WorkspaceSnapshotViewportV1
    price_scale: WorkspaceSnapshotPriceScaleV1
    volume_visible: bool
    pane_sizes: Mapping[str, int]


@dataclass(frozen=True, slots=True)
class WorkspaceSnapshotCapture:
    visualization_mode: str
    pan_anchor_enabled: bool
    active_chart_ref: str
    charts: tuple[WorkspaceSnapshotChartCapture, ...]


def _sequence(value: object, name: str) -> Sequence[Mapping[str, object]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ResearchWorkspaceSnapshotValidationError(f"{name} must be an array")
    if not all(isinstance(item, Mapping) for item in value):
        raise ResearchWorkspaceSnapshotValidationError(f"{name} entries must be objects")
    return value


def _require_keys(value: Mapping[str, object], expected: set[str], name: str) -> None:
    supplied = set(value)
    if supplied != expected:
        raise ResearchWorkspaceSnapshotValidationError(
            f"{name} fields do not match schema: expected {sorted(expected)}, got {sorted(supplied)}"
        )
