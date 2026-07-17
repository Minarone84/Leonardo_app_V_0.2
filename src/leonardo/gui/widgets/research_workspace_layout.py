"""Pure adaptive layout planning for occupied Research chart slots."""

from __future__ import annotations

from dataclasses import dataclass


RESEARCH_WORKSPACE_MODES = ("scroll_4", "fit_8")


@dataclass(frozen=True, slots=True)
class ResearchWorkspaceLayoutItem:
    slot_id: int
    visual_index: int
    row: int
    column: int
    row_span: int = 1
    column_span: int = 1


@dataclass(frozen=True, slots=True)
class ResearchWorkspaceLayoutPlan:
    mode: str
    items: tuple[ResearchWorkspaceLayoutItem, ...]
    row_count: int
    vertical_scroll: str
    minimum_height_ratio: float

    @property
    def count(self) -> int:
        return len(self.items)


def build_research_workspace_layout(
    slot_ids: object, mode: str
) -> ResearchWorkspaceLayoutPlan:
    supplied = _validated_slot_ids(slot_ids, mode)
    return _build_layout(tuple(sorted(supplied)), mode)


def build_research_workspace_layout_in_order(
    ordered_slot_ids: object, mode: str
) -> ResearchWorkspaceLayoutPlan:
    supplied = _validated_slot_ids(ordered_slot_ids, mode)
    return _build_layout(supplied, mode)


def _validated_slot_ids(slot_ids: object, mode: str) -> tuple[int, ...]:
    if mode not in RESEARCH_WORKSPACE_MODES:
        raise ValueError("mode must be 'scroll_4' or 'fit_8'")
    if isinstance(slot_ids, (str, bytes)):
        raise TypeError("slot_ids must be an iterable of integers")
    try:
        supplied = tuple(slot_ids)  # type: ignore[arg-type]
    except TypeError as error:
        raise TypeError("slot_ids must be an iterable of integers") from error
    if len(supplied) > 8:
        raise ValueError("at most eight slot IDs are supported")
    if any(type(slot_id) is not int or not 1 <= slot_id <= 8 for slot_id in supplied):
        raise ValueError("slot IDs must be unique integers from 1 through 8")
    if len(set(supplied)) != len(supplied):
        raise ValueError("slot IDs must be unique integers from 1 through 8")
    return supplied


def _build_layout(
    ordered_slot_ids: tuple[int, ...], mode: str
) -> ResearchWorkspaceLayoutPlan:
    positions = _positions(len(ordered_slot_ids))
    items = tuple(
        ResearchWorkspaceLayoutItem(slot_id, visual_index, *position)
        for visual_index, (slot_id, position) in enumerate(
            zip(ordered_slot_ids, positions, strict=True)
        )
    )
    row_count = 0 if not positions else max(position[0] for position in positions) + 1
    if mode == "scroll_4":
        vertical_scroll = "as_needed"
        minimum_height_ratio = max(1.0, row_count / 2.0)
    else:
        vertical_scroll = "off"
        minimum_height_ratio = 1.0
    return ResearchWorkspaceLayoutPlan(
        mode, items, row_count, vertical_scroll, minimum_height_ratio
    )


def _positions(count: int) -> tuple[tuple[int, int, int, int], ...]:
    if count == 0:
        return ()
    if count == 1:
        return ((0, 0, 1, 2),)
    if count == 2:
        return ((0, 0, 1, 1), (0, 1, 1, 1))
    if count == 3:
        return ((0, 0, 1, 2), (1, 0, 1, 1), (1, 1, 1, 1))
    positions = [(index // 2, index % 2, 1, 1) for index in range(count)]
    if count in (5, 7):
        positions[-1] = (count // 2, 0, 1, 2)
    return tuple(positions)
