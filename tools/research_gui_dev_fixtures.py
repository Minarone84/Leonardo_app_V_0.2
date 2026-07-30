"""Deterministic read-model fixtures for the restored Research GUI shell."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from leonardo.data import MarketId, timeframe_duration_ms
from leonardo.financial_tools import (
    ALL_FINANCIAL_TOOL_SPECS,
    FinancialToolCalculationResult,
)
from leonardo.gui.chart.interaction import CandlestickInteractionState
from leonardo.gui.windows.research_notebook_manager_dialog import (
    ResearchNotebookSnapshotAssignment,
)
from leonardo.research import (
    ChartStudy,
    HistoricalDataset,
    HorizontalViewport,
    RESEARCH_FINANCIAL_TOOL_SPECS,
    ResearchNotebookAnnotationSettingsV1,
    ResearchNotebookNoteV1,
    ResearchNotebookPageV1,
    ResearchNotebookPointOfInterestV1,
    ResearchNotebookPotentialTradeV1,
    ResearchNotebookSummary,
    ResearchNotebookV1,
    ResearchWorkspaceSnapshotSummary,
    ResearchWorkspaceSnapshotV1,
    ResidentOHLCVSlice,
    ResidentStudyProjection,
    StudyApplyAttempt,
    StudyEnvironmentEntryV1,
    StudyEnvironmentPresentationV1,
    StudyEnvironmentSummary,
    StudyEnvironmentV1,
    StudyFillStyle,
    StudyArtifactOption,
    StudyLineStyle,
    StudyManagerEntry,
    StudyPresentation,
    StudySetupCatalog,
    StudySetupDraft,
    StudySourceOption,
    WorkspaceSnapshotCapture,
    WorkspaceSnapshotChartCapture,
    WorkspaceSnapshotChartV1,
    WorkspaceSnapshotPaneSizeV1,
    WorkspaceSnapshotPriceScaleV1,
    WorkspaceSnapshotStateV1,
    WorkspaceSnapshotViewportV1,
    build_study_request,
)
from leonardo.research.catalog import AcceptedDatasetSummary
from leonardo.research.studies import build_chart_study


def _summary(
    market_id: MarketId,
    *,
    digest: str,
    row_count: int,
    first_timestamp_ms: int,
    last_timestamp_ms: int,
) -> AcceptedDatasetSummary:
    fixture_root = Path("task1026_research_gui_fixtures") / market_id.as_key()
    return AcceptedDatasetSummary(
        market_id=market_id,
        csv_path=fixture_root / "candles.csv",
        sidecar_path=fixture_root / "candles.meta.json",
        file_sha256=digest,
        row_count=row_count,
        first_timestamp_ms=first_timestamp_ms,
        last_timestamp_ms=last_timestamp_ms,
        source="task1026-dev-fixture",
        persistence_status="committed",
        validation_status="ok",
        warnings=(),
    )


RESEARCH_GUI_DATASET_FIXTURES = (
    _summary(
        MarketId("bybit", "linear", "BTCUSDT", "4h"),
        digest="1" * 64,
        row_count=1200,
        first_timestamp_ms=1_700_000_000_000,
        last_timestamp_ms=1_717_265_600_000,
    ),
    _summary(
        MarketId("bybit", "linear", "ETHUSDT", "1h"),
        digest="2" * 64,
        row_count=2400,
        first_timestamp_ms=1_700_000_000_000,
        last_timestamp_ms=1_708_636_400_000,
    ),
    _summary(
        MarketId("binance", "spot", "BTCUSDT", "15m"),
        digest="3" * 64,
        row_count=3600,
        first_timestamp_ms=1_700_000_000_000,
        last_timestamp_ms=1_703_239_100_000,
    ),
    _summary(
        MarketId("binance", "spot", "ETHUSDT", "1d"),
        digest="4" * 64,
        row_count=730,
        first_timestamp_ms=1_650_000_000_000,
        last_timestamp_ms=1_712_985_600_000,
    ),
)


@dataclass(frozen=True, slots=True)
class ResearchGuiDevChartFixture:
    market_id: MarketId
    interaction_state: CandlestickInteractionState
    study_projections: tuple[ResidentStudyProjection, ...]
    study_presentations: tuple[StudyPresentation, ...]
    study_entries: tuple[StudyManagerEntry, ...]


@dataclass(frozen=True, slots=True)
class ResearchGuiDevStudyEnvironmentBundle:
    chart_studies: tuple[ChartStudy, ...]
    environments: tuple[StudyEnvironmentV1, ...]
    summaries: tuple[StudyEnvironmentSummary, ...]


@dataclass(frozen=True, slots=True)
class ResearchGuiDevWorkspaceSnapshotBundle:
    capture: WorkspaceSnapshotCapture
    snapshots: tuple[ResearchWorkspaceSnapshotV1, ...]
    summaries: tuple[ResearchWorkspaceSnapshotSummary, ...]


@dataclass(frozen=True, slots=True)
class ResearchGuiDevNotebookBundle:
    notebooks: tuple[ResearchNotebookV1, ...]
    summaries: tuple[ResearchNotebookSummary, ...]
    assignments: tuple[ResearchNotebookSnapshotAssignment, ...]
    current_snapshot_id: str


def build_primary_chart_fixture() -> ResearchGuiDevChartFixture:
    """Build one deterministic in-memory chart presentation fixture."""

    market_id = MarketId("bybit", "linear", "BTCUSDT", "4h")
    count = 240
    step_ms = 4 * 60 * 60 * 1000
    timestamps = tuple(1_700_000_000_000 + index * step_ms for index in range(count))
    opens = tuple(
        42_000.0 + index * 18.0 + 760.0 * math.sin(index / 11.0)
        for index in range(count)
    )
    closes = tuple(
        value + 120.0 * math.sin(index / 3.7)
        for index, value in enumerate(opens)
    )
    highs = tuple(
        max(open_value, close_value) + 210.0 + 30.0 * abs(math.cos(index / 5.0))
        for index, (open_value, close_value) in enumerate(zip(opens, closes, strict=True))
    )
    lows = tuple(
        min(open_value, close_value) - 210.0 - 30.0 * abs(math.sin(index / 6.0))
        for index, (open_value, close_value) in enumerate(zip(opens, closes, strict=True))
    )
    volumes = tuple(
        1_200.0 + 350.0 * (1.0 + math.sin(index / 7.0)) + index * 2.5
        for index in range(count)
    )
    fingerprint = "7" * 64
    resident = ResidentOHLCVSlice(
        market_id=market_id,
        dataset_fingerprint=fingerprint,
        base_index=0,
        end_index_exclusive=count,
        ts_ms=timestamps,
        open=opens,
        high=highs,
        low=lows,
        close=closes,
        volume=volumes,
        has_more_left=False,
        has_more_right=False,
        first_timestamp_ms=timestamps[0],
        last_timestamp_ms=timestamps[-1],
    )
    viewport = HorizontalViewport(
        count,
        visible_count=120,
        left_padding=0,
        right_padding=0,
    )
    interaction_state = CandlestickInteractionState(viewport, resident)

    sma = _rolling_mean(closes, 20)
    bb_middle = sma
    bb_upper = tuple(value + 620.0 for value in bb_middle)
    bb_lower = tuple(value - 620.0 for value in bb_middle)
    rsi = tuple(50.0 + 34.0 * math.sin(index / 8.0) for index in range(count))
    volume_mean = _rolling_mean(volumes, 20)

    projections = (
        _projection("dev-sma", market_id, fingerprint, timestamps, "price", {"sma_20": sma}),
        _projection(
            "dev-bb",
            market_id,
            fingerprint,
            timestamps,
            "price",
            {
                "bb_middle": bb_middle,
                "bb_upper_band": bb_upper,
                "bb_lower_band": bb_lower,
            },
        ),
        _projection(
            "dev-rsi",
            market_id,
            fingerprint,
            timestamps,
            "oscillator",
            {"rsi_14": rsi},
        ),
        _projection(
            "dev-volume",
            market_id,
            fingerprint,
            timestamps,
            "oscillator",
            {"volume": volumes, "volume_mean_20": volume_mean},
        ),
    )
    presentations = (
        StudyPresentation(
            "dev-sma",
            True,
            "price",
            {"sma_20": StudyLineStyle("sma_20", "#F59E0B")},
            {},
        ),
        StudyPresentation(
            "dev-bb",
            True,
            "price",
            {
                "bb_middle": StudyLineStyle("bb_middle", "#F59E0B"),
                "bb_upper_band": StudyLineStyle(
                    "bb_upper_band", "#60A5FA", line_pattern="dashed"
                ),
                "bb_lower_band": StudyLineStyle(
                    "bb_lower_band", "#60A5FA", line_pattern="dashed"
                ),
            },
            {
                "bb_band": StudyFillStyle(
                    "bb_band",
                    "bb_upper_band",
                    "bb_lower_band",
                    "#60A5FA",
                    opacity=0.12,
                )
            },
        ),
        StudyPresentation(
            "dev-rsi",
            True,
            "oscillator:dev-rsi",
            {"rsi_14": StudyLineStyle("rsi_14", "#A855F7")},
            {},
        ),
        StudyPresentation(
            "dev-volume",
            True,
            "oscillator:dev-volume",
            {
                "volume": StudyLineStyle("volume", "#22D3EE"),
                "volume_mean_20": StudyLineStyle("volume_mean_20", "#F97316"),
            },
            {},
        ),
    )
    entries = (
        _entry("dev-sma", "SMA 20", "sma", "price"),
        _entry("dev-bb", "BB 20 / 2", "bb", "price"),
        _entry("dev-rsi", "RSI 14", "rsi", "oscillator:dev-rsi"),
        _entry("dev-volume", "Volume", "volume", "oscillator:dev-volume"),
    )
    return ResearchGuiDevChartFixture(
        market_id=market_id,
        interaction_state=interaction_state,
        study_projections=projections,
        study_presentations=presentations,
        study_entries=entries,
    )


def build_additional_workspace_chart_fixtures(
) -> tuple[ResearchGuiDevChartFixture, ...]:
    """Build the seven independent fixtures for workspace slots 2 through 8."""

    markets = (
        MarketId("bybit", "linear", "ETHUSDT", "1h"),
        MarketId("binance", "spot", "BTCUSDT", "15m"),
        MarketId("binance", "spot", "ETHUSDT", "1d"),
        MarketId("bybit", "linear", "BTCUSDT", "4h"),
        MarketId("bybit", "linear", "ETHUSDT", "1h"),
        MarketId("binance", "spot", "BTCUSDT", "15m"),
        MarketId("binance", "spot", "ETHUSDT", "1d"),
    )
    return tuple(
        _build_additional_chart_fixture(slot_id, market_id)
        for slot_id, market_id in enumerate(markets, start=2)
    )


def build_chart_fixture_for_market(
    market_id: MarketId,
    *,
    slot_id: int,
) -> ResearchGuiDevChartFixture:
    """Build independent deterministic chart state for one accepted market."""

    if not isinstance(market_id, MarketId):
        raise TypeError("market_id must be a MarketId")
    if type(slot_id) is not int or not 1 <= slot_id <= 8:
        raise ValueError("slot_id must be an integer from 1 through 8")
    primary_market = MarketId("bybit", "linear", "BTCUSDT", "4h")
    if slot_id == 1 and market_id == primary_market:
        return build_primary_chart_fixture()
    return _build_additional_chart_fixture(slot_id, market_id)


def build_study_setup_catalog_fixture(
    chart_fixture: ResearchGuiDevChartFixture,
) -> StudySetupCatalog:
    """Build one deterministic in-memory Study Setup catalog."""

    if not isinstance(chart_fixture, ResearchGuiDevChartFixture):
        raise TypeError("chart_fixture must be a ResearchGuiDevChartFixture")
    projection_by_id = {
        projection.study_id: projection
        for projection in chart_fixture.study_projections
    }
    study_sources = tuple(
        StudySourceOption(
            source_kind="study",
            label=f"{entry.display_name}: {output_name}",
            family=ALL_FINANCIAL_TOOL_SPECS[entry.tool_key].kind,
            study_id=entry.study_id,
            output_name=output_name,
        )
        for entry in chart_fixture.study_entries
        for output_name in projection_by_id[entry.study_id].render_series
    )
    return StudySetupCatalog(
        market_id=chart_fixture.market_id,
        tools=RESEARCH_FINANCIAL_TOOL_SPECS,
        ohlcv_sources=tuple(
            StudySourceOption(
                source_kind="ohlcv",
                label=label,
                family="ohlcv",
                column_name=column_name,
            )
            for label, column_name in (
                ("Open", "open"),
                ("High", "high"),
                ("Low", "low"),
                ("Close", "close"),
                ("Volume", "volume"),
            )
        ),
        study_sources=study_sources,
        artifact_options=(
            StudyArtifactOption(
                chart_fixture.market_id,
                "e6423b7911b3b62c73cc66dc134d615b4984f3c49b93e65d594ebab906b60992",
                "indicator",
                "sma",
                "Saved SMA 20",
                ("sma_20",),
                parameters={"period": 20},
            ),
            StudyArtifactOption(
                chart_fixture.market_id,
                "ec7c06a96d8bfe7c658765e2d9ce3707ac291e5514dbad6858ea5f801e39ac31",
                "oscillator",
                "rsi",
                "Saved RSI 14",
                ("rsi_14",),
                parameters={"period": 14},
            ),
        ),
        artifact_rejections=(),
    )


def build_study_environment_gui_fixtures(
    chart_fixture: ResearchGuiDevChartFixture,
) -> ResearchGuiDevStudyEnvironmentBundle:
    """Build deterministic in-memory Study Environment GUI projections."""

    if not isinstance(chart_fixture, ResearchGuiDevChartFixture):
        raise TypeError("chart_fixture must be a ResearchGuiDevChartFixture")
    catalog = build_study_setup_catalog_fixture(chart_fixture)
    studies = (
        _build_environment_chart_study(
            chart_fixture,
            catalog,
            tool_key="sma",
            period=20,
            study_id="dev-env-sma",
            display_name="SMA 20",
        ),
        _build_environment_chart_study(
            chart_fixture,
            catalog,
            tool_key="rsi",
            period=14,
            study_id="dev-env-rsi",
            display_name="RSI 14",
        ),
    )
    presentations = (
        StudyEnvironmentPresentationV1(
            True,
            (StudyLineStyle("sma_20", "#F59E0B"),),
            (),
        ),
        StudyEnvironmentPresentationV1(
            True,
            (StudyLineStyle("rsi_14", "#A855F7"),),
            (),
        ),
    )
    entries = tuple(
        StudyEnvironmentEntryV1(
            entry_id=entry_id,
            mode="calculation",
            kind=study.result.kind,
            tool_key=study.result.tool_key,
            display_name=study.display_name,
            parameters=dict(study.result.parameters),
            sources=(),
            artifact_id=None,
            expected_output_names=study.result.output_names,
            user_metadata=study.user_metadata,
            presentation=presentation,
        )
        for entry_id, study, presentation in zip(
            ("env_sma", "env_rsi"), studies, presentations, strict=True
        )
    )
    timestamp = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    environment = StudyEnvironmentV1.build(
        environment_id="dev_env_core",
        display_name="Core Research Environment",
        description="SMA 20 and RSI 14 development environment.",
        created_at_utc=timestamp,
        updated_at_utc=timestamp,
        created_from=chart_fixture.market_id,
        entries=entries,
    )
    summaries = (
        StudyEnvironmentSummary(
            environment.environment_id,
            environment.display_name,
            environment.description,
            len(environment.entries),
            environment.created_at_utc,
            environment.updated_at_utc,
        ),
        StudyEnvironmentSummary(
            "dev_env_invalid",
            "Invalid Development Environment",
            "",
            0,
            None,
            None,
            False,
            "Invalid development fixture",
        ),
    )
    return ResearchGuiDevStudyEnvironmentBundle(
        chart_studies=studies,
        environments=(environment,),
        summaries=summaries,
    )


def build_workspace_snapshot_gui_fixtures(
    primary_fixture: ResearchGuiDevChartFixture,
    secondary_fixture: ResearchGuiDevChartFixture,
    environment_bundle: ResearchGuiDevStudyEnvironmentBundle,
) -> ResearchGuiDevWorkspaceSnapshotBundle:
    """Build deterministic in-memory Workspace Snapshot GUI projections."""

    if not isinstance(primary_fixture, ResearchGuiDevChartFixture):
        raise TypeError("primary_fixture must be a ResearchGuiDevChartFixture")
    if not isinstance(secondary_fixture, ResearchGuiDevChartFixture):
        raise TypeError("secondary_fixture must be a ResearchGuiDevChartFixture")
    if not isinstance(environment_bundle, ResearchGuiDevStudyEnvironmentBundle):
        raise TypeError(
            "environment_bundle must be a ResearchGuiDevStudyEnvironmentBundle"
        )
    environment = environment_bundle.environments[0]
    primary_dataset = _historical_dataset_from_fixture(primary_fixture)
    secondary_dataset = _historical_dataset_from_fixture(secondary_fixture)
    primary_resident = primary_fixture.interaction_state.resident
    secondary_resident = secondary_fixture.interaction_state.resident
    if primary_resident is None or secondary_resident is None:
        raise RuntimeError("Workspace Snapshot fixtures require resident OHLCV")
    primary_viewport = WorkspaceSnapshotViewportV1(
        primary_resident.ts_ms[primary_resident.row_count // 2],
        primary_fixture.interaction_state.viewport.visible_count,
    )
    secondary_viewport = WorkspaceSnapshotViewportV1(
        secondary_resident.ts_ms[secondary_resident.row_count // 2],
        secondary_fixture.interaction_state.viewport.visible_count,
    )
    price_scale = WorkspaceSnapshotPriceScaleV1(True)
    study_presentations = (
        StudyPresentation(
            "dev-env-sma",
            True,
            "price",
            {"sma_20": StudyLineStyle("sma_20", "#F59E0B")},
            {},
        ),
        StudyPresentation(
            "dev-env-rsi",
            True,
            "oscillator:dev-env-rsi",
            {"rsi_14": StudyLineStyle("rsi_14", "#A855F7")},
            {},
        ),
    )
    capture = WorkspaceSnapshotCapture(
        "scroll_4",
        False,
        "chart_001",
        (
            WorkspaceSnapshotChartCapture(
                "chart_001",
                1,
                False,
                primary_fixture.market_id,
                primary_dataset,
                environment_bundle.chart_studies,
                study_presentations,
                primary_viewport,
                price_scale,
                False,
                {"price": 720, "study:env_rsi": 240},
            ),
            WorkspaceSnapshotChartCapture(
                "chart_002",
                2,
                False,
                secondary_fixture.market_id,
                secondary_dataset,
                (),
                (),
                secondary_viewport,
                price_scale,
                False,
                {"price": 720},
            ),
        ),
    )
    primary_chart = WorkspaceSnapshotChartV1(
        "chart_001",
        1,
        False,
        primary_fixture.market_id,
        primary_viewport,
        price_scale,
        False,
        (
            WorkspaceSnapshotPaneSizeV1("price", 720),
            WorkspaceSnapshotPaneSizeV1("study:env_rsi", 240),
        ),
        environment,
    )
    secondary_chart = WorkspaceSnapshotChartV1(
        "chart_002",
        2,
        False,
        secondary_fixture.market_id,
        secondary_viewport,
        price_scale,
        False,
        (WorkspaceSnapshotPaneSizeV1("price", 720),),
        None,
    )
    first_timestamp = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    second_timestamp = datetime(2026, 1, 2, 12, 0, tzinfo=timezone.utc)
    primary_snapshot = ResearchWorkspaceSnapshotV1.build(
        snapshot_id="dev_snapshot_primary",
        display_name="Morning Research Workspace",
        description="Two-chart development Workspace Snapshot.",
        created_at_utc=first_timestamp,
        updated_at_utc=first_timestamp,
        workspace=WorkspaceSnapshotStateV1("scroll_4", False, "chart_001"),
        charts=(primary_chart, secondary_chart),
    )
    secondary_snapshot = ResearchWorkspaceSnapshotV1.build(
        snapshot_id="dev_snapshot_secondary",
        display_name="Secondary Research Workspace",
        description="Single-chart development Workspace Snapshot.",
        created_at_utc=second_timestamp,
        updated_at_utc=second_timestamp,
        workspace=WorkspaceSnapshotStateV1("fit_8", False, "chart_001"),
        charts=(
            WorkspaceSnapshotChartV1(
                "chart_001",
                1,
                False,
                primary_fixture.market_id,
                primary_viewport,
                price_scale,
                False,
                (WorkspaceSnapshotPaneSizeV1("price", 720),),
                None,
            ),
        ),
    )
    summaries = (
        _workspace_snapshot_summary(primary_snapshot),
        _workspace_snapshot_summary(secondary_snapshot),
        ResearchWorkspaceSnapshotSummary(
            "dev_snapshot_invalid",
            "Invalid Development Snapshot",
            "",
            0,
            None,
            None,
            False,
            "Invalid development fixture",
        ),
    )
    return ResearchGuiDevWorkspaceSnapshotBundle(
        capture=capture,
        snapshots=(primary_snapshot, secondary_snapshot),
        summaries=summaries,
    )


def build_notebook_gui_fixtures(
    primary_market_id: MarketId,
    secondary_market_id: MarketId,
) -> ResearchGuiDevNotebookBundle:
    """Build deterministic in-memory Research Notebook GUI projections."""

    if not isinstance(primary_market_id, MarketId):
        raise TypeError("primary_market_id must be a MarketId")
    if not isinstance(secondary_market_id, MarketId):
        raise TypeError("secondary_market_id must be a MarketId")
    timestamp = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    primary_page = ResearchNotebookPageV1(
        primary_market_id,
        notes=(
            ResearchNotebookNoteV1(
                "note_market_structure", None, "Review current market structure."
            ),
        ),
        potential_trades=(
            ResearchNotebookPotentialTradeV1(
                "trade_breakout",
                1_767_268_800_000,
                "long",
                42_500.0,
                44_000.0,
                41_800.0,
                "planned",
                "pending",
                "Watch for breakout confirmation.",
            ),
        ),
        points_of_interest=(
            ResearchNotebookPointOfInterestV1(
                "poi_support_zone",
                1_767_272_400_000,
                42_000.0,
                "Support zone",
                "Primary support area.",
            ),
        ),
    )
    primary = ResearchNotebookV1.build(
        notebook_id="dev_notebook_market_review",
        display_name="BTC Market Review",
        description="Primary Research notebook development fixture.",
        created_at_utc=timestamp,
        updated_at_utc=timestamp,
        annotation_settings=ResearchNotebookAnnotationSettingsV1(),
        pages=(primary_page,),
    )
    secondary = ResearchNotebookV1.build(
        notebook_id="dev_notebook_eth_notes",
        display_name="ETH Research Notes",
        description="Secondary Research notebook development fixture.",
        created_at_utc=timestamp,
        updated_at_utc=timestamp,
        annotation_settings=ResearchNotebookAnnotationSettingsV1(),
        pages=(
            ResearchNotebookPageV1(
                secondary_market_id,
                notes=(
                    ResearchNotebookNoteV1(
                        "note_eth_structure", None, "Review ETH market structure."
                    ),
                ),
            ),
        ),
    )
    summaries = (
        _notebook_summary(primary),
        _notebook_summary(secondary),
        ResearchNotebookSummary(
            "dev_notebook_invalid",
            "Invalid Development Notebook",
            "",
            None,
            None,
            0,
            0,
            0,
            0,
            (),
            False,
            "Invalid development fixture",
        ),
    )
    assignments = (
        ResearchNotebookSnapshotAssignment(
            "dev_snapshot_primary",
            "Morning Research Workspace",
            "dev_notebook_market_review",
        ),
        ResearchNotebookSnapshotAssignment(
            "dev_snapshot_secondary",
            "Secondary Research Workspace",
            None,
        ),
    )
    return ResearchGuiDevNotebookBundle(
        notebooks=(primary, secondary),
        summaries=summaries,
        assignments=assignments,
        current_snapshot_id="dev_snapshot_primary",
    )


def _build_environment_chart_study(
    chart_fixture: ResearchGuiDevChartFixture,
    catalog: StudySetupCatalog,
    *,
    tool_key: str,
    period: int,
    study_id: str,
    display_name: str,
) -> ChartStudy:
    source_entry = next(
        entry for entry in chart_fixture.study_entries if entry.tool_key == tool_key
    )
    source_projection = next(
        projection
        for projection in chart_fixture.study_projections
        if projection.study_id == source_entry.study_id
    )
    request = build_study_request(
        StudySetupDraft(
            "calculation",
            tool_key,
            {"period": period},
            display_name=display_name,
        ),
        catalog,
    )
    output_name = next(iter(source_projection.render_series))
    frame = pd.DataFrame(
        {
            "ts_ms": np.asarray(source_projection.ts_ms, dtype="int64"),
            output_name: np.asarray(
                source_projection.render_series[output_name], dtype="float32"
            ),
        }
    )
    result = FinancialToolCalculationResult(
        tool_key=tool_key,
        kind=ALL_FINANCIAL_TOOL_SPECS[tool_key].kind,
        parameters=request.parameters,
        bindings={},
        output_names=(output_name,),
        frame=frame,
    )
    resident = chart_fixture.interaction_state.resident
    if resident is None:
        raise RuntimeError("Study Environment fixture requires resident OHLCV")
    return build_chart_study(
        attempt=StudyApplyAttempt(
            "dev_environment_session",
            1,
            f"dev-request-{tool_key}",
            study_id,
            chart_fixture.market_id,
            resident.dataset_fingerprint,
        ),
        source_kind="calculation",
        display_name=display_name,
        result=result,
        setup_request=request,
    )


def _historical_dataset_from_fixture(
    chart_fixture: ResearchGuiDevChartFixture,
) -> HistoricalDataset:
    resident = chart_fixture.interaction_state.resident
    if resident is None:
        raise RuntimeError("Workspace Snapshot fixture requires resident OHLCV")
    return HistoricalDataset(
        chart_fixture.market_id,
        Path("task1031_workspace_snapshot_fixtures")
        / chart_fixture.market_id.as_key()
        / "candles.csv",
        resident.dataset_fingerprint,
        resident.row_count,
        resident.first_timestamp_ms,
        resident.last_timestamp_ms,
        resident.ts_ms,
        resident.open,
        resident.high,
        resident.low,
        resident.close,
        resident.volume,
    )


def _workspace_snapshot_summary(
    snapshot: ResearchWorkspaceSnapshotV1,
) -> ResearchWorkspaceSnapshotSummary:
    return ResearchWorkspaceSnapshotSummary(
        snapshot.snapshot_id,
        snapshot.display_name,
        snapshot.description,
        len(snapshot.charts),
        snapshot.created_at_utc,
        snapshot.updated_at_utc,
    )


def _notebook_summary(notebook: ResearchNotebookV1) -> ResearchNotebookSummary:
    return ResearchNotebookSummary(
        notebook.notebook_id,
        notebook.display_name,
        notebook.description,
        notebook.created_at_utc,
        notebook.updated_at_utc,
        len(notebook.pages),
        sum(len(page.notes) for page in notebook.pages),
        sum(len(page.potential_trades) for page in notebook.pages),
        sum(len(page.points_of_interest) for page in notebook.pages),
        tuple(page.market_id for page in notebook.pages),
    )


def _build_additional_chart_fixture(
    slot_id: int, market_id: MarketId
) -> ResearchGuiDevChartFixture:
    primary = build_primary_chart_fixture()
    source = primary.interaction_state.resident
    if source is None:
        raise RuntimeError("primary Research fixture must contain resident OHLCV")
    step_ms = timeframe_duration_ms(market_id.timeframe)
    if step_ms is None:
        raise RuntimeError("workspace fixture timeframe must have a fixed duration")
    timestamps = tuple(
        source.ts_ms[0] + index * step_ms for index in range(source.row_count)
    )
    fingerprint = str(slot_id) * 64
    resident = ResidentOHLCVSlice(
        market_id=market_id,
        dataset_fingerprint=fingerprint,
        base_index=source.base_index,
        end_index_exclusive=source.end_index_exclusive,
        ts_ms=timestamps,
        open=source.open,
        high=source.high,
        low=source.low,
        close=source.close,
        volume=source.volume,
        has_more_left=source.has_more_left,
        has_more_right=source.has_more_right,
        first_timestamp_ms=timestamps[0],
        last_timestamp_ms=timestamps[-1],
    )
    viewport = HorizontalViewport(
        resident.row_count,
        visible_count=primary.interaction_state.viewport.visible_count,
        left_padding=0,
        right_padding=0,
    )
    interaction_state = CandlestickInteractionState(viewport, resident)
    replacements = {
        item.study_id: f"dev{slot_id}-{item.study_id.removeprefix('dev-')}"
        for item in primary.study_projections
    }
    projections = tuple(
        ResidentStudyProjection(
            study_id=replacements[item.study_id],
            market_id=market_id,
            dataset_fingerprint=fingerprint,
            pane_role=item.pane_role,
            base_index=item.base_index,
            end_index_exclusive=item.end_index_exclusive,
            ts_ms=timestamps,
            render_series=item.render_series,
            style_driver_series=item.style_driver_series,
        )
        for item in primary.study_projections
    )
    presentations = tuple(
        StudyPresentation(
            study_id=replacements[item.study_id],
            visible=item.visible,
            pane_id=(
                f"oscillator:{replacements[item.study_id]}"
                if item.pane_id is not None
                and item.pane_id.startswith("oscillator:")
                else item.pane_id
            ),
            signal_styles=item.signal_styles,
            fill_styles=item.fill_styles,
            revision=item.revision,
        )
        for item in primary.study_presentations
    )
    entries = tuple(
        StudyManagerEntry(
            study_id=replacements[item.study_id],
            display_name=item.display_name,
            tool_key=item.tool_key,
            tool_title=item.tool_title,
            source_kind=item.source_kind,
            saved=item.saved,
            visible=item.visible,
            pane_id=(
                f"oscillator:{replacements[item.study_id]}"
                if item.pane_id is not None
                and item.pane_id.startswith("oscillator:")
                else item.pane_id
            ),
            pane_label=item.pane_label,
            dependent_study_ids=tuple(
                replacements[dependent]
                for dependent in item.dependent_study_ids
            ),
            compact_label=item.compact_label,
            parameter_summary=item.parameter_summary,
            parameter_details=item.parameter_details,
            source_summary=item.source_summary,
            source_details=item.source_details,
            origin_label=item.origin_label,
        )
        for item in primary.study_entries
    )
    return ResearchGuiDevChartFixture(
        market_id=market_id,
        interaction_state=interaction_state,
        study_projections=projections,
        study_presentations=presentations,
        study_entries=entries,
    )


def _rolling_mean(values: tuple[float, ...], period: int) -> tuple[float, ...]:
    output: list[float] = []
    for index in range(len(values)):
        start = max(0, index - period + 1)
        window = values[start : index + 1]
        output.append(sum(window) / len(window))
    return tuple(output)


def _projection(
    study_id: str,
    market_id: MarketId,
    fingerprint: str,
    timestamps: tuple[int, ...],
    pane_role: str,
    render_series: dict[str, tuple[float, ...]],
) -> ResidentStudyProjection:
    return ResidentStudyProjection(
        study_id=study_id,
        market_id=market_id,
        dataset_fingerprint=fingerprint,
        pane_role=pane_role,
        base_index=0,
        end_index_exclusive=len(timestamps),
        ts_ms=timestamps,
        render_series=render_series,
        style_driver_series={},
    )


def _entry(
    study_id: str,
    display_name: str,
    tool_key: str,
    pane_id: str,
) -> StudyManagerEntry:
    presentation = {
        "sma": (
            "SMA 20",
            "period=20",
            "Period: 20",
            "OHLCV: CLOSE",
            "OHLCV inputs: close",
        ),
        "bb": (
            "BB 20 2",
            "period=20; std=2",
            "Period: 20\nStd Dev Multiplier: 2",
            "OHLCV: CLOSE",
            "OHLCV inputs: close",
        ),
        "rsi": (
            "RSI 14",
            "period=14",
            (
                "Period: 14\nGuide levels:\n"
                "Oversold: 30\nCenter: 50\nOverbought: 70"
            ),
            "OHLCV: CLOSE",
            "OHLCV inputs: close",
        ),
        "volume": (
            "Volume 20",
            "period=20",
            "Mean Period: 20",
            "OHLCV: VOLUME",
            "OHLCV inputs: volume",
        ),
    }[tool_key]
    return StudyManagerEntry(
        study_id=study_id,
        display_name=display_name,
        tool_key=tool_key,
        tool_title=display_name,
        source_kind="calculation",
        saved=False,
        visible=True,
        pane_id=pane_id,
        pane_label="Price" if pane_id == "price" else "Oscillator",
        dependent_study_ids=(),
        compact_label=presentation[0],
        parameter_summary=presentation[1],
        parameter_details=presentation[2],
        source_summary=presentation[3],
        source_details=presentation[4],
        origin_label="Calculated",
    )
