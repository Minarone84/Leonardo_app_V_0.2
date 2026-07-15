from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from types import MappingProxyType


_CANONICAL_TOOL_ALIASES = {
    "utc": "universal_trend_classifier",
    "dynamic_binning_analysis": "dynamic_binning",
    "derivative_analysis": "derivative",
    "angle_analysis": "angle",
    "braid_state_analysis": "braids",
    "trap_area_analysis": "trap_area",
    "percent_angle": "percent_span_angle",
    "percent_angle_analysis": "percent_span_angle",
    "percent_span_angle_analysis": "percent_span_angle",
}
CANONICAL_TOOL_ALIASES = MappingProxyType(_CANONICAL_TOOL_ALIASES)


def _slugify_token(value: object) -> str:
    text = str(value).strip().lower()
    if not text:
        return "unknown"
    for old, new in (
        ("%", "pct"), (" ", "_"), ("/", "_"), ("\\", "_"), ("(", "_"), (")", "_"),
        ("[", "_"), ("]", "_"), ("{", "_"), ("}", "_"), (",", "_"), ("=", "_"),
        (":", "_"), (";", "_"),
    ):
        text = text.replace(old, new)
    text = re.sub(r"[^a-z0-9_-]+", "_", text)
    text = re.sub(r"_+", "_", text)
    text = re.sub(r"-+", "-", text)
    return text.strip("_-") or "unknown"


def canonicalize_tool_key(key: str) -> str:
    token = _slugify_token(key)
    if token == "unknown":
        raise ValueError("financial tool key must be non-empty")
    return CANONICAL_TOOL_ALIASES.get(token, token)


def build_source_token(source: object) -> str:
    text = str(source).strip().lower()
    if not text:
        return "unknown"
    sentinel = "zzdblsepzz"
    token = _slugify_token(text.replace("__", sentinel)).replace(sentinel, "__")
    token = re.sub(r"__+", "__", token.strip("_-"))
    return token or "unknown"


def _source(value: object, context: str) -> str:
    if value is None or not str(value).strip():
        raise ValueError(f"{context} requires a non-empty source")
    token = build_source_token(value)
    if token == "unknown":
        raise ValueError(f"{context} requires a non-empty source")
    return token


def _sources(value: object, context: str) -> tuple[str, ...]:
    if isinstance(value, str):
        raw = tuple(part.strip() for part in value.split(","))
    elif isinstance(value, Iterable):
        raw = tuple(str(part).strip() for part in value)
    else:
        raise ValueError(f"{context} must contain one or more sources")
    result = tuple(_source(part, context) for part in raw if part)
    if not result:
        raise ValueError(f"{context} must contain one or more sources")
    if len(result) != len(set(result)):
        raise ValueError(f"{context} contains duplicate sources")
    return result


def _parts(prefix: str, *parts: object) -> str:
    return "_".join((prefix, *(_slugify_token(part) for part in parts)))


def _resolve_indicator_names(key: str, params: Mapping[str, object]) -> tuple[str, ...]:
    if key in {"sma", "ema", "tema", "hma"}:
        return (_parts(key, params["period"]),)
    if key == "kama":
        return (_parts("kama", params["fast_period"], params["slow_period"]),)
    if key == "bb":
        return ("bb_middle", "bb_upper_band", "bb_lower_band")
    if key == "hck":
        return ("fast_vwap", "slow_vwap", "vwap_color")
    if key == "strategy":
        return tuple(
            [*(f"st_ema_{slot}" for slot in range(1, 7)), *(f"st_sma_{slot}" for slot in range(1, 7)),
             "st_bb_middle", "st_bb_upper_band", "st_bb_lower_band",
             "st_fast_vwap", "st_slow_vwap", "st_vwap_color"]
        )
    if key == "peaks_troughs":
        return tuple(
            name for length in (3, 5, 7, 9, 11)
            for name in (f"peak_fractal_{length}", f"trough_fractal_{length}")
        )
    if key == "universal_trend_classifier":
        return (
            "horizontal_range", "hr_start", "hr_end", "hor_upper", "hor_lower", "uptrend",
            "uptrend_start", "uptrend_end", "downtrend", "downtrend_start", "downtrend_end",
            "hr_uptrend", "hr_downtrend", "hr_start_marker", "hr_end_marker",
            "uptrend_start_marker", "uptrend_end_marker", "downtrend_start_marker",
            "downtrend_end_marker", "hr_breakout_attempt", "hr_pending_breakout",
            "hr_breakout_confirmed", "hr_false_breakout", "hr_reclaim", "hr_break_direction",
            "hr_break_extreme", "hr_reclaim_marker",
        )
    raise KeyError(key)


