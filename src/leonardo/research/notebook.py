"""Immutable version-1 Research Notebook models."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from leonardo.data import MarketId, canonicalize_market_id


_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_DIRECTIONS = frozenset({"long", "short"})
_TRADE_STATUSES = frozenset({"planned", "open", "closed", "cancelled"})
_TRADE_OUTCOMES = frozenset({"pending", "win", "loss", "breakeven"})
_ANNOTATION_KINDS = frozenset({"poi", "trade_long", "trade_short"})


class ResearchNotebookValidationError(ValueError):
    """Raised when a Research Notebook violates schema version 1."""


class ResearchNotebookNotFoundError(KeyError):
    """Raised when an exact Research Notebook does not exist."""


class ResearchNotebookAlreadyExistsError(FileExistsError):
    """Raised when a notebook identity or display name already exists."""


def _text(value: object, name: str, *, empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ResearchNotebookValidationError(f"{name} must be a string")
    if not empty and (not value or value != value.strip()):
        raise ResearchNotebookValidationError(
            f"{name} must be canonical non-empty text"
        )
    return value


def _identifier(value: object, name: str) -> str:
    value = _text(value, name)
    if _ID_RE.fullmatch(value) is None:
        raise ResearchNotebookValidationError(
            f"{name} is not a canonical identifier"
        )
    return value


def _integer(
    value: object,
    name: str,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    if type(value) is not int:
        raise ResearchNotebookValidationError(f"{name} must be an integer")
    if minimum is not None and value < minimum:
        raise ResearchNotebookValidationError(f"{name} is below minimum")
    if maximum is not None and value > maximum:
        raise ResearchNotebookValidationError(f"{name} is above maximum")
    return value


def _timestamp(value: object, name: str, *, optional: bool = False) -> int | None:
    if optional and value is None:
        return None
    return _integer(value, name, minimum=0)


def _price(value: object, name: str) -> float | None:
    if value is None:
        return None
    if type(value) not in (int, float):
        raise ResearchNotebookValidationError(f"{name} must be numeric or null")
    resolved = float(value)
    if not math.isfinite(resolved) or resolved <= 0:
        raise ResearchNotebookValidationError(
            f"{name} must be positive and finite"
        )
    return resolved


def _utc(value: object, name: str) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ResearchNotebookValidationError(f"{name} must be timezone-aware")
    if value.utcoffset().total_seconds() != 0:
        raise ResearchNotebookValidationError(f"{name} must be UTC")
    return value


def _parse_utc(value: object, name: str) -> datetime:
    text = _text(value, name)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ResearchNotebookValidationError(f"{name} is invalid") from exc
    return _utc(parsed, name)


def _market(value: object) -> MarketId:
    if not isinstance(value, MarketId):
        raise ResearchNotebookValidationError("market_id must be a MarketId")
    canonical = canonicalize_market_id(
        value.exchange,
        value.market_type,
        value.symbol,
        value.timeframe,
    )
    if canonical != value:
        raise ResearchNotebookValidationError("market_id must be canonical")
    return value


def _market_key(value: MarketId) -> tuple[str, str, str, str]:
    return value.exchange, value.market_type, value.symbol, value.timeframe


def _market_to_dict(value: MarketId) -> dict[str, str]:
    return {
        "exchange": value.exchange,
        "market_type": value.market_type,
        "symbol": value.symbol,
        "timeframe": value.timeframe,
    }


def _market_from_dict(value: object) -> MarketId:
    mapping = _mapping(value, "market_id")
    _require_keys(
        mapping,
        {"exchange", "market_type", "symbol", "timeframe"},
        "market_id",
    )
    try:
        market = MarketId(
            exchange=mapping["exchange"],
            market_type=mapping["market_type"],
            symbol=mapping["symbol"],
            timeframe=mapping["timeframe"],
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ResearchNotebookValidationError("market_id is invalid") from exc
    return _market(market)


def canonical_json_bytes(value: Mapping[str, object]) -> bytes:
    try:
        text = json.dumps(
            dict(value),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ResearchNotebookValidationError(
            "Research Notebook is not canonical JSON"
        ) from exc
    return (text + "\n").encode("utf-8")


def notebook_content_hash(value: Mapping[str, object]) -> str:
    payload = dict(value)
    payload.pop("content_hash", None)
    try:
        serialized = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ResearchNotebookValidationError(
            "Research Notebook content is not canonical JSON"
        ) from exc
    return hashlib.sha256(serialized).hexdigest()


@dataclass(frozen=True, slots=True)
class ResearchNotebookAnnotationSettingsV1:
    show_points_of_interest: bool = True
    show_potential_trades: bool = True
    poi_offset_px: int = -28
    long_offset_px: int = 56
    short_offset_px: int = -56

    def __post_init__(self) -> None:
        if (
            type(self.show_points_of_interest) is not bool
            or type(self.show_potential_trades) is not bool
        ):
            raise ResearchNotebookValidationError(
                "annotation visibility settings must be boolean"
            )
        for name in ("poi_offset_px", "long_offset_px", "short_offset_px"):
            _integer(getattr(self, name), name, minimum=-200, maximum=200)

    def to_dict(self) -> dict[str, object]:
        return {
            "show_points_of_interest": self.show_points_of_interest,
            "show_potential_trades": self.show_potential_trades,
            "poi_offset_px": self.poi_offset_px,
            "long_offset_px": self.long_offset_px,
            "short_offset_px": self.short_offset_px,
        }

    @classmethod
    def from_dict(
        cls, value: Mapping[str, object]
    ) -> "ResearchNotebookAnnotationSettingsV1":
        _require_keys(
            value,
            {
                "show_points_of_interest",
                "show_potential_trades",
                "poi_offset_px",
                "long_offset_px",
                "short_offset_px",
            },
            "annotation_settings",
        )
        return cls(**dict(value))


@dataclass(frozen=True, slots=True)
class ResearchNotebookNoteV1:
    row_id: str
    timestamp_ms: int | None
    text: str

    def __post_init__(self) -> None:
        _identifier(self.row_id, "row_id")
        _timestamp(self.timestamp_ms, "timestamp_ms", optional=True)
        _text(self.text, "text")

    def to_dict(self) -> dict[str, object]:
        return {
            "row_id": self.row_id,
            "timestamp_ms": self.timestamp_ms,
            "text": self.text,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "ResearchNotebookNoteV1":
        _require_keys(value, {"row_id", "timestamp_ms", "text"}, "note")
        return cls(**dict(value))


@dataclass(frozen=True, slots=True)
class ResearchNotebookPotentialTradeV1:
    row_id: str
    timestamp_ms: int
    direction: str
    entry_price: float | None
    target_price: float | None
    stop_price: float | None
    status: str
    outcome: str
    note: str

    def __post_init__(self) -> None:
        _identifier(self.row_id, "row_id")
        _timestamp(self.timestamp_ms, "timestamp_ms")
        if self.direction not in _DIRECTIONS:
            raise ResearchNotebookValidationError("trade direction is invalid")
        for name in ("entry_price", "target_price", "stop_price"):
            object.__setattr__(self, name, _price(getattr(self, name), name))
        if self.status not in _TRADE_STATUSES:
            raise ResearchNotebookValidationError("trade status is invalid")
        if self.outcome not in _TRADE_OUTCOMES:
            raise ResearchNotebookValidationError("trade outcome is invalid")
        _text(self.note, "note", empty=True)

    def to_dict(self) -> dict[str, object]:
        return {
            "row_id": self.row_id,
            "timestamp_ms": self.timestamp_ms,
            "direction": self.direction,
            "entry_price": self.entry_price,
            "target_price": self.target_price,
            "stop_price": self.stop_price,
            "status": self.status,
            "outcome": self.outcome,
            "note": self.note,
        }

    @classmethod
    def from_dict(
        cls, value: Mapping[str, object]
    ) -> "ResearchNotebookPotentialTradeV1":
        _require_keys(
            value,
            {
                "row_id",
                "timestamp_ms",
                "direction",
                "entry_price",
                "target_price",
                "stop_price",
                "status",
                "outcome",
                "note",
            },
            "potential_trade",
        )
        return cls(**dict(value))


@dataclass(frozen=True, slots=True)
class ResearchNotebookPointOfInterestV1:
    row_id: str
    timestamp_ms: int
    price: float | None
    title: str
    description: str

    def __post_init__(self) -> None:
        _identifier(self.row_id, "row_id")
        _timestamp(self.timestamp_ms, "timestamp_ms")
        object.__setattr__(self, "price", _price(self.price, "price"))
        _text(self.title, "title")
        _text(self.description, "description", empty=True)

    def to_dict(self) -> dict[str, object]:
        return {
            "row_id": self.row_id,
            "timestamp_ms": self.timestamp_ms,
            "price": self.price,
            "title": self.title,
            "description": self.description,
        }

    @classmethod
    def from_dict(
        cls, value: Mapping[str, object]
    ) -> "ResearchNotebookPointOfInterestV1":
        _require_keys(
            value,
            {"row_id", "timestamp_ms", "price", "title", "description"},
            "point_of_interest",
        )
        return cls(**dict(value))


@dataclass(frozen=True, slots=True)
class ResearchNotebookPageV1:
    market_id: MarketId
    notes: tuple[ResearchNotebookNoteV1, ...] = ()
    potential_trades: tuple[ResearchNotebookPotentialTradeV1, ...] = ()
    points_of_interest: tuple[ResearchNotebookPointOfInterestV1, ...] = ()

    def __post_init__(self) -> None:
        _market(self.market_id)
        notes = tuple(self.notes)
        trades = tuple(self.potential_trades)
        points = tuple(self.points_of_interest)
        if not all(isinstance(item, ResearchNotebookNoteV1) for item in notes):
            raise ResearchNotebookValidationError("notes are invalid")
        if not all(
            isinstance(item, ResearchNotebookPotentialTradeV1) for item in trades
        ):
            raise ResearchNotebookValidationError("potential trades are invalid")
        if not all(
            isinstance(item, ResearchNotebookPointOfInterestV1) for item in points
        ):
            raise ResearchNotebookValidationError("points of interest are invalid")
        canonical_notes = tuple(
            sorted(
                notes,
                key=lambda item: (
                    0 if item.timestamp_ms is None else 1,
                    -1 if item.timestamp_ms is None else item.timestamp_ms,
                    item.row_id,
                ),
            )
        )
        canonical_trades = tuple(
            sorted(trades, key=lambda item: (item.timestamp_ms, item.row_id))
        )
        canonical_points = tuple(
            sorted(points, key=lambda item: (item.timestamp_ms, item.row_id))
        )
        object.__setattr__(self, "notes", canonical_notes)
        object.__setattr__(self, "potential_trades", canonical_trades)
        object.__setattr__(self, "points_of_interest", canonical_points)

    def to_dict(self) -> dict[str, object]:
        return {
            "market_id": _market_to_dict(self.market_id),
            "notes": [item.to_dict() for item in self.notes],
            "potential_trades": [item.to_dict() for item in self.potential_trades],
            "points_of_interest": [
                item.to_dict() for item in self.points_of_interest
            ],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "ResearchNotebookPageV1":
        _require_keys(
            value,
            {"market_id", "notes", "potential_trades", "points_of_interest"},
            "page",
        )
        return cls(
            market_id=_market_from_dict(value["market_id"]),
            notes=tuple(
                ResearchNotebookNoteV1.from_dict(_mapping(item, "note"))
                for item in _sequence(value["notes"], "notes")
            ),
            potential_trades=tuple(
                ResearchNotebookPotentialTradeV1.from_dict(
                    _mapping(item, "potential_trade")
                )
                for item in _sequence(
                    value["potential_trades"], "potential_trades"
                )
            ),
            points_of_interest=tuple(
                ResearchNotebookPointOfInterestV1.from_dict(
                    _mapping(item, "point_of_interest")
                )
                for item in _sequence(
                    value["points_of_interest"], "points_of_interest"
                )
            ),
        )


@dataclass(frozen=True, slots=True)
class ResearchNotebookV1:
    notebook_id: str
    content_hash: str
    display_name: str
    description: str
    created_at_utc: datetime
    updated_at_utc: datetime
    annotation_settings: ResearchNotebookAnnotationSettingsV1
    pages: tuple[ResearchNotebookPageV1, ...]
    schema_version: str = "1.0"
    object_type: str = "research_notebook"

    def __post_init__(self) -> None:
        _identifier(self.notebook_id, "notebook_id")
        if _SHA_RE.fullmatch(_text(self.content_hash, "content_hash")) is None:
            raise ResearchNotebookValidationError(
                "content_hash must be lowercase SHA-256"
            )
        _text(self.display_name, "display_name")
        _text(self.description, "description", empty=True)
        created = _utc(self.created_at_utc, "created_at_utc")
        updated = _utc(self.updated_at_utc, "updated_at_utc")
        if updated < created:
            raise ResearchNotebookValidationError(
                "updated timestamp precedes creation"
            )
        if self.schema_version != "1.0" or self.object_type != "research_notebook":
            raise ResearchNotebookValidationError("unsupported notebook schema")
        if not isinstance(
            self.annotation_settings, ResearchNotebookAnnotationSettingsV1
        ):
            raise ResearchNotebookValidationError(
                "annotation_settings are invalid"
            )
        pages = tuple(self.pages)
        if len(pages) > 64 or not all(
            isinstance(item, ResearchNotebookPageV1) for item in pages
        ):
            raise ResearchNotebookValidationError("pages are invalid")
        pages = tuple(sorted(pages, key=lambda item: _market_key(item.market_id)))
        market_keys = tuple(_market_key(item.market_id) for item in pages)
        if len(set(market_keys)) != len(market_keys):
            raise ResearchNotebookValidationError("page MarketIds must be unique")
        row_ids = tuple(
            row.row_id
            for page in pages
            for row in (
                *page.notes,
                *page.potential_trades,
                *page.points_of_interest,
            )
        )
        if len(set(row_ids)) != len(row_ids):
            raise ResearchNotebookValidationError(
                "row IDs must be unique across the notebook"
            )
        object.__setattr__(self, "pages", pages)
        expected = notebook_content_hash(self.to_dict(include_content_hash=False))
        if self.content_hash != expected:
            raise ResearchNotebookValidationError(
                "content_hash does not match notebook payload"
            )

    @classmethod
    def build(
        cls,
        *,
        notebook_id: str,
        display_name: str,
        description: str,
        created_at_utc: datetime,
        updated_at_utc: datetime,
        annotation_settings: ResearchNotebookAnnotationSettingsV1,
        pages: Sequence[ResearchNotebookPageV1],
    ) -> "ResearchNotebookV1":
        canonical_pages = tuple(
            sorted(tuple(pages), key=lambda item: _market_key(item.market_id))
        )
        payload = {
            "schema_version": "1.0",
            "object_type": "research_notebook",
            "notebook_id": notebook_id,
            "display_name": display_name,
            "description": description,
            "created_at_utc": _utc(
                created_at_utc, "created_at_utc"
            ).isoformat(),
            "updated_at_utc": _utc(
                updated_at_utc, "updated_at_utc"
            ).isoformat(),
            "annotation_settings": annotation_settings.to_dict(),
            "pages": [item.to_dict() for item in canonical_pages],
        }
        return cls(
            notebook_id=notebook_id,
            content_hash=notebook_content_hash(payload),
            display_name=display_name,
            description=description,
            created_at_utc=created_at_utc,
            updated_at_utc=updated_at_utc,
            annotation_settings=annotation_settings,
            pages=canonical_pages,
        )

    def to_dict(self, *, include_content_hash: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "object_type": self.object_type,
            "notebook_id": self.notebook_id,
            "display_name": self.display_name,
            "description": self.description,
            "created_at_utc": self.created_at_utc.isoformat(),
            "updated_at_utc": self.updated_at_utc.isoformat(),
            "annotation_settings": self.annotation_settings.to_dict(),
            "pages": [item.to_dict() for item in self.pages],
        }
        if include_content_hash:
            payload["content_hash"] = self.content_hash
        return payload

    def canonical_json_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "ResearchNotebookV1":
        _require_keys(
            value,
            {
                "schema_version",
                "object_type",
                "notebook_id",
                "content_hash",
                "display_name",
                "description",
                "created_at_utc",
                "updated_at_utc",
                "annotation_settings",
                "pages",
            },
            "notebook",
        )
        return cls(
            schema_version=value["schema_version"],
            object_type=value["object_type"],
            notebook_id=value["notebook_id"],
            content_hash=value["content_hash"],
            display_name=value["display_name"],
            description=value["description"],
            created_at_utc=_parse_utc(value["created_at_utc"], "created_at_utc"),
            updated_at_utc=_parse_utc(value["updated_at_utc"], "updated_at_utc"),
            annotation_settings=ResearchNotebookAnnotationSettingsV1.from_dict(
                _mapping(value["annotation_settings"], "annotation_settings")
            ),
            pages=tuple(
                ResearchNotebookPageV1.from_dict(_mapping(item, "page"))
                for item in _sequence(value["pages"], "pages")
            ),
        )


@dataclass(frozen=True, slots=True)
class ResearchNotebookDraft:
    display_name: str
    description: str
    annotation_settings: ResearchNotebookAnnotationSettingsV1
    pages: tuple[ResearchNotebookPageV1, ...]
    notebook_id: str | None = None

    def __post_init__(self) -> None:
        _text(self.display_name, "display_name")
        _text(self.description, "description", empty=True)
        if not isinstance(
            self.annotation_settings, ResearchNotebookAnnotationSettingsV1
        ):
            raise ResearchNotebookValidationError(
                "annotation_settings are invalid"
            )
        pages = tuple(self.pages)
        if self.notebook_id is not None:
            _identifier(self.notebook_id, "notebook_id")
        probe = ResearchNotebookV1.build(
            notebook_id=self.notebook_id or "notebook_draft",
            display_name=self.display_name,
            description=self.description,
            created_at_utc=datetime.fromisoformat("2000-01-01T00:00:00+00:00"),
            updated_at_utc=datetime.fromisoformat("2000-01-01T00:00:00+00:00"),
            annotation_settings=self.annotation_settings,
            pages=pages,
        )
        object.__setattr__(self, "pages", probe.pages)


@dataclass(frozen=True, slots=True)
class ResearchNotebookSummary:
    notebook_id: str
    display_name: str
    description: str
    created_at_utc: datetime | None
    updated_at_utc: datetime | None
    page_count: int
    note_count: int
    potential_trade_count: int
    point_of_interest_count: int
    page_market_ids: tuple[MarketId, ...]
    valid: bool = True
    rejection_reason: str | None = None
    path: Path | None = None


@dataclass(frozen=True, slots=True)
class ResearchNotebookAnnotation:
    annotation_id: str
    notebook_id: str
    row_id: str
    market_id: MarketId
    kind: str
    timestamp_ms: int
    anchor_price: float | None
    label: str
    title: str
    tooltip: str
    offset_px: int

    def __post_init__(self) -> None:
        _text(self.annotation_id, "annotation_id")
        _identifier(self.notebook_id, "notebook_id")
        _identifier(self.row_id, "row_id")
        _market(self.market_id)
        if self.kind not in _ANNOTATION_KINDS:
            raise ResearchNotebookValidationError("annotation kind is invalid")
        _timestamp(self.timestamp_ms, "timestamp_ms")
        object.__setattr__(
            self, "anchor_price", _price(self.anchor_price, "anchor_price")
        )
        _text(self.label, "label")
        _text(self.title, "title")
        _text(self.tooltip, "tooltip")
        _integer(self.offset_px, "offset_px", minimum=-200, maximum=200)


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ResearchNotebookValidationError(f"{name} must be an object")
    return value


def _sequence(value: object, name: str) -> tuple[object, ...]:
    if not isinstance(value, Sequence) or isinstance(
        value, (str, bytes, bytearray)
    ):
        raise ResearchNotebookValidationError(f"{name} must be a sequence")
    return tuple(value)


def _require_keys(
    value: Mapping[str, object],
    expected: set[str],
    name: str,
) -> None:
    keys = set(value)
    if keys != expected:
        missing = ", ".join(sorted(expected - keys))
        extra = ", ".join(sorted(keys - expected))
        detail = "; ".join(
            part
            for part in (
                f"missing: {missing}" if missing else "",
                f"unexpected: {extra}" if extra else "",
            )
            if part
        )
        raise ResearchNotebookValidationError(f"{name} fields are invalid ({detail})")
