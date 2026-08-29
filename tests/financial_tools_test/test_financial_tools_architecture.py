from __future__ import annotations

import ast
from dataclasses import fields
from pathlib import Path

import leonardo.financial_tools as financial_tools
from leonardo.financial_tools.models import FinancialToolSpec


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "src" / "leonardo" / "financial_tools"


def test_public_package_exports_only_frozen_task_api() -> None:
    assert financial_tools.__all__ == (
        "ALL_FINANCIAL_TOOL_SPECS", "CANONICAL_TOOL_ALIASES", "CONSTRUCT_SPECS", "ConstructIOSpec",
        "DataInputSpec", "FinancialToolSpec", "FinancialToolCalculationResult",
        "INDICATOR_SPECS", "OSCILLATOR_SPECS",
        "OscillatorGuideLevelSpec", "OscillatorVisualSpec", "OutputSignalSpec", "ParameterSpec",
        "ToolBehaviorSpec", "ToolEditCapabilities", "ToolOutputSpec", "ToolStyleCapabilities",
        "ToolUpdatePolicy", "UpdateStrategy",
        "build_source_token", "calculate_financial_tool", "canonicalize_tool_key", "get_financial_tool_spec",
        "list_financial_tool_specs", "resolve_output_names", "resolve_output_signals",
        "resolve_parameters", "validate_catalog",
    )


def test_package_contains_only_authorized_task_modules() -> None:
    assert {path.name for path in PACKAGE.glob("*.py")} == {
        "__init__.py", "calculation.py", "calculation_models.py",
        "construct_input_eligibility.py", "models.py", "naming.py", "specifications.py",
    }
    assert {
        path.name
        for path in PACKAGE.iterdir()
        if path.is_file() and path.suffix != ".py"
    } == {"construct_input_eligibility.json"}
    assert {path.name for path in (PACKAGE / "_calculation").glob("*.py")} == {
        "__init__.py", "common.py", "constructs.py", "dynamic_binning.py", "indicators.py",
        "oscillators.py", "universal_trend_classifier.py",
    }


def test_financial_tools_do_not_import_gui_core_compute_or_persistence() -> None:
    forbidden = (
        "PySide6", "leonardo.gui", "leonardo.research", "leonardo.core", "leonardo.ohlcv",
        "leonardo.storage", "pandas", "numpy", "sqlite", "sqlalchemy", "ContractRegistry",
        "ToolContract", "ft_naming", "ft_specs", "specs_runtime", "naming_runtime", "tool_contracts",
        "CoreBridge", "DataManager",
    )
    base_allowed_imports = {
        "__future__",
        "collections",
        "dataclasses",
        "re",
        "types",
        "typing",
    }
    for path in (PACKAGE / name for name in ("models.py", "naming.py", "specifications.py")):
        source = path.read_text(encoding="utf-8")
        assert not any(term in source for term in forbidden), path
        tree = ast.parse(source)
        allowed_imports = set(base_allowed_imports)
        if path.name == "models.py":
            allowed_imports.add("enum")
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(
                    alias.name.split(".")[0] in allowed_imports
                    for alias in node.names
                )
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                assert (node.module or "").split(".")[0] in allowed_imports


def test_models_do_not_store_callable_resolvers_or_use_contract_names() -> None:
    assert all("resolver" not in field.name for field in fields(FinancialToolSpec))
    source = (PACKAGE / "models.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    identifiers = {
        node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
    } | {
        node.arg for node in ast.walk(tree) if isinstance(node, ast.arg)
    } | {
        node.name for node in ast.walk(tree) if isinstance(node, (ast.ClassDef, ast.FunctionDef))
    }
    assert all(not name.endswith("Contract") for name in identifiers)


def test_only_the_accepted_public_calculation_entry_point_is_created() -> None:
    public_functions: list[tuple[str, str]] = []
    for path in PACKAGE.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        public_functions.extend(
            (path.name, node.name)
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_")
        )
    assert ("calculation.py", "calculate_financial_tool") in public_functions
    assert not any(
        name.startswith(("compute", "execute", "persist", "save", "load"))
        and (path_name, name) != (
            "construct_input_eligibility.py",
            "load_construct_input_eligibility",
        )
        for path_name, name in public_functions
    )


