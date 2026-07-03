import ast
import json
from pathlib import Path

import pytest

from leonardo.gui.metadata import (
    GuiMetadataOverrideDocument,
    GuiMetadataOverrideStore,
    OVERRIDE_FILE_SCHEMA_VERSION,
    load_metadata_document,
)


_METADATA_ID = "main_window.window"
_REPO_ROOT = Path(__file__).resolve().parents[2]
_MAIN_WINDOW_METADATA_PATH = (
    _REPO_ROOT
    / "src"
    / "leonardo"
    / "gui"
    / "metadata"
    / "windows"
    / "main_window.window.toml"
)
_OVERRIDE_STORE_PATH = (
    _REPO_ROOT
    / "src"
    / "leonardo"
    / "gui"
    / "metadata"
    / "override_store.py"
)


def test_missing_override_file_loads_empty_document(tmp_path: Path) -> None:
    store = _store(tmp_path)

    result = store.load(_METADATA_ID)

    assert result.ok is True
    assert result.path == store.path_for(_METADATA_ID)
    assert result.document == GuiMetadataOverrideDocument(metadata_id=_METADATA_ID)
    assert store.root.exists() is False


def test_save_load_round_trip_persists_changed_only_overrides(tmp_path: Path) -> None:
    store = _store(tmp_path)
    document = GuiMetadataOverrideDocument(
        metadata_id=_METADATA_ID,
        values={"style.font_size": 12, "style.density": "compact"},
    )

    save_result = store.save(document)
    load_result = store.load(_METADATA_ID)

    assert save_result.ok is True
    assert load_result.ok is True
    assert load_result.document is not None
    assert load_result.document.metadata_id == _METADATA_ID
    assert load_result.document.values == document.values


