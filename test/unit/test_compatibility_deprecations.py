from __future__ import annotations

from pathlib import Path

import pytest


DEPRECATED_INTERNAL_IMPORT_PATTERNS = (
    "from dhara.file_storage import",
    "import dhara.file_storage",
    "from dhara.connection import",
    "import dhara.connection",
    "from dhara.persistent import",
    "import dhara.persistent",
    "from dhara.persistent_dict import",
    "import dhara.persistent_dict",
    "from dhara.persistent_list import",
    "import dhara.persistent_list",
)

ALLOWED_COMPAT_FILES = {
    "dhara/file_storage.py",
    "dhara/connection.py",
    "dhara/persistent.py",
    "dhara/persistent_dict.py",
    "dhara/persistent_list.py",
}


@pytest.mark.unit
def test_deprecated_compatibility_imports_emit_warnings() -> None:
    with pytest.deprecated_call():
        import dhara.file_storage  # noqa: F401

    with pytest.deprecated_call():
        import dhara.connection  # noqa: F401

    with pytest.deprecated_call():
        import dhara.persistent  # noqa: F401

    with pytest.deprecated_call():
        import dhara.persistent_dict  # noqa: F401

    with pytest.deprecated_call():
        import dhara.persistent_list  # noqa: F401

    with pytest.deprecated_call():
        import dhara.mcp.server  # noqa: F401

    with pytest.deprecated_call():
        import druva  # noqa: F401


@pytest.mark.unit
def test_dhara_internals_do_not_import_deprecated_compatibility_shims() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    dhara_root = repo_root / "dhara"
    offenders: list[str] = []

    for path in dhara_root.rglob("*.py"):
        relpath = path.relative_to(repo_root).as_posix()
        if relpath in ALLOWED_COMPAT_FILES:
            continue

        content = path.read_text()
        for pattern in DEPRECATED_INTERNAL_IMPORT_PATTERNS:
            if pattern in content:
                offenders.append(f"{relpath}: {pattern}")

    assert offenders == []
