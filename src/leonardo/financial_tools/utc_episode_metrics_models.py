"""Validated, detached nonvisual measurements of an unchanged UTC report."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field

import pandas as pd

from .utc_classification_models import UtcClassificationResult, _plain
from ._calculation.utc_episode_metrics import _build_metrics, _digest, _MEMBERSHIPS


@dataclass(frozen=True, slots=True, init=False)
class UtcEpisodeMetricsResult:
    _payload: dict = field(repr=False)

    def __init__(self, value, *, classification):
        core = (classification.to_dict() if isinstance(classification, UtcClassificationResult)
                else UtcClassificationResult.from_dict(classification).to_dict())
        value = _plain(value)
        if not isinstance(value, dict) or value.get("schema_version") != "1.0" or value.get("measurement_rule_version") != "utc-episode-metrics-1":
            raise ValueError("unsupported UTC episode metrics schema or rule")
        if core["status"] == "legacy_unavailable" or value.get("classification_sha256") != _digest(core):
            raise ValueError("UTC episode metrics classification binding mismatch")
        try:
            expected = _build_metrics(core, value["evidence"])
        except (KeyError, TypeError, IndexError) as exc:
            raise ValueError("invalid UTC episode metrics evidence") from exc
        if _digest(value) != _digest(expected):
            raise ValueError("UTC episode metrics disagree with retained evidence or classification")
        object.__setattr__(self, "_payload", value)

    @classmethod
    def from_dict(cls, value, *, classification):
        return cls(value, classification=classification)

    def to_dict(self):
        return deepcopy(self._payload)

    @property
    def episodes(self):
        return tuple(deepcopy(self._payload["episodes"]))

    @property
    def context_at_cutoff(self):
        return deepcopy(self._payload["context_at_cutoff"])

    def to_episode_frame(self):
        return pd.DataFrame(list(self.episodes), dtype=object)

    def to_pullback_frame(self):
        return pd.DataFrame([p for e in self.episodes for p in e["pullbacks"]], dtype=object)

    def _validate_output_membership(self, frame):
        from ._calculation.universal_trend_classifier import _OUTPUT_COLUMNS
        for name in _MEMBERSHIPS:
            values = frame.iloc[:, 1 + _OUTPUT_COLUMNS.index(name)].tolist()
            if values != [bar[name] for bar in self._payload["evidence"]["bars"]]:
                raise ValueError("UTC episode metrics membership disagrees with numeric result")