def test_saved_json_contains_required_fields(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.save(
        GuiMetadataOverrideDocument(
            metadata_id=_METADATA_ID,
            values={"style.font_size": 12},
        )
    )

    payload = _load_payload(store.path_for(_METADATA_ID))

    assert set(payload) == {
        "schema_version",
        "metadata_id",
        "updated_at_ms",
        "overrides",
    }
    assert payload["schema_version"] == OVERRIDE_FILE_SCHEMA_VERSION
    assert payload["metadata_id"] == _METADATA_ID
    assert isinstance(payload["updated_at_ms"], int)
    assert payload["overrides"] == {"style.font_size": 12}


def test_saved_json_does_not_contain_defaults(tmp_path: Path) -> None:
    metadata_result = load_metadata_document(_MAIN_WINDOW_METADATA_PATH)
    assert metadata_result.document is not None
    document = metadata_result.document
    store = _store(tmp_path)

    store.save(
        GuiMetadataOverrideDocument(
            metadata_id=document.metadata_id,
            values={"style.font_size": 12},
        )
    )

    payload = _load_payload(store.path_for(document.metadata_id))

    assert payload["overrides"] == {"style.font_size": 12}
    assert "geometry.width" not in payload["overrides"]
    assert "geometry.height" not in payload["overrides"]


def test_empty_override_save_deletes_existing_file(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.save(
        GuiMetadataOverrideDocument(
            metadata_id=_METADATA_ID,
            values={"style.font_size": 12},
        )
    )
    path = store.path_for(_METADATA_ID)
    assert path.exists()

    result = store.save(GuiMetadataOverrideDocument(metadata_id=_METADATA_ID))

    assert result.ok is True
    assert result.document is not None
    assert result.document.values == {}
    assert path.exists() is False


def test_reset_field_removes_only_one_key(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.save(
        GuiMetadataOverrideDocument(
            metadata_id=_METADATA_ID,
            values={"style.font_size": 12, "geometry.width": 1300},
        )
    )

    result = store.reset_field(_METADATA_ID, "style.font_size")
    loaded = store.load(_METADATA_ID)

    assert result.ok is True
    assert loaded.document is not None
    assert loaded.document.values == {"geometry.width": 1300}


def test_reset_section_removes_only_keys_under_prefix(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.save(
        GuiMetadataOverrideDocument(
            metadata_id=_METADATA_ID,
            values={
                "style.font_size": 12,
                "style.density": "compact",
                "geometry.width": 1300,
            },
        )
    )

    result = store.reset_section(_METADATA_ID, "style")
    loaded = store.load(_METADATA_ID)

    assert result.ok is True
    assert loaded.document is not None
    assert loaded.document.values == {"geometry.width": 1300}


def test_reset_profile_deletes_file(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.save(
        GuiMetadataOverrideDocument(
            metadata_id=_METADATA_ID,
            values={"style.font_size": 12},
        )
    )
    path = store.path_for(_METADATA_ID)
    assert path.exists()

    result = store.reset_profile(_METADATA_ID)

    assert result.ok is True
    assert result.document is not None
    assert result.document.values == {}
    assert path.exists() is False


@pytest.mark.parametrize(
    "metadata_id",
    ("", "bad/name", r"bad\name", "bad:name", "bad..name"),
)
def test_unsafe_metadata_ids_are_rejected(
    tmp_path: Path,
    metadata_id: str,
) -> None:
    store = _store(tmp_path)

    with pytest.raises(ValueError):
        store.path_for(metadata_id)
    result = store.load(metadata_id)

    assert result.ok is False
    assert result.path is None
    assert result.document is None
    assert result.errors[0].code == "unsafe_metadata_id"


@pytest.mark.parametrize(
    "metadata_id",
    ("..", "../main", "main/../window", r"..\main"),
)
def test_path_traversal_metadata_ids_are_rejected(
    tmp_path: Path,
    metadata_id: str,
) -> None:
    store = _store(tmp_path)

    with pytest.raises(ValueError):
        store.path_for(metadata_id)
    result = store.load(metadata_id)

    assert result.ok is False
    assert result.path is None
    assert result.errors[0].code == "unsafe_metadata_id"


def test_corrupt_json_returns_diagnostics_and_empty_document(tmp_path: Path) -> None:
    store = _store(tmp_path)
    path = _write_raw_override(store, _METADATA_ID, "{not json")

    result = store.load(_METADATA_ID)

    assert result.ok is False
    assert result.document == GuiMetadataOverrideDocument(metadata_id=_METADATA_ID)
    assert result.errors[0].code == "corrupt_json"
    assert path.exists()


def test_non_object_json_returns_diagnostics_and_empty_document(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _write_raw_override(store, _METADATA_ID, "[]")

    result = store.load(_METADATA_ID)

    assert result.ok is False
    assert result.document == GuiMetadataOverrideDocument(metadata_id=_METADATA_ID)
    assert result.errors[0].code == "invalid_payload"


def test_schema_mismatch_returns_diagnostics_and_empty_document(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _write_payload(
        store,
        _METADATA_ID,
        {
            "schema_version": "unsupported",
            "metadata_id": _METADATA_ID,
            "updated_at_ms": 1,
            "overrides": {"style.font_size": 12},
        },
    )

    result = store.load(_METADATA_ID)

    assert result.ok is False
    assert result.document == GuiMetadataOverrideDocument(metadata_id=_METADATA_ID)
    assert result.errors[0].code == "schema_mismatch"


def test_metadata_id_mismatch_returns_diagnostics_and_empty_document(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    _write_payload(
        store,
        _METADATA_ID,
        {
            "schema_version": OVERRIDE_FILE_SCHEMA_VERSION,
            "metadata_id": "runtime_manager.window",
            "updated_at_ms": 1,
            "overrides": {"style.font_size": 12},
        },
    )

    result = store.load(_METADATA_ID)

    assert result.ok is False
    assert result.document == GuiMetadataOverrideDocument(metadata_id=_METADATA_ID)
    assert result.errors[0].code == "metadata_id_mismatch"


def test_invalid_overrides_payload_returns_diagnostics_and_empty_document(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    _write_payload(
        store,
        _METADATA_ID,
        {
            "schema_version": OVERRIDE_FILE_SCHEMA_VERSION,
            "metadata_id": _METADATA_ID,
            "updated_at_ms": 1,
            "overrides": [],
        },
    )

    result = store.load(_METADATA_ID)

    assert result.ok is False
    assert result.document == GuiMetadataOverrideDocument(metadata_id=_METADATA_ID)
    assert result.errors[0].code == "invalid_overrides"


def test_atomic_save_writes_final_file_at_expected_path(tmp_path: Path) -> None:
    store = _store(tmp_path)

    result = store.save(
        GuiMetadataOverrideDocument(
            metadata_id=_METADATA_ID,
            values={"style.font_size": 12},
        )
    )

    assert result.ok is True
    assert result.path == store.path_for(_METADATA_ID)
    assert store.path_for(_METADATA_ID).exists()
    assert list(store.root.glob("*.tmp")) == []
    assert list(store.root.glob(".*.tmp")) == []


def test_store_does_not_mutate_source_metadata_documents(tmp_path: Path) -> None:
    before = _MAIN_WINDOW_METADATA_PATH.read_text(encoding="utf-8")
    store = _store(tmp_path)

    store.save(
        GuiMetadataOverrideDocument(
            metadata_id=_METADATA_ID,
            values={"style.font_size": 12},
        )
    )
    store.reset_profile(_METADATA_ID)

    assert _MAIN_WINDOW_METADATA_PATH.read_text(encoding="utf-8") == before


def test_store_imports_no_qt_core_or_window_modules() -> None:
    tree = ast.parse(_OVERRIDE_STORE_PATH.read_text(encoding="utf-8"))
    imported_modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported_modules.append(node.module)

    assert all(not module.startswith("PySide") for module in imported_modules)
    assert all(not module.startswith("PyQt") for module in imported_modules)
    assert all(not module.startswith("leonardo.core") for module in imported_modules)
    assert all(not module.startswith("leonardo.gui.windows") for module in imported_modules)


def _store(tmp_path: Path) -> GuiMetadataOverrideStore:
    return GuiMetadataOverrideStore(tmp_path / "gui_overrides")


def _load_payload(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _write_raw_override(
    store: GuiMetadataOverrideStore,
    metadata_id: str,
    text: str,
) -> Path:
    store.root.mkdir(parents=True, exist_ok=True)
    path = store.path_for(metadata_id)
    path.write_text(text, encoding="utf-8")
    return path


def _write_payload(
    store: GuiMetadataOverrideStore,
    metadata_id: str,
    payload: object,
) -> Path:
    return _write_raw_override(store, metadata_id, json.dumps(payload))
