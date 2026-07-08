import json
import os
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse

import pytest

from leonardo.download_data.bybit_ohlcv import (
    BYBIT_KLINE_ENDPOINT,
    BYBIT_PUBLIC_API_BASE_URL,
    BybitPublicTransportError,
    build_bybit_kline_request,
    bybit_public_kline_http_transport,
)
from leonardo.download_data.smoke_execution import (
    LIVE_BYBIT_SMOKE_ENV_VAR,
    run_bybit_ohlcv_live_smoke,
)


def test_live_transport_builds_url_and_params_without_real_network() -> None:
    seen: dict[str, object] = {}

    def fake_opener(request: object, *, timeout: float) -> _FakeResponse:
        seen["url"] = request.full_url  # type: ignore[attr-defined]
        seen["timeout"] = timeout
        return _FakeResponse(_success_payload())

    result = bybit_public_kline_http_transport(
        _params(),
        timeout=3.0,
        opener=fake_opener,
    )
    parsed_url = urlparse(str(seen["url"]))
    query = parse_qs(parsed_url.query)

    assert result["retCode"] == 0
    assert f"{parsed_url.scheme}://{parsed_url.netloc}" == BYBIT_PUBLIC_API_BASE_URL
    assert parsed_url.path == BYBIT_KLINE_ENDPOINT
    assert query["category"] == ["spot"]
    assert query["symbol"] == ["BTCUSDT"]
    assert query["interval"] == ["1"]
    assert query["limit"] == ["10"]
    assert seen["timeout"] == 3.0


def test_live_transport_handles_fixture_success_response() -> None:
    response = bybit_public_kline_http_transport(
        _params(),
        opener=lambda request, *, timeout: _FakeResponse(_success_payload()),
    )

    assert response["retCode"] == 0
    assert response["result"]["list"][0][0] == "1700000060000"  # type: ignore[index]


def test_live_transport_rejects_nonzero_ret_code() -> None:
    payload = {"retCode": 10001, "retMsg": "bad request", "result": {}}

    with pytest.raises(BybitPublicTransportError, match="retCode 10001"):
        bybit_public_kline_http_transport(
            _params(),
            opener=lambda request, *, timeout: _FakeResponse(payload),
        )


def test_live_transport_rejects_malformed_json() -> None:
    with pytest.raises(BybitPublicTransportError, match="JSON"):
        bybit_public_kline_http_transport(
            _params(),
            opener=lambda request, *, timeout: _FakeResponse(b"{not-json"),
        )


def test_live_transport_rejects_http_failure_status() -> None:
    with pytest.raises(BybitPublicTransportError, match="HTTP status 503"):
        bybit_public_kline_http_transport(
            _params(),
            opener=lambda request, *, timeout: _FakeResponse(_success_payload(), status=503),
        )


def test_live_transport_rejects_http_error_exception() -> None:
    def fake_opener(request: object, *, timeout: float) -> object:
        raise HTTPError(
            url="https://api.bybit.com/v5/market/kline",
            code=500,
            msg="server error",
            hdrs=None,
            fp=None,
        )

    with pytest.raises(BybitPublicTransportError, match="HTTP status 500"):
        bybit_public_kline_http_transport(_params(), opener=fake_opener)


def test_live_smoke_helper_refuses_without_allow_flag_or_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(LIVE_BYBIT_SMOKE_ENV_VAR, raising=False)

    with pytest.raises(PermissionError, match=LIVE_BYBIT_SMOKE_ENV_VAR):
        run_bybit_ohlcv_live_smoke(
            sandbox_root=tmp_path,
            transport=_failing_transport,
        )

    assert not (tmp_path / "historical").exists()


def test_live_smoke_helper_accepts_explicit_allow_with_mocked_transport(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(LIVE_BYBIT_SMOKE_ENV_VAR, raising=False)

    result = run_bybit_ohlcv_live_smoke(
        sandbox_root=tmp_path,
        allow_live=True,
        transport=_fixture_transport,
    )

    assert result.total_bars_downloaded == 2
    assert result.total_bars_written == 2
    assert (tmp_path / "historical/bybit/spot/BTCUSDT/1m/ohlcv/candles.csv").exists()
    assert (
        tmp_path / "historical/bybit/spot/BTCUSDT/1m/ohlcv/candles.meta.json"
    ).exists()


def test_live_smoke_helper_accepts_env_gate_with_mocked_transport(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(LIVE_BYBIT_SMOKE_ENV_VAR, "1")

    result = run_bybit_ohlcv_live_smoke(
        sandbox_root=tmp_path,
        transport=_fixture_transport,
    )

    assert result.status.value == "completed"
    assert result.storage_results[0].bars_written == 2


@pytest.mark.skipif(
    os.environ.get(LIVE_BYBIT_SMOKE_ENV_VAR) != "1",
    reason="live Bybit smoke is explicit opt-in only",
)
def test_optional_live_bybit_public_kline_smoke(tmp_path: Path) -> None:
    result = run_bybit_ohlcv_live_smoke(
        sandbox_root=tmp_path,
    )

    assert result.total_bars_written > 0
    assert (tmp_path / "historical/bybit/spot/BTCUSDT/1m/ohlcv/candles.csv").exists()


def _params() -> dict[str, object]:
    descriptor = build_bybit_kline_request(_page_request())
    return dict(descriptor["params"])  # type: ignore[arg-type]


def _page_request() -> object:
    from leonardo.contracts.download_data_execution import (
        DownloadDataProviderPageRequest,
    )

    return DownloadDataProviderPageRequest(
        exchange_id="bybit",
        market_type="spot",
        symbol="BTCUSDT",
        timeframe="1m",
        category="spot",
        interval="1",
        limit=10,
    )


def _fixture_transport(params: object) -> dict[str, object]:
    if dict(params) != _params():  # type: ignore[arg-type]
        raise AssertionError("unexpected live smoke params")
    return _success_payload()


def _failing_transport(params: object) -> dict[str, object]:
    raise AssertionError("transport must not run without live gate")


def _success_payload() -> dict[str, object]:
    return {
        "retCode": 0,
        "retMsg": "OK",
        "result": {
            "category": "spot",
            "symbol": "BTCUSDT",
            "list": [
                [
                    "1700000060000",
                    "42005.0",
                    "42020.0",
                    "42000.0",
                    "42015.0",
                    "1.2",
                    "50400.0",
                ],
                [
                    "1700000000000",
                    "42000.0",
                    "42010.0",
                    "41990.0",
                    "42005.0",
                    "1.1",
                    "46200.0",
                ],
            ],
        },
    }


class _FakeResponse:
    def __init__(
        self,
        payload: dict[str, object] | bytes,
        *,
        status: int = 200,
    ) -> None:
        self.status = status
        self._payload = payload
        self.closed = False

    def read(self) -> bytes:
        if isinstance(self._payload, bytes):
            return self._payload
        return json.dumps(self._payload).encode("utf-8")

    def close(self) -> None:
        self.closed = True
