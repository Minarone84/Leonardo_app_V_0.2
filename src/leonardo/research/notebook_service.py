"""Pure Research Notebook construction, persistence, and annotation projection."""

from __future__ import annotations

from collections.abc import Sequence

from leonardo.data import MarketId, canonicalize_market_id
from leonardo.research.notebook import (
    ResearchNotebookAnnotation,
    ResearchNotebookAnnotationSettingsV1,
    ResearchNotebookDraft,
    ResearchNotebookPageV1,
    ResearchNotebookSummary,
    ResearchNotebookV1,
)
from leonardo.research.notebook_store import ResearchNotebookStore


_KIND_ORDER = {"trade_long": 0, "trade_short": 1, "poi": 2}


class ResearchNotebookService:
    """Own Research Notebook semantics while delegating filesystem work."""

    def __init__(self, store: ResearchNotebookStore) -> None:
        if not isinstance(store, ResearchNotebookStore):
            raise TypeError("store must be ResearchNotebookStore")
        self._store = store

    def build_draft(
        self,
        *,
        display_name: str,
        description: str = "",
        annotation_settings: ResearchNotebookAnnotationSettingsV1 | None = None,
        pages: Sequence[ResearchNotebookPageV1] = (),
        notebook_id: str | None = None,
    ) -> ResearchNotebookDraft:
        return ResearchNotebookDraft(
            display_name=display_name,
            description=description,
            annotation_settings=(
                ResearchNotebookAnnotationSettingsV1()
                if annotation_settings is None
                else annotation_settings
            ),
            pages=tuple(pages),
            notebook_id=notebook_id,
        )

    def list_notebooks(self) -> tuple[ResearchNotebookSummary, ...]:
        return self._store.list_summaries()

    def load_notebook(self, notebook_id: str) -> ResearchNotebookV1:
        return self._store.load(notebook_id)

    def create_notebook(self, draft: ResearchNotebookDraft) -> ResearchNotebookV1:
        return self._store.create(draft)

    def update_notebook(
        self, notebook_id: str, draft: ResearchNotebookDraft
    ) -> ResearchNotebookV1:
        return self._store.update(notebook_id, draft)

    def delete_notebook(self, notebook_id: str) -> ResearchNotebookSummary:
        return self._store.delete(notebook_id)

    def project_annotations(
        self,
        notebook: ResearchNotebookV1,
        market_id: MarketId,
    ) -> tuple[ResearchNotebookAnnotation, ...]:
        if not isinstance(notebook, ResearchNotebookV1):
            raise TypeError("notebook must be ResearchNotebookV1")
        if not isinstance(market_id, MarketId):
            raise TypeError("market_id must be MarketId")
        canonical = canonicalize_market_id(
            market_id.exchange,
            market_id.market_type,
            market_id.symbol,
            market_id.timeframe,
        )
        if canonical != market_id:
            raise ValueError("market_id must be canonical")
        page = next(
            (item for item in notebook.pages if item.market_id == market_id),
            None,
        )
        if page is None:
            return ()
        settings = notebook.annotation_settings
        annotations: list[ResearchNotebookAnnotation] = []
        if settings.show_potential_trades:
            for trade in page.potential_trades:
                kind = f"trade_{trade.direction}"
                annotations.append(
                    ResearchNotebookAnnotation(
                        annotation_id=f"{notebook.notebook_id}:{trade.row_id}",
                        notebook_id=notebook.notebook_id,
                        row_id=trade.row_id,
                        market_id=market_id,
                        kind=kind,
                        timestamp_ms=trade.timestamp_ms,
                        anchor_price=trade.entry_price,
                        label="L" if trade.direction == "long" else "S",
                        title=(
                            "Long Potential Trade"
                            if trade.direction == "long"
                            else "Short Potential Trade"
                        ),
                        tooltip=_trade_tooltip(trade),
                        offset_px=(
                            settings.long_offset_px
                            if trade.direction == "long"
                            else settings.short_offset_px
                        ),
                    )
                )
        if settings.show_points_of_interest:
            for point in page.points_of_interest:
                annotations.append(
                    ResearchNotebookAnnotation(
                        annotation_id=f"{notebook.notebook_id}:{point.row_id}",
                        notebook_id=notebook.notebook_id,
                        row_id=point.row_id,
                        market_id=market_id,
                        kind="poi",
                        timestamp_ms=point.timestamp_ms,
                        anchor_price=point.price,
                        label="+",
                        title=point.title,
                        tooltip=_poi_tooltip(point),
                        offset_px=settings.poi_offset_px,
                    )
                )
        return tuple(
            sorted(
                annotations,
                key=lambda item: (
                    item.timestamp_ms,
                    _KIND_ORDER[item.kind],
                    item.row_id,
                ),
            )
        )


def _trade_tooltip(trade) -> str:
    values = [
        f"{trade.direction.title()} Potential Trade",
        f"Status: {trade.status}",
        f"Outcome: {trade.outcome}",
    ]
    for label, value in (
        ("Entry", trade.entry_price),
        ("Target", trade.target_price),
        ("Stop", trade.stop_price),
    ):
        if value is not None:
            values.append(f"{label}: {value}")
    if trade.note:
        values.append(trade.note)
    return "\n".join(values)


def _poi_tooltip(point) -> str:
    values = [point.title]
    if point.price is not None:
        values.append(f"Price: {point.price}")
    if point.description:
        values.append(point.description)
    return "\n".join(values)
