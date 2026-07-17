"""Pure scene planning for Research Notebook chart annotations."""

from __future__ import annotations

import math
from dataclasses import dataclass

from leonardo.data import MarketId
from leonardo.gui.chart.candlestick_scene import SceneRect
from leonardo.gui.chart.price_scale import PriceScaleSnapshot
from leonardo.research.notebook import ResearchNotebookAnnotation
from leonardo.research.resident import ResidentOHLCVSlice
from leonardo.research.viewport import ViewportSnapshot


_KIND_APPEARANCE = {
    "poi": ("circle", "#f0b429"),
    "trade_long": ("triangle_up", "#00aa78"),
    "trade_short": ("triangle_down", "#d24646"),
}
_STACK_DISTANCE_PX = 14.0
_GLYPH_SIZE_PX = 10.0


@dataclass(frozen=True, slots=True)
class ResearchChartAnnotationProjection:
    """One notebook annotation resolved to a canonical dataset index."""

    annotation: ResearchNotebookAnnotation
    global_index: int

    def __post_init__(self) -> None:
        if not isinstance(self.annotation, ResearchNotebookAnnotation):
            raise TypeError("annotation must be a ResearchNotebookAnnotation")
        if type(self.global_index) is not int or self.global_index < 0:
            raise ValueError("global_index must be a non-negative integer")

    def cache_identity(self) -> tuple[object, ...]:
        value = self.annotation
        return (
            value.annotation_id,
            value.notebook_id,
            value.row_id,
            value.market_id,
            value.kind,
            value.timestamp_ms,
            value.anchor_price,
            value.label,
            value.title,
            value.tooltip,
            value.offset_px,
            self.global_index,
        )


@dataclass(frozen=True, slots=True)
class ResearchChartAnnotationBundle:
    """Immutable annotation input for one exact canonical market."""

    market_id: MarketId | None = None
    projections: tuple[ResearchChartAnnotationProjection, ...] = ()

    def __post_init__(self) -> None:
        if self.market_id is not None and not isinstance(self.market_id, MarketId):
            raise TypeError("market_id must be a MarketId or None")
        if not all(
            isinstance(item, ResearchChartAnnotationProjection)
            for item in self.projections
        ):
            raise TypeError(
                "projections must contain ResearchChartAnnotationProjection values"
            )
        if self.market_id is None and self.projections:
            raise ValueError("non-empty annotation bundles require a market_id")
        if self.market_id is not None and any(
            item.annotation.market_id != self.market_id for item in self.projections
        ):
            raise ValueError("all annotations must match the bundle market_id")

    def cache_identity(self) -> tuple[object, ...]:
        return (
            self.market_id,
            tuple(item.cache_identity() for item in self.projections),
        )


@dataclass(frozen=True, slots=True)
class ResearchAnnotationGlyph:
    """One clipped immutable annotation drawing instruction."""

    annotation_id: str
    row_id: str
    kind: str
    global_index: int
    x: float
    y: float
    label: str
    title: str
    tooltip: str
    shape: str
    color: str
    size_px: float = _GLYPH_SIZE_PX

    def __post_init__(self) -> None:
        if not all(
            isinstance(value, str) and value
            for value in (
                self.annotation_id,
                self.row_id,
                self.kind,
                self.label,
                self.title,
                self.tooltip,
                self.shape,
                self.color,
            )
        ):
            raise ValueError("annotation glyph text fields must be non-empty")
        if type(self.global_index) is not int or self.global_index < 0:
            raise ValueError("global_index must be a non-negative integer")
        for name in ("x", "y", "size_px"):
            value = getattr(self, name)
            if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                raise ValueError(f"{name} must be finite")
        if self.size_px <= 0:
            raise ValueError("size_px must be positive")

    def contains(self, x: float, y: float) -> bool:
        half = self.size_px / 2.0
        return abs(float(x) - self.x) <= half and abs(float(y) - self.y) <= half


