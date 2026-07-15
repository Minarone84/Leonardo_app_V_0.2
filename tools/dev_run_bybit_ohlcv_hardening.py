"""Run a temporary real-Bybit OHLCV download, validation, and repair smoke.

This tool uses only Bybit public REST endpoints and a temporary data directory.
It does not read credentials and does not touch the configured Leonardo data root.
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory

from leonardo.connection import (
    ConnectionApplicationService,
    HistoricalProviderRequestError,
    ProviderRegistry,
)
from leonardo.connection.bybit import BybitHistoricalProvider
from leonardo.core.audit_log import AuditLog, InMemoryAuditSink
from leonardo.core.connection_registry import ConnectionRegistry
from leonardo.data import canonicalize_market_id
from leonardo.ohlcv import (
    CanonicalOHLCVValidator,
    DownloadBatchRequest,
    HistoricalDownloadService,
    OHLCVDatasetOperationLocks,
    OHLCVMaintenanceService,
    OHLCVStore,
)
from leonardo.ohlcv.maintenance import repair_range_result

_MINUTE_MS = 60_000


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Temporary real-Bybit OHLCV download/repair hardening smoke"
    )
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--market", default="linear")
    parser.add_argument("--timeframe", default="1m")
    return parser


async def _run(symbol: str, market_type: str, timeframe: str) -> None:
    if timeframe != "1m":
        raise ValueError("Task 1012 smoke currently supports exactly timeframe=1m")

    with TemporaryDirectory(prefix="leo_task1012_bybit_") as directory:
        root = Path(directory)
        registry = ProviderRegistry()
        registry.register("bybit", BybitHistoricalProvider)
        connections = ConnectionApplicationService(registry, ConnectionRegistry())
        audit = AuditLog(InMemoryAuditSink())
        store = OHLCVStore(root / "historical_data")
        locks = OHLCVDatasetOperationLocks()
        downloader = HistoricalDownloadService(
            connections,
            store,
            audit,
            actor_id="task1012-smoke",
            operation_locks=locks,
        )
        maintenance = OHLCVMaintenanceService(
            store,
            CanonicalOHLCVValidator(),
            audit_log=audit,
            actor_id="task1012-smoke",
        )
        market = canonicalize_market_id("bybit", market_type, symbol, timeframe)

        async with connections.provider_session("bybit") as provider:
            server_time_ms = await provider.get_server_time_ms()
        current_open = (server_time_ms // _MINUTE_MS) * _MINUTE_MS
        end_ms = current_open - _MINUTE_MS
        start_ms = end_ms - (2 * _MINUTE_MS)

        print(f"Temporary root: {root}")
        print(f"Downloading real Bybit range: {start_ms}..{end_ms}")
        request = DownloadBatchRequest(
            exchange="bybit",
            market_type=market_type,
            symbol=symbol,
            timeframes=(timeframe,),
            start_ms=start_ms,
            end_ms=end_ms,
            limit=3,
        )
        batch = await downloader.run_batch(request)
        downloaded = batch.results[0]
        if downloaded.total_rows < 3:
            raise RuntimeError(
                f"Bybit returned only {downloaded.total_rows} rows; expected at least 3"
            )

        initial_validation = maintenance.validate(market)
        if not initial_validation.accepted:
            raise RuntimeError(
                "real Bybit download did not pass canonical validation: "
                f"{initial_validation.report.messages}"
            )
        print("Initial real-provider validation: accepted")

        candles = list(store.read(market))
        missing_ts = candles[len(candles) // 2].ts_ms
        injected = [candle for candle in candles if candle.ts_ms != missing_ts]
        store.write(
            market,
            injected,
            source="task1012_fault_injection",
            persistence_status="committed",
            lineage={"task1012_missing_ts_ms": missing_ts},
        )
        damaged_validation = maintenance.validate(market)
        if damaged_validation.report.status == "ok":
            raise RuntimeError("fault injection did not produce a canonical validation issue")

        plan = maintenance.plan_repair(market)
        if not plan.actionable:
            raise RuntimeError(f"real-provider repair plan was not actionable: {plan.message}")
        print(f"Repairing real Bybit gap at ts_ms={missing_ts}")
        requests = tuple(
            DownloadBatchRequest(
                exchange=market.exchange,
                market_type=market.market_type,
                symbol=market.symbol,
                timeframes=(market.timeframe,),
                start_ms=item.start_ts_ms,
                end_ms=item.end_ts_ms,
            )
            for item in plan.ranges
        )
        batches = await downloader.run_repair_batches(
            requests,
            before_first_write=lambda: maintenance.assert_repair_plan_current(plan),
        )
        range_results = tuple(
            repair_range_result(repair_range, batch.results[0])
            for repair_range, batch in zip(plan.ranges, batches, strict=True)
        )
        repaired_sidecar = maintenance.mark_repair_completed(plan, range_results)
        repaired_validation = maintenance.validate(market)
        result = maintenance.build_repair_result(
            plan,
            range_results,
            repaired_sidecar,
            repaired_validation,
        )
        if not result.accepted:
            raise RuntimeError(
                f"real Bybit repair did not return accepted data: {result.outcome}"
            )
        print("Real-provider repair: repaired_ok")

        async with connections.provider_session("bybit") as provider:
            try:
                await provider.fetch_ohlcv_historical(
                    market=market_type,
                    symbol="LEONARDOINTENTIONALLYINVALIDUSDT",
                    timeframe=timeframe,
                    start_ms=start_ms,
                    end_ms=end_ms,
                    limit=1,
                )
            except HistoricalProviderRequestError as error:
                if error.retryable:
                    raise RuntimeError(
                        "Bybit invalid-symbol failure was incorrectly classified retryable"
                    ) from error
                print(
                    "Permanent provider failure classification: "
                    f"code={error.code!r}, retryable={error.retryable}"
                )
            else:
                raise RuntimeError("Bybit unexpectedly accepted the intentionally invalid symbol")

        print("TASK 1012 REAL-BYBIT SMOKE: PASS")


def main() -> None:
    args = _parser().parse_args()
    asyncio.run(_run(args.symbol, args.market, args.timeframe))


if __name__ == "__main__":
    main()
