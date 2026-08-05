from __future__ import annotations

import ast
import inspect
from pathlib import Path

import leonardo.artifacts as artifacts
from leonardo.artifacts import ArtifactService


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "src" / "leonardo" / "artifacts"
TESTS = ROOT / "tests" / "artifacts_test"

PRODUCTION_FILES = {
    "__init__.py",
    "_stores.py",
    "identity.py",
    "models.py",
    "serialization.py",
    "service.py",
}
TEST_FILES = {
    "test_artifact_architecture.py",
    "test_artifact_atomicity.py",
    "test_artifact_catalog_and_delete.py",
    "test_artifact_identity.py",
    "test_artifact_lineage.py",
    "test_artifact_models.py",
    "test_artifact_serialization.py",
    "test_artifact_service_roundtrip.py",
    "test_managed_artifact_versions.py",
}
PUBLIC_API = {
    "ArtifactAlreadyExistsError",
    "ArtifactError",
    "ArtifactIdentityCollisionError",
    "ArtifactLineageError",
    "ArtifactHeadV1",
    "ArtifactMetadataV1",
    "ArtifactNotFoundError",
    "ArtifactRecipeV1",
    "ArtifactSaveResult",
    "ArtifactService",
    "ArtifactSourceRefV1",
    "ArtifactSummary",
    "ArtifactValidationError",
    "ArtifactVersionRecordV1",
    "LoadedArtifact",
    "ManagedArtifactGraphPublicationResult",
    "ManagedArtifactSummary",
    "ManagedArtifactVersionKey",
    "OHLCVSourceFingerprintV1",
    "PreparedManagedArtifact",
    "RecipeInUseError",
    "RecipeSaveResult",
    "RecipeSummary",
    "compute_logical_artifact_id",
}


def _production_text() -> str:
    return "\n".join((PACKAGE / name).read_text(encoding="utf-8") for name in sorted(PRODUCTION_FILES))


def test_exact_task_inventory_and_public_api() -> None:
    assert {path.name for path in PACKAGE.glob("*.py")} == PRODUCTION_FILES
    assert {path.name for path in TESTS.glob("*.py")} == TEST_FILES
    assert {path.name for path in (TESTS / "fixtures").iterdir() if path.is_file()} == {
        "task_1016_canonical_values.csv",
        "task_1016_identity_fixtures.json",
    }
    assert set(artifacts.__all__) == PUBLIC_API
    assert {name for name in PUBLIC_API if hasattr(artifacts, name)} == PUBLIC_API


def test_artifact_service_is_the_only_public_write_owner() -> None:
    assert {
        name
        for name, value in inspect.getmembers(ArtifactService, inspect.isfunction)
        if not name.startswith("_")
    } == {
        "delete_artifact",
        "delete_recipe",
        "capture_accepted_source",
        "list_artifacts",
        "list_artifact_versions",
        "list_managed_artifacts",
        "list_managed_markets",
        "list_recipes",
        "load_artifact",
        "load_artifact_by_id",
        "load_artifact_head",
        "load_artifact_version",
        "load_recipe",
        "prepare_managed_calculation",
        "publish_managed_artifact_graph",
        "save_calculation",
        "save_recipe_from_result",
        "validate_artifact_current",
    }
    assert not any(
        name.lower().endswith(("store", "registry", "plugin"))
        for name in artifacts.__all__
        if name != "ArtifactService"
    )


def test_no_forbidden_layer_or_scope_imports() -> None:
    forbidden = {
        "PySide6",
        "leonardo.gui",
        "leonardo.core",
        "leonardo.research",
        "leonardo.data_manager",
        "leonardo.analysis",
        "leonardo.backtesting",
    }
    imported: set[str] = set()
    for name in PRODUCTION_FILES:
        tree = ast.parse((PACKAGE / name).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
    assert not any(
        module == item or module.startswith(item + ".")
        for module in imported
        for item in forbidden
    )


def test_no_calculation_collection_recovery_or_database_implementation() -> None:
    text = _production_text()
    for forbidden in (
        "calculate_financial_tool",
        ".rolling(",
        ".ewm(",
        "processEvents",
    ):
        assert forbidden not in text
    assert not any(
        token in path.stem
        for path in PACKAGE.glob("*.py")
        for token in ("collection", "update", "recovery", "database")
    )


def test_no_ohlcv_mutation_calls_or_broad_deletion() -> None:
    service_tree = ast.parse((PACKAGE / "service.py").read_text(encoding="utf-8"))
    ohlcv_calls = {
        node.func.attr
        for node in ast.walk(service_tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Attribute)
        and isinstance(node.func.value.value, ast.Name)
        and node.func.value.value.id == "self"
        and node.func.value.attr == "_ohlcv_store"
    }
    assert ohlcv_calls <= {"csv_path", "sidecar_path", "read", "read_sidecar"}
    text = _production_text()
    for forbidden in ("rmtree", "os.walk", ".rglob(", ".glob(", "shutil"):
        assert forbidden not in text


def test_no_arbitrary_path_public_operation() -> None:
    for name, method in inspect.getmembers(ArtifactService, inspect.isfunction):
        if name.startswith("_") or name == "__init__":
            continue
        parameters = inspect.signature(method).parameters
        assert not any("path" in parameter.lower() or "root" in parameter.lower() for parameter in parameters)


def test_recipe_publication_is_create_if_absent() -> None:
    stores = (PACKAGE / "_stores.py").read_text(encoding="utf-8")
    assert "os.link(temporary, path)" in stores
    assert "def _replace_mutable_file" in stores
    assert stores.count("os.replace(") == 2


def test_artifact_publication_is_native_no_replace() -> None:
    stores = (PACKAGE / "_stores.py").read_text(encoding="utf-8")
    assert "_publish_directory_no_replace(staging, final_dir)" in stores
    assert "renameat2" in stores
    assert "_replace_mutable_file(path, payload" in stores


def test_artifact_serialization_uses_task_1015_runtime_authority() -> None:
    service = (PACKAGE / "service.py").read_text(encoding="utf-8")
    serialization = (PACKAGE / "serialization.py").read_text(encoding="utf-8")
    assert "FinancialToolCalculationResult.runtime_output_types" in service
    assert "FinancialToolCalculationResult.validate_runtime_outputs" in service
    assert "resolve_output_signals" not in service
    assert "OutputSignalSpec" not in serialization