@dataclass(frozen=True, slots=True)
class ResearchAnnotationScene:
    """Immutable rendered notebook annotation scene."""

    glyphs: tuple[ResearchAnnotationGlyph, ...] = ()
    cache_key: tuple[object, ...] = ()

    def cache_identity(self) -> tuple[object, ...]:
        return self.cache_key


def build_annotation_scene(
    bundle: ResearchChartAnnotationBundle,
    resident: ResidentOHLCVSlice,
    viewport: ViewportSnapshot,
    price_scale: PriceScaleSnapshot,
    plot_rect: SceneRect,
) -> ResearchAnnotationScene:
    """Build deterministic visible annotation geometry without affecting scale."""

    if not isinstance(bundle, ResearchChartAnnotationBundle):
        raise TypeError("bundle must be a ResearchChartAnnotationBundle")
    if not isinstance(resident, ResidentOHLCVSlice):
        raise TypeError("resident must be a ResidentOHLCVSlice")
    if not isinstance(viewport, ViewportSnapshot):
        raise TypeError("viewport must be a ViewportSnapshot")
    if not isinstance(price_scale, PriceScaleSnapshot):
        raise TypeError("price_scale must be a PriceScaleSnapshot")
    if not isinstance(plot_rect, SceneRect):
        raise TypeError("plot_rect must be a SceneRect")

    cache_key = (
        bundle.cache_identity(),
        resident.market_id,
        resident.dataset_fingerprint,
        resident.base_index,
        resident.end_index_exclusive,
        viewport.dataset_count,
        viewport.start_index,
        viewport.end_index_exclusive,
        viewport.visible_count,
        price_scale.cache_identity(),
        plot_rect,
    )
    if bundle.market_id is None or bundle.market_id != resident.market_id:
        return ResearchAnnotationScene(cache_key=cache_key)

    stack_counts: dict[tuple[int, int], int] = {}
    glyphs: list[ResearchAnnotationGlyph] = []
    for projection in bundle.projections:
        global_index = projection.global_index
        if (
            global_index < viewport.start_index
            or global_index >= viewport.end_index_exclusive
            or not resident.contains_global_index(global_index)
        ):
            continue
        annotation = projection.annotation
        local_index = global_index - resident.base_index
        anchor = annotation.anchor_price
        if anchor is None:
            anchor = (
                resident.low[local_index]
                if annotation.kind == "trade_long"
                else resident.high[local_index]
            )
        x = plot_rect.x + (
            (global_index - viewport.start_index + 0.5)
            / max(1, viewport.visible_count)
        ) * plot_rect.width
        anchor_y = _price_to_y(anchor, price_scale, plot_rect)
        direction = -1 if annotation.offset_px < 0 else 1
        if annotation.offset_px == 0:
            direction = 1 if annotation.kind == "trade_long" else -1
        stack_key = (global_index, direction)
        stack_index = stack_counts.get(stack_key, 0)
        stack_counts[stack_key] = stack_index + 1
        y = anchor_y + annotation.offset_px + direction * (
            stack_index * _STACK_DISTANCE_PX
        )
        half = _GLYPH_SIZE_PX / 2.0
        x = min(max(x, plot_rect.x + half), plot_rect.right - half)
        y = min(max(y, plot_rect.y + half), plot_rect.bottom - half)
        shape, color = _KIND_APPEARANCE[annotation.kind]
        glyphs.append(
            ResearchAnnotationGlyph(
                annotation_id=annotation.annotation_id,
                row_id=annotation.row_id,
                kind=annotation.kind,
                global_index=global_index,
                x=x,
                y=y,
                label=annotation.label,
                title=annotation.title,
                tooltip=annotation.tooltip,
                shape=shape,
                color=color,
            )
        )
    return ResearchAnnotationScene(tuple(glyphs), cache_key)


def _price_to_y(
    price: float,
    price_scale: PriceScaleSnapshot,
    plot_rect: SceneRect,
) -> float:
    price_range = price_scale.price_range
    relative = (float(price) - price_range.low) / price_range.span
    return plot_rect.bottom - relative * plot_rect.height
