"""Faithful result fields, paged access and display-only transformations."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import numpy as np
import pandas as pd
import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtWidgets import QApplication

from leonardo.analysis import AnalysisService
from leonardo.gui.analysis.binning_results import BinningResults
from leonardo.gui.display_time import DISPLAY_TIME_ZONE_PROPERTY
from tests.analysis_test.test_analysis_service import make_database, request

_APP = None


@pytest.fixture(scope='module')
def qapp():
    global _APP
    _APP = QApplication.instance() or QApplication([])
    return _APP


@pytest.fixture
def results_widget(qapp):
    widget = BinningResults()
    widget.resize(700,600)
    widget.show()
    yield widget
    widget.close()
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_paging_reaches_every_row_and_keeps_all_backend_fields(tmp_path, results_widget):
    values = np.linspace(-8,2,1003)
    values[[0,500,1002]] = np.nan
    store, manifest, _ = make_database(tmp_path, {'delta':values})
    result = AnalysisService(store).run(request(manifest,'delta'))
    widget = results_widget
    widget.set_result(result)
    model = widget.model
    assert len(model.names) == 35 and set(model.names) == set(result.columns[0].to_frame())
    assert model.rowCount() == 500 and model.page_count == 3
    seen = []
    for page in range(1,4):
        widget.page.setValue(page)
        seen.extend(model.headerData(row,Qt.Orientation.Vertical) for row in range(model.rowCount()))
    assert seen == list(map(str,range(1,1004)))
    assert model.rowCount() == 3 and not widget.next.isEnabled()
    raw_column = model.names.index('raw_value')
    assert model.data(model.index(2,raw_column)) == '—'
    status_column = model.names.index('status')
    assert model.data(model.index(2,status_column)) == 'missing_value'
    assert model.headerData(model.names.index('conditional_large_tail_frequency'), Qt.Orientation.Horizontal).startswith('Within-direction')
    assert model.headerData(model.names.index('whole_large_tail_frequency'), Qt.Orientation.Horizontal).startswith('Whole-reference')
    for name in model.names:
        assert model.headerData(model.names.index(name),Qt.Orientation.Horizontal,Qt.ItemDataRole.ToolTipRole) == name


def test_result_selection_does_not_mix_columns_or_recalculate(tmp_path, results_widget, monkeypatch):
    store, manifest, _ = make_database(tmp_path, {'delta':[-4,-1,0,1], 'positive':[1,2,4,8]})
    service = AnalysisService(store)
    result = service.run(request(manifest,'delta','positive'))
    monkeypatch.setattr(service,'run',lambda *a,**kw: pytest.fail('result selection recalculated'))
    widget = results_widget
    widget.set_result(result)
    widget.column.setCurrentIndex(1)
    pd.testing.assert_frame_equal(widget.model.frame, result.columns[1].to_frame())
    assert 'absent_reference' in widget.distribution_note.text()
    assert len(widget._current.bins) == 20
    assert sum(b.count for b in widget._current.bins if b.direction=='Negative') == 0
    widget.column.setCurrentIndex(0)
    pd.testing.assert_frame_equal(widget.model.frame,result.columns[0].to_frame())


@pytest.mark.parametrize('values', ([0,0,0],[-2,-2,-2],[1,2,3],[-1,-2,-3],[np.nan,np.nan,np.nan]))
def test_degenerate_one_sign_zero_and_missing_views_are_honest(tmp_path,results_widget,values):
    store,manifest,_ = make_database(tmp_path,{'delta':values})
    result = AnalysisService(store).run(request(manifest,'delta'))
    widget = results_widget
    widget.set_result(result)
    assert len(widget.model.frame)==len(values)
    if all(pd.isna(values)):
        assert widget.bins.rowCount()==0 and widget.chart._display.points==()
        assert widget._current.profile is None
    else:
        assert widget.bins.rowCount()==20
        for row,b in enumerate(result.columns[0].bins):
            assert int(widget.bins.item(row,4).text())==b.count
            if b.count==0:
                assert widget.bins.item(row,5).text()==widget.bins.item(row,6).text()=='—'
    assert not widget.grab().isNull()


def test_time_zone_refresh_changes_only_display(qapp,tmp_path,results_widget):
    store,manifest,_ = make_database(tmp_path)
    result=AnalysisService(store).run(request(manifest,'delta'))
    old=qapp.property(DISPLAY_TIME_ZONE_PROPERTY)
    try:
        qapp.setProperty(DISPLAY_TIME_ZONE_PROPERTY,'UTC')
        results_widget.set_result(result)
        frame=results_widget.model.frame.copy(deep=True)
        utc=results_widget.model.data(results_widget.model.index(0,0))
        qapp.setProperty(DISPLAY_TIME_ZONE_PROPERTY,'Europe/Rome')
        results_widget.refresh_display_time()
        local=results_widget.model.data(results_widget.model.index(0,0))
        assert utc!=local
        pd.testing.assert_frame_equal(results_widget.model.frame,frame)
        assert results_widget._result is result
    finally:
        qapp.setProperty(DISPLAY_TIME_ZONE_PROPERTY,old)