def _resolve_oscillator_names(key: str, params: Mapping[str, object]) -> tuple[str, ...]:
    if key in {"rsi", "mfi"}:
        return (_parts(key, params["period"]),)
    if key == "arsi":
        return (
            _parts("arsi", params["period"], params["method"]),
            _parts("arsi_signal", params["period"], params["method"], params["signal_period"], params["signal_method"]),
        )
    if key == "tdirsi":
        suffix = tuple(params[name] for name in ("period", "band_length", "fast_len", "slow_len", "fast_smo", "slow_smo"))
        return tuple(_parts(prefix, *suffix) for prefix in (
            "tdirsi_fast_ma", "tdirsi_slow_ma", "tdirsi_up", "tdirsi_dn", "tdirsi_mid"
        ))
    if key == "smi":
        return (
            _parts("smi", params["k_length"], params["d_length"]),
            _parts("smi_signal", params["k_length"], params["d_length"]),
        )
    if key == "obv":
        return ("obv",)
    if key == "volume":
        return ("volume", _parts("volume_mean", params["period"]))
    raise KeyError(key)


def _resolve_construct_names(key: str, params: Mapping[str, object], bindings: Mapping[str, object]) -> tuple[str, ...]:
    if key == "dynamic_binning":
        return ()
    if key == "derivative":
        source = _source(bindings.get("source", bindings.get("source_column")), "derivative.source")
        return (f"{source}__d{params['order']}",)
    if key == "angle":
        source = _source(bindings.get("source", bindings.get("source_column")), "angle.source")
        return (f"{source}__ang",)
    if key in {"braids", "braid_instability", "trap_area"}:
        fast = _source(params.get("fast"), f"{key}.fast")
        slow = _source(params.get("slow"), f"{key}.slow")
        mid_raw = params.get("mid")
        if key == "trap_area":
            if mid_raw is None or not str(mid_raw).strip():
                return (f"{fast}_{slow}_trapA",)
            mid = _source(mid_raw, "trap_area.mid")
            return (f"{fast}_{mid}_trapA", f"{fast}_{slow}_trapA", f"{mid}_{slow}_trapA")
        mid = _source(mid_raw, f"{key}.mid")
        base = f"{fast}_{mid}_{slow}"
        if key == "braids":
            return (base, f"{base}_width", f"{base}_compression")
        return (f"{base}_inst_{_slugify_token(params['n'])}",)
    if key == "delta":
        fast = _source(params.get("fast"), "delta.fast")
        slow = _source(params.get("slow"), "delta.slow")
        suffix = "delta_pct" if params["mode"] == "pct" else "delta"
        return (f"{fast}_{slow}_{suffix}",)
    if key == "percent_span_angle":
        sources = _sources(params["source_columns"], "percent_span_angle.source_columns")
        return tuple(f"{source}_ang_pct_span_{_slugify_token(params['window'])}" for source in sources)
    if key == "angle_momentum":
        sources = _sources(params["source_columns"], "angle_momentum.source_columns")
        return tuple(f"{source}_ang_mtm_{_slugify_token(params['n'])}" for source in sources)
    raise KeyError(key)


def resolve_output_names(
    tool_key: str,
    parameters: Mapping[str, object] | None = None,
) -> tuple[str, ...]:
    from .specifications import get_financial_tool_spec, resolve_parameters

    key = canonicalize_tool_key(tool_key)
    spec = get_financial_tool_spec(key)
    supplied = dict(parameters or {})
    bindings: dict[str, object] = {}
    if key in {"derivative", "angle"}:
        for binding_name in ("source", "source_column"):
            if binding_name in supplied:
                bindings[binding_name] = supplied.pop(binding_name)
    resolved = resolve_parameters(key, supplied)
    if spec.kind == "indicator":
        return _resolve_indicator_names(key, resolved)
    if spec.kind == "oscillator":
        return _resolve_oscillator_names(key, resolved)
    return _resolve_construct_names(key, resolved, bindings)