def test_no_filesystem_persistence_calls_are_created() -> None:
    forbidden_calls = {
        "open", "write", "write_text", "write_bytes", "mkdir", "makedirs", "rename",
        "unlink", "remove", "rmdir", "dump", "dumps",
    }
    for path in PACKAGE.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    name = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    name = node.func.attr
                else:
                    continue
                if name == "open" and path.name == "construct_input_eligibility.py":
                    assert isinstance(node.func, ast.Attribute), (path, name)
                    assert (
                        node.args
                        and isinstance(node.args[0], ast.Constant)
                        and node.args[0].value == "r"
                    ), (path, name)
                    continue
                assert name not in forbidden_calls, (path, name)


def test_calculation_modules_preserve_private_dependency_boundary() -> None:
    forbidden = (
        "PySide6", "leonardo.gui", "leonardo.research", "leonardo.core", "leonardo.ohlcv",
        "leonardo.storage", "sqlite", "sqlalchemy", "processEvents", "ToolContract",
        "IndicatorRequest", "OscillatorRequest", "ConstructRequest", "CoreBridge", "ft_specs",
        "ft_naming", "specs_runtime", "naming_runtime", "tool_contracts",
    )
    calculation_paths = (
        PACKAGE / "calculation.py", PACKAGE / "calculation_models.py",
        *((PACKAGE / "_calculation").glob("*.py")),
    )
    for path in calculation_paths:
        source = path.read_text(encoding="utf-8")
        assert not any(term in source for term in forbidden), path


def test_private_calculation_package_exports_nothing() -> None:
    namespace: dict[str, object] = {}
    exec((PACKAGE / "_calculation" / "__init__.py").read_text(encoding="utf-8"), namespace)
    assert namespace["__all__"] == ()


def test_no_public_registry_discovery_or_plugin_mechanism() -> None:
    forbidden_modules = {"pkgutil", "importlib"}
    forbidden_calls = {"entry_points", "discover", "register", "register_plugin"}
    forbidden_public_tokens = ("registry", "discover", "plugin")
    calculation_paths = (
        PACKAGE / "calculation.py", PACKAGE / "calculation_models.py",
        *((PACKAGE / "_calculation").glob("*.py")),
    )
    for path in calculation_paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(alias.name.split(".")[0] not in forbidden_modules for alias in node.names), path
            elif isinstance(node, ast.ImportFrom):
                assert (node.module or "").split(".")[0] not in forbidden_modules, path
            elif isinstance(node, ast.Call):
                name = node.func.id if isinstance(node.func, ast.Name) else (
                    node.func.attr if isinstance(node.func, ast.Attribute) else ""
                )
                assert name not in forbidden_calls, (path, name)
        public_names = (
            node.name
            for node in tree.body
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
            and not node.name.startswith("_")
        )
        assert not any(
            token in name.lower()
            for name in public_names
            for token in forbidden_public_tokens
        ), path


def test_specifications_exposes_only_authorized_uppercase_catalog_constants() -> None:
    tree = ast.parse((PACKAGE / "specifications.py").read_text(encoding="utf-8"))
    assigned_names: set[str] = set()
    for node in tree.body:
        targets: tuple[ast.expr, ...]
        if isinstance(node, ast.Assign):
            targets = tuple(node.targets)
        elif isinstance(node, ast.AnnAssign):
            targets = (node.target,)
        else:
            continue
        assigned_names.update(
            target.id
            for target in targets
            if isinstance(target, ast.Name) and not target.id.startswith("_") and target.id.isupper()
        )
    assert assigned_names == {
        "INDICATOR_SPECS",
        "OSCILLATOR_SPECS",
        "CONSTRUCT_SPECS",
        "ALL_FINANCIAL_TOOL_SPECS",
    }
