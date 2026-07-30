"""Accepted-dataset selector for one new restored Research chart."""

from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from leonardo.research.catalog import AcceptedDatasetSummary


class ResearchNewChartDialog(QDialog):
    """Select one exact supplied accepted dataset through a guided cascade."""

    def __init__(
        self,
        dataset_summaries: Iterable[AcceptedDatasetSummary],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._dataset_summaries: tuple[AcceptedDatasetSummary, ...] = ()
        self._selected_summary: AcceptedDatasetSummary | None = None

        self.setObjectName("research_restoration.new_chart_dialog")
        self.setWindowTitle("New Research Chart")
        self.setModal(True)
        self.resize(460, 240)

        self.info_label = QLabel(
            "Select exchange, market type, asset, and timeframe in order.", self
        )
        self.info_label.setObjectName("research_restoration.new_chart.info")
        self.info_label.setWordWrap(True)

        self.exchange_combo = QComboBox(self)
        self.exchange_combo.setObjectName("research_restoration.new_chart.exchange")
        self.market_type_combo = QComboBox(self)
        self.market_type_combo.setObjectName(
            "research_restoration.new_chart.market_type"
        )
        self.asset_combo = QComboBox(self)
        self.asset_combo.setObjectName("research_restoration.new_chart.asset")
        self.timeframe_combo = QComboBox(self)
        self.timeframe_combo.setObjectName(
            "research_restoration.new_chart.timeframe"
        )
        for combo in (
            self.exchange_combo,
            self.market_type_combo,
            self.asset_combo,
            self.timeframe_combo,
        ):
            combo.addItem("", "")

        self.create_button = QPushButton("Create Chart", self)
        self.create_button.setObjectName("research_restoration.new_chart.create")
        self.create_button.setEnabled(False)
        self.cancel_button = QPushButton("Cancel", self)
        self.cancel_button.setObjectName("research_restoration.new_chart.cancel")

        form = QFormLayout()
        form.addRow("Exchange", self.exchange_combo)
        form.addRow("Market Type", self.market_type_combo)
        form.addRow("Asset", self.asset_combo)
        form.addRow("Timeframe", self.timeframe_combo)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.create_button)
        buttons.addWidget(self.cancel_button)

        layout = QVBoxLayout(self)
        layout.addWidget(self.info_label)
        layout.addLayout(form)
        layout.addStretch(1)
        layout.addLayout(buttons)

        self.market_type_combo.setEnabled(False)
        self.asset_combo.setEnabled(False)
        self.timeframe_combo.setEnabled(False)
        self.exchange_combo.currentIndexChanged.connect(
            self._on_exchange_changed
        )
        self.market_type_combo.currentIndexChanged.connect(
            self._on_market_type_changed
        )
        self.asset_combo.currentIndexChanged.connect(self._on_asset_changed)
        self.timeframe_combo.currentIndexChanged.connect(
            self._on_timeframe_changed
        )
        self.create_button.clicked.connect(self._accept_selection)
        self.cancel_button.clicked.connect(self.reject)
        self.set_dataset_summaries(dataset_summaries)

    def selected_dataset_summary(self) -> AcceptedDatasetSummary | None:
        return self._selected_summary

    def set_dataset_summaries(
        self, summaries: Iterable[AcceptedDatasetSummary]
    ) -> None:
        snapshot = tuple(summaries)
        if not all(isinstance(item, AcceptedDatasetSummary) for item in snapshot):
            raise TypeError(
                "summaries must contain AcceptedDatasetSummary values"
            )
        identities = tuple(item.market_id for item in snapshot)
        if len(set(identities)) != len(identities):
            raise ValueError("summaries must have unique MarketId identities")
        self._dataset_summaries = tuple(
            sorted(
                snapshot,
                key=lambda item: (
                    item.market_id.exchange,
                    item.market_id.market_type,
                    item.market_id.symbol,
                    item.market_id.timeframe,
                ),
            )
        )
        self.exchange_combo.blockSignals(True)
        self.exchange_combo.clear()
        self.exchange_combo.addItem("", "")
        self.exchange_combo.blockSignals(False)
        self._populate_exchanges()
        self.reset_selection()

    def reset_selection(self) -> None:
        """Restore the initial blank cascade without rebuilding the catalog."""
        self._selected_summary = None
        self.exchange_combo.blockSignals(True)
        self.exchange_combo.setCurrentIndex(0)
        self.exchange_combo.blockSignals(False)
        self._reset_combo(self.market_type_combo)
        self._reset_combo(self.asset_combo)
        self._reset_combo(self.timeframe_combo)
        has_datasets = bool(self._dataset_summaries)
        self.exchange_combo.setEnabled(has_datasets)
        self.market_type_combo.setEnabled(False)
        self.asset_combo.setEnabled(False)
        self.timeframe_combo.setEnabled(False)
        self.create_button.setEnabled(False)
        self.info_label.setText(
            "Select an exchange to continue."
            if has_datasets
            else "No accepted OHLCV datasets are available for Research."
        )

    def _populate_exchanges(self) -> None:
        exchanges = sorted(
            {item.market_id.exchange for item in self._dataset_summaries}
        )
        for exchange in exchanges:
            self.exchange_combo.addItem(
                exchange[:1].upper() + exchange[1:], exchange
            )
        self.exchange_combo.setEnabled(bool(exchanges))
        self.info_label.setText(
            "Select an exchange to continue."
            if exchanges
            else "No accepted OHLCV datasets are available for Research."
        )

    def _on_exchange_changed(self) -> None:
        exchange = self._current_data(self.exchange_combo)
        self._reset_combo(self.market_type_combo)
        self._reset_combo(self.asset_combo)
        self._reset_combo(self.timeframe_combo)
        self.asset_combo.setEnabled(False)
        self.timeframe_combo.setEnabled(False)
        self.create_button.setEnabled(False)
        if not exchange:
            self.market_type_combo.setEnabled(False)
            self.info_label.setText("Select an exchange to continue.")
            return
        values = sorted(
            {
                item.market_id.market_type
                for item in self._dataset_summaries
                if item.market_id.exchange == exchange
            }
        )
        self._add_values(self.market_type_combo, values)
        self.market_type_combo.setEnabled(bool(values))
        self.info_label.setText("Select a market type.")

    def _on_market_type_changed(self) -> None:
        exchange = self._current_data(self.exchange_combo)
        market_type = self._current_data(self.market_type_combo)
        self._reset_combo(self.asset_combo)
        self._reset_combo(self.timeframe_combo)
        self.timeframe_combo.setEnabled(False)
        self.create_button.setEnabled(False)
        if not exchange or not market_type:
            self.asset_combo.setEnabled(False)
            self.info_label.setText("Select a market type.")
            return
        values = sorted(
            {
                item.market_id.symbol
                for item in self._dataset_summaries
                if item.market_id.exchange == exchange
                and item.market_id.market_type == market_type
            }
        )
        self._add_values(self.asset_combo, values)
        self.asset_combo.setEnabled(bool(values))
        self.info_label.setText("Select an asset.")

    def _on_asset_changed(self) -> None:
        exchange = self._current_data(self.exchange_combo)
        market_type = self._current_data(self.market_type_combo)
        asset = self._current_data(self.asset_combo)
        self._reset_combo(self.timeframe_combo)
        self.create_button.setEnabled(False)
        if not exchange or not market_type or not asset:
            self.timeframe_combo.setEnabled(False)
            self.info_label.setText("Select an asset.")
            return
        values = sorted(
            {
                item.market_id.timeframe
                for item in self._dataset_summaries
                if item.market_id.exchange == exchange
                and item.market_id.market_type == market_type
                and item.market_id.symbol == asset
            }
        )
        self._add_values(self.timeframe_combo, values)
        self.timeframe_combo.setEnabled(bool(values))
        self.info_label.setText("Select a timeframe.")

    def _on_timeframe_changed(self) -> None:
        selected = self._resolve_current_summary()
        self.create_button.setEnabled(selected is not None)
        self.info_label.setText(
            "Selection complete. Create Chart is available."
            if selected is not None
            else "Select a timeframe."
        )

    def _accept_selection(self) -> None:
        selected = self._resolve_current_summary()
        if selected is None:
            return
        self._selected_summary = selected
        self.accept()

    def _resolve_current_summary(self) -> AcceptedDatasetSummary | None:
        selected = (
            self._current_data(self.exchange_combo),
            self._current_data(self.market_type_combo),
            self._current_data(self.asset_combo),
            self._current_data(self.timeframe_combo),
        )
        if not all(selected):
            return None
        for summary in self._dataset_summaries:
            market = summary.market_id
            if selected == (
                market.exchange,
                market.market_type,
                market.symbol,
                market.timeframe,
            ):
                return summary
        return None

    @staticmethod
    def _current_data(combo: QComboBox) -> str:
        value = combo.currentData()
        return value if isinstance(value, str) else ""

    @staticmethod
    def _reset_combo(combo: QComboBox) -> None:
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("", "")
        combo.setCurrentIndex(0)
        combo.blockSignals(False)

    @staticmethod
    def _add_values(combo: QComboBox, values: Iterable[str]) -> None:
        for value in values:
            combo.addItem(value, value)
