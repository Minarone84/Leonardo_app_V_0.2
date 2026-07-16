from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from types import MappingProxyType

import pandas as pd


@dataclass(frozen=True, slots=True, init=False)
class FinancialToolCalculationResult:
    tool_key: str
    kind: str
    parameters: Mapping[str, object]
    bindings: Mapping[str, object]
    output_names: tuple[str, ...]
    row_count: int
    first_timestamp_ms: int
    last_timestamp_ms: int
    _frame: pd.DataFrame = field(repr=False)
    _analysis: dict[str, object] = field(repr=False)

    def __init__(
        self,
        *,
        tool_key: str,
        kind: str,
        parameters: Mapping[str, object],
        bindings: Mapping[str, object],
        output_names: tuple[str, ...],
        frame: pd.DataFrame,
        analysis: Mapping[str, object] | None = None,
    ) -> None:
        frame_copy = frame.copy(deep=True)
        object.__setattr__(self, "tool_key", tool_key)
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "parameters", MappingProxyType(deepcopy(dict(parameters))))
        object.__setattr__(self, "bindings", MappingProxyType(deepcopy(dict(bindings))))
        object.__setattr__(self, "output_names", tuple(output_names))
        object.__setattr__(self, "row_count", len(frame_copy))
        object.__setattr__(self, "first_timestamp_ms", int(frame_copy["ts_ms"].iloc[0]))
        object.__setattr__(self, "last_timestamp_ms", int(frame_copy["ts_ms"].iloc[-1]))
        object.__setattr__(self, "_frame", frame_copy)
        object.__setattr__(self, "_analysis", deepcopy(dict(analysis or {})))

    @property
    def analysis(self) -> dict[str, object]:
        return deepcopy(self._analysis)

    def to_frame(self) -> pd.DataFrame:
        return self._frame.copy(deep=True)
