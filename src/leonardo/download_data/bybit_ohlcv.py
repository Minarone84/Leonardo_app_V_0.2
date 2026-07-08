"""Bybit public OHLCV smoke helpers.

The helpers in this module build Bybit V5 kline request descriptors and
normalize fixture-like kline responses into Download Data execution contracts.
No network transport or live Bybit client is implemented here.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from leonardo.contracts.download_data_execution import (
    DownloadDataCandleSortOrder,
    DownloadDataNormalizedCandle,
    DownloadDataProviderPageRequest,
    DownloadDataProviderPageResult,
    DownloadDataProviderResultStatus,
)


BYBIT_PUBLIC_API_BASE_URL = "https://api.bybit.com"
BYBIT_KLINE_ENDPOINT = "/v5/market/kline"

BybitKlineTransport = Callable[[Mapping[str, object]], Mapping[str, object]]
BybitUrlOpener = Callable[..., object]


class BybitPublicTransportError(RuntimeError):
    """Raised when the opt-in Bybit public REST transport fails."""


def build_bybit_kline_request(
    request: DownloadDataProviderPageRequest,
) -> dict[str, object]:
    """Return a Bybit V5 kline request descriptor without executing it."""

    if not isinstance(request, DownloadDataProviderPageRequest):
        raise TypeError("request must be DownloadDataProviderPageRequest")

    params: dict[str, object] = {
        "category": request.category,
        "symbol": request.symbol.upper(),
        "interval": request.interval,
        "limit": request.limit,
    }
    if request.start_timestamp_ms is not None:
        params["start"] = request.start_timestamp_ms
    if request.end_timestamp_ms is not None:
        params["end"] = request.end_timestamp_ms

    return {
        "method": "GET",
        "endpoint": BYBIT_KLINE_ENDPOINT,
        "params": params,
    }


def build_bybit_kline_url(
    params: Mapping[str, object],
    *,
    base_url: str = BYBIT_PUBLIC_API_BASE_URL,
) -> str:
    """Build a Bybit public kline URL without opening a network connection."""

    _validate_live_kline_params(params)
    query_values = {
        key: str(value)
        for key, value in params.items()
        if value is not None
    }
    return (
        f"{base_url.rstrip('/')}{BYBIT_KLINE_ENDPOINT}"
        f"?{urlencode(query_values)}"
    )


def bybit_public_kline_http_transport(
    params: Mapping[str, object],
    *,
    timeout: float = 10.0,
    opener: BybitUrlOpener | None = None,
    base_url: str = BYBIT_PUBLIC_API_BASE_URL,
) -> Mapping[str, object]:
    """Call Bybit public kline REST transport when explicitly invoked."""

    url = build_bybit_kline_url(params, base_url=base_url)
    request = Request(url, method="GET")
    active_opener = opener or urlopen
    try:
        response = active_opener(request, timeout=timeout)
    except HTTPError as error:
        raise BybitPublicTransportError(
            f"Bybit public kline HTTP status {error.code}"
        ) from error
    except URLError as error:
        raise BybitPublicTransportError(
            f"Bybit public kline transport failed: {error.reason}"
        ) from error

    try:
        status = getattr(response, "status", getattr(response, "code", 200))
        if type(status) is not int or status < 200 or status >= 300:
            raise BybitPublicTransportError(
                f"Bybit public kline HTTP status {status}"
            )
        body = response.read()
    finally:
        close = getattr(response, "close", None)
        if callable(close):
            close()

    try:
        parsed = json.loads(body.decode("utf-8"))
    except (AttributeError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise BybitPublicTransportError(
            "Bybit public kline response JSON is invalid"
        ) from error
    if not isinstance(parsed, Mapping):
        raise BybitPublicTransportError(
            "Bybit public kline response must be a JSON object"
        )
    ret_code = parsed.get("retCode")
    if ret_code not in (0, "0"):
        ret_msg = parsed.get("retMsg", "")
        raise BybitPublicTransportError(
            f"Bybit public kline retCode {ret_code}: {ret_msg}"
        )
    return parsed


def fetch_bybit_kline_page(
    request: DownloadDataProviderPageRequest,
    transport: BybitKlineTransport,
) -> DownloadDataProviderPageResult:
    """Fetch one mocked transport page and normalize it into contract rows."""

    if not callable(transport):
        raise TypeError("transport must be callable")
    descriptor = build_bybit_kline_request(request)
    response = transport(descriptor["params"])  # type: ignore[arg-type]
    return normalize_bybit_kline_response(request, response)


def _validate_live_kline_params(params: Mapping[str, object]) -> None:
    for field_name in ("category", "symbol", "interval", "limit"):
        value = params.get(field_name)
        if value is None or (isinstance(value, str) and not value.strip()):
            raise ValueError(f"Bybit kline param {field_name} is required")


def normalize_bybit_kline_response(
    request: DownloadDataProviderPageRequest,
    response: Mapping[str, object],
) -> DownloadDataProviderPageResult:
    """Normalize a Bybit V5 kline response mapping into ascending candles."""

    if not isinstance(request, DownloadDataProviderPageRequest):
        raise TypeError("request must be DownloadDataProviderPageRequest")
    if not isinstance(response, Mapping):
        raise TypeError("response must be a mapping")

    rows = _extract_kline_rows(response)
    candles = tuple(
        sorted(
            (
                _normalize_kline_row(row, source_order=index)
                for index, row in enumerate(rows)
            ),
            key=lambda candle: candle.timestamp_ms,
        )
    )
    return DownloadDataProviderPageResult(
        request=request,
        status=DownloadDataProviderResultStatus.OK,
        candles=candles,
        sort_order=DownloadDataCandleSortOrder.ASCENDING,
    )


def _extract_kline_rows(response: Mapping[str, object]) -> tuple[object, ...]:
    ret_code = response.get("retCode")
    if ret_code not in (0, "0"):
        raise ValueError("Bybit kline response retCode must be 0")
    result = response.get("result")
    if not isinstance(result, Mapping):
        raise ValueError("Bybit kline response result must be a mapping")
    rows = result.get("list")
    if isinstance(rows, str) or not isinstance(rows, Sequence):
        raise ValueError("Bybit kline response result.list must be a sequence")
    return tuple(rows)


def _normalize_kline_row(
    row: object,
    *,
    source_order: int,
) -> DownloadDataNormalizedCandle:
    if isinstance(row, str) or not isinstance(row, Sequence):
        raise ValueError("Bybit kline row must be a sequence")
    if len(row) < 6:
        raise ValueError("Bybit kline row must include timestamp and OHLCV values")

    timestamp = _coerce_timestamp(row[0])
    open_price = _required_decimal_like(row[1], "open")
    high_price = _required_decimal_like(row[2], "high")
    low_price = _required_decimal_like(row[3], "low")
    close_price = _required_decimal_like(row[4], "close")
    volume = _required_decimal_like(row[5], "volume")
    turnover = _required_decimal_like(row[6], "turnover") if len(row) > 6 else None

    return DownloadDataNormalizedCandle(
        timestamp_ms=timestamp,
        open=open_price,
        high=high_price,
        low=low_price,
        close=close_price,
        volume=volume,
        turnover=turnover,
        source_order=source_order,
    )


def _coerce_timestamp(value: object) -> int:
    if isinstance(value, bool):
        raise ValueError("timestamp must be an integer millisecond value")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    raise ValueError("timestamp must be an integer millisecond value")


def _required_decimal_like(value: object, field_name: str) -> str | int | float:
    if value is None:
        raise ValueError(f"{field_name} is required")
    if isinstance(value, str) and not value.strip():
        raise ValueError(f"{field_name} is required")
    if not isinstance(value, str | int | float) or isinstance(value, bool):
        raise ValueError(f"{field_name} must be decimal-like")
    return value
