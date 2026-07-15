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
        "DataInputSpec", "FinancialToolSpec", "INDICATOR_SPECS", "OSCILLATOR_SPECS",
        "OscillatorGuideLevelSpec", "OscillatorVisualSpec", "OutputSignalSpec", "ParameterSpec",
        "ToolBehaviorSpec", "ToolEditCapabilities", "ToolOutputSpec", "ToolStyleCapabilities",
        "build_source_token", "canonicalize_tool_key", "get_financial_tool_spec",
        "list_financial_tool_specs", "resolve_output_names", "resolve_output_signals",
        "resolve_parameters", "validate_catalog",
    )


def test_package_contains_only_authorized_task_modules() -> None:
    assert {path.name for path in PACKAGE.glob("*.py")} == {
        "__init__.py", "models.py", "naming.py", "specifications.py"
    }


def test_financial_tools_do_not_import_gui_core_compute_or_persistence() -> None:
    forbidden = (
        "PySide6", "leonardo.gui", "leonardo.research", "leonardo.core", "leonardo.ohlcv",
        "leonardo.storage", "pandas", "numpy", "sqlite", "sqlalchemy", "ContractRegistry",
        "ToolContract", "ft_naming", "ft_specs", "specs_runtime", "naming_runtime", "tool_contracts",
        "CoreBridge", "DataManager",
    )
    for path in PACKAGE.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert not any(term in source for term in forbidden), path
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(alias.name.split(".")[0] in {"collections", "dataclasses", "re", "types", "typing"}
                           for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                assert (node.module or "").split(".")[0] in {
                    "__future__", "collections", "dataclasses", "re", "types", "typing"
                }


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


def test_no_calculation_entry_points_are_created() -> None:
    forbidden_function_prefixes = ("calculate", "compute", "execute", "persist", "save", "load")
    for path in PACKAGE.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        public_functions = [node.name for node in tree.body if isinstance(node, ast.FunctionDef) and not node.name.startswith("_")]
        assert not any(name.startswith(forbidden_function_prefixes) for name in public_functions)


def test_no_filesystem_persistence_calls_are_created() -> None:
    forbidden_calls = {
        "open", "write", "write_text", "write_bytes", "mkdir", "makedirs", "rename",
        "unlink", "remove", "rmdir", "dump", "dumps",
    }
    for path in PACKAGE.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    name = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    name = node.func.attr
                else:
                    continue
                assert name not in forbidden_calls, (path, name)


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
