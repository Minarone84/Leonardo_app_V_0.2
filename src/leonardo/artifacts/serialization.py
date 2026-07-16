from __future__ import annotations

import csv
import hashlib
import io
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from .models import ArtifactValidationError


@dataclass(frozen=True, slots=True)
class _FileState:
    size: int
    modified_ns: int
    sha256: str


def encode_canonical_json(payload: Mapping[str, object]) -> bytes:
    return (
        json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False)
        + "\n"
    ).encode("utf-8")


def decode_canonical_json(data: bytes, *, context: str) -> dict[str, object]:
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ArtifactValidationError(f"invalid {context} JSON") from exc
    if not isinstance(value, dict):
        raise ArtifactValidationError(f"{context} JSON root must be an object")
    try:
        json.dumps(value, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ArtifactValidationError(f"{context} JSON must be finite and JSON-safe") from exc
    if encode_canonical_json(value) != data:
        raise ArtifactValidationError(f"{context} JSON bytes must be canonical")
    return value


def encode_values_csv(
    frame: pd.DataFrame,
    output_names: Sequence[str],
    runtime_types: Sequence[str],
) -> bytes:
    columns = ("ts_ms", *output_names)
    if tuple(frame.columns) != columns:
        raise ArtifactValidationError("values frame columns do not match recipe outputs")
    if len(runtime_types) != len(output_names):
        raise ArtifactValidationError("runtime output type count does not match output names")
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(columns)
    type_by_name = dict(zip(output_names, runtime_types, strict=True))
    for row in frame.itertuples(index=False, name=None):
        timestamp = row[0]
        if isinstance(timestamp, (bool, np.bool_)):
            raise ArtifactValidationError("ts_ms values must be integer-valued numbers")
        if isinstance(timestamp, (float, np.floating)):
            numeric_timestamp = float(timestamp)
            if not math.isfinite(numeric_timestamp) or not numeric_timestamp.is_integer():
                raise ArtifactValidationError("ts_ms values must be finite integers")
        elif not isinstance(timestamp, (int, np.integer)):
            raise ArtifactValidationError("ts_ms values must be integer-valued numbers")
        encoded = [str(int(timestamp))]
        for name, value in zip(output_names, row[1:], strict=True):
            encoded.append(_encode_value(value, name, type_by_name[name]))
        writer.writerow(encoded)
    return buffer.getvalue().encode("utf-8")


def decode_values_csv(
    data: bytes,
    output_names: Sequence[str],
    runtime_types: Sequence[str],
) -> pd.DataFrame:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ArtifactValidationError("values.csv must be UTF-8") from exc
    reader = csv.reader(io.StringIO(text, newline=""))
    try:
        header = tuple(next(reader))
    except StopIteration as exc:
        raise ArtifactValidationError("values.csv must contain a header") from exc
    expected = ("ts_ms", *output_names)
    if header != expected or len(runtime_types) != len(output_names):
        raise ArtifactValidationError("values.csv columns do not match recipe outputs")
    rows: list[list[object]] = []
    prior_timestamp: int | None = None
    for line_number, row in enumerate(reader, start=2):
        if len(row) != len(expected):
            raise ArtifactValidationError(f"invalid values.csv field count at line {line_number}")
        try:
            timestamp = int(row[0])
        except ValueError as exc:
            raise ArtifactValidationError(f"invalid ts_ms at line {line_number}") from exc
        if str(timestamp) != row[0] or (prior_timestamp is not None and timestamp <= prior_timestamp):
            raise ArtifactValidationError("values.csv timestamps must be canonical and strictly increasing")
        prior_timestamp = timestamp
        values: list[object] = [timestamp]
        for raw, name, runtime_type in zip(row[1:], output_names, runtime_types, strict=True):
            values.append(_decode_value(raw, name, runtime_type, line_number))
        rows.append(values)
    if not rows:
        raise ArtifactValidationError("values.csv must contain at least one data row")
    frame = pd.DataFrame(rows, columns=expected)
    frame["ts_ms"] = frame["ts_ms"].astype("int64")
    for name, runtime_type in zip(output_names, runtime_types, strict=True):
        if runtime_type == "numeric":
            frame[name] = frame[name].astype("float32")
        elif runtime_type == "boolean":
            frame[name] = frame[name].astype(bool)
        else:
            frame[name] = frame[name].astype(object)
    if encode_values_csv(frame, output_names, runtime_types) != data:
        raise ArtifactValidationError("values.csv bytes must be canonical")
    return frame


def encode_analysis_json(analysis: Mapping[str, object]) -> bytes:
    return encode_canonical_json(_plain_finite(analysis, "analysis"))


def decode_analysis_json(data: bytes) -> dict[str, object]:
    return decode_canonical_json(data, context="analysis")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def capture_file_state(path: Path) -> _FileState:
    target = Path(path)
    before = target.stat()
    digest = hashlib.sha256()
    with target.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    after = target.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ArtifactValidationError(f"file changed while hashing: {target.name}")
    return _FileState(after.st_size, after.st_mtime_ns, digest.hexdigest())


def _encode_value(value: object, name: str, runtime_type: str) -> str:
    if runtime_type == "boolean":
        if not isinstance(value, (bool, np.bool_)):
            raise ArtifactValidationError(f"{name} must contain booleans")
        return "true" if bool(value) else "false"
    if runtime_type == "categorical":
        if not isinstance(value, str):
            raise ArtifactValidationError(f"{name} must contain categorical strings")
        return value
    if pd.isna(value):
        return ""
    if isinstance(value, (bool, np.bool_)):
        raise ArtifactValidationError(f"{name} must contain numeric values, not booleans")
    if not isinstance(value, (int, float, np.integer, np.floating)):
        raise ArtifactValidationError(f"{name} must contain numeric values")
    numeric = float(value)
    if not math.isfinite(numeric):
        raise ArtifactValidationError(f"{name} must contain finite values or NaN")
    return format(np.float32(numeric), ".9g")


def _decode_value(raw: str, name: str, runtime_type: str, line_number: int) -> object:
    if runtime_type == "boolean":
        if raw not in {"true", "false"}:
            raise ArtifactValidationError(f"invalid boolean at line {line_number}")
        return raw == "true"
    if runtime_type == "categorical":
        if not raw:
            raise ArtifactValidationError(f"empty categorical value at line {line_number}")
        return raw
    if raw == "":
        return np.float32(np.nan)
    try:
        value = float(raw)
    except ValueError as exc:
        raise ArtifactValidationError(f"invalid numeric value at line {line_number}") from exc
    if not math.isfinite(value):
        raise ArtifactValidationError(f"non-finite numeric value at line {line_number}")
    return np.float32(value)


def _plain_finite(value: object, context: str) -> object:
    if isinstance(value, Mapping):
        result: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ArtifactValidationError(f"{context} keys must be strings")
            result[key] = _plain_finite(item, f"{context}.{key}")
        return result
    if isinstance(value, (list, tuple)):
        return [_plain_finite(item, context) for item in value]
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        value = float(value)
    if isinstance(value, float) and not math.isfinite(value):
        raise ArtifactValidationError(f"{context} must contain finite values")
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    raise ArtifactValidationError(f"{context} must contain only JSON-safe finite values")
