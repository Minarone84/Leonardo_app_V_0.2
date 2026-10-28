"""Compare against a captured accepted checkout, never against Git HEAD."""
import ast
import importlib.util
import os
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest

from leonardo.financial_tools import calculate_financial_tool, resolve_parameters
from leonardo.financial_tools._calculation import utc_classification as observer
from leonardo.financial_tools._calculation import universal_trend_classifier as current
from tests.financial_tools_test.test_utc_classification import CASES, _frame, _parameters


@pytest.fixture(scope="module")
def accepted_baseline():
    root = os.environ.get("UTC_ENRICHMENT_BASELINE")
    if not root:
        pytest.skip("set UTC_ENRICHMENT_BASELINE to the frozen accepted checkout for the audit gate")
    root = Path(root)
    assert (root / "src/leonardo/financial_tools/_calculation/universal_trend_classifier.py").is_file()
    def load(file, suffix):
        name = "leonardo.financial_tools._calculation." + suffix
        spec = importlib.util.spec_from_file_location(name, root / "src/leonardo/financial_tools/_calculation" / file)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        return module
    return root, load("universal_trend_classifier.py", "_accepted_utc"), load("utc_classification.py", "_accepted_trace")


def test_detector_range_plot_and_existing_observer_function_bodies_are_unchanged(accepted_baseline):
    root, _, _ = accepted_baseline
    package = Path(current.__file__).parent
    for filename, allowed in (
        ("universal_trend_classifier.py", {"_calculate_universal_trend_classifier"}),
        ("utc_classification.py", {"__init__", "segment"}),
    ):
        before = ast.parse((root / "src/leonardo/financial_tools/_calculation" / filename).read_text(encoding="utf-8"))
        after = ast.parse((package / filename).read_text(encoding="utf-8"))
        def bodies(tree):
            return {node.name: ast.dump(node, include_attributes=False) for node in ast.walk(tree)
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name not in allowed}
        assert bodies(before) == bodies(after)


def compare(data, parameters, accepted_baseline, monkeypatch):
    _, baseline, trace = accepted_baseline
    parameters = resolve_parameters("UTC", parameters)
    actual_series, actual = current._calculate_universal_trend_classifier(data, parameters, {})
    with monkeypatch.context() as patch:
        patch.setattr(observer, "_UtcTrace", trace._UtcTrace)
        expected_series, expected = baseline._calculate_universal_trend_classifier(data, parameters, {})
    assert len(actual_series) == len(expected_series) == 27
    for left, right in zip(actual_series, expected_series):
        pd.testing.assert_series_equal(left, right, check_exact=True)
    assert actual["utc_classification"] == expected["utc_classification"]


@pytest.mark.parametrize("sequence", CASES)
@pytest.mark.parametrize("mirror", (False, True))
def test_exact_formation_outputs_and_classification_match_frozen_source(sequence, mirror, accepted_baseline, monkeypatch):
    if mirror:
        sequence = tuple(("T" if k == "P" else "P", 220-v) for k,v in sequence)
    compare(_frame(sequence), _parameters(), accepted_baseline, monkeypatch)


@pytest.mark.parametrize("window", (3,5,7,9,11))
@pytest.mark.parametrize("seed", (3,18,94))
def test_seeded_mixed_windows_and_invalid_segments_match_frozen_source(window, seed, accepted_baseline, monkeypatch):
    rng = np.random.default_rng(seed)
    close = 100 + np.cumsum(rng.normal(0,.8,120))
    data = pd.DataFrame(dict(ts_ms=1_700_000_000_000+np.arange(120)*60_000,
                             open=close, high=close+1, low=close-1, close=close, volume=1.))
    pt = calculate_financial_tool("peaks_troughs", data).to_frame()
    for name in pt.columns[1:]: data[name] = pt[name]
    data.loc[48,"close"] = np.nan
    data.loc[70:,"ts_ms"] += 3_600_000
    data["saved_peak"] = data[f"peak_fractal_{window}"].map(lambda v: str(v) if pd.notna(v) else v)
    data["saved_trough"] = data[f"trough_fractal_{window}"].map(lambda v: str(v) if pd.notna(v) else v)
    compare(data, {"trend_fractal_window":window, "range_fractal_window":3 if window != 3 else 7,
                   "peak_column":"saved_peak", "trough_column":"saved_trough"}, accepted_baseline, monkeypatch)
