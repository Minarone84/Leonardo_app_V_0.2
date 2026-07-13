from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "leonardo"


def test_retired_heavy_v2_packages_are_absent() -> None:
    forbidden = (
        SRC / "contracts",
        SRC / "gui" / "metadata",
        SRC / "core" / "contract_registry.py",
        SRC / "core" / "object_map_service.py",
        SRC / "core" / "state_store.py",
        SRC / "core" / "service_registry.py",
        SRC / "core" / "session_manager.py",
        SRC / "core" / "user_policy.py",
        SRC / "gui" / "dummy_data.py",
        SRC / "gui" / "settings_inspector.py",
        SRC / "gui" / "settings_profiles.py",
        SRC / "gui" / "windows" / "settings_inspector_window.py",
    )
    assert all(not path.exists() for path in forbidden)


def test_no_production_imports_reference_retired_machinery() -> None:
    forbidden_tokens = (
        "leonardo.contracts",
        "leonardo.gui.metadata",
        "ContractRegistry",
        "ObjectMap",
        "StateStore",
        "GuiMetadata",
        "ReadOnlyObjectMapService",
        "CoreRuntimeBridge",
    )
    offenders = []
    for path in SRC.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for token in forbidden_tokens:
            if token in text:
                offenders.append((path.relative_to(ROOT), token))
    assert offenders == []
