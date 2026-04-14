from __future__ import annotations

from pathlib import Path

import pytest


FORBIDDEN_DOC_PATTERNS = (
    "dhara-mcp",
    "dhara -s",
    "dhara -c",
    "dhara db server",
    "python -m dhara.cli start",
    "from dhara.file_storage import",
    "from dhara.connection import",
    "from dhara.client_storage import",
    "from dhara.persistent import",
    "from dhara.persistent_dict import",
    "from dhara.persistent_list import",
    "from durus.",
    "import durus",
    "create_server(",
)

EXCLUDED_DOC_PREFIXES = (
    "docs/archive/",
    "docs/implementation-plans/",
    "docs/.backups/",
)

EXCLUDED_DOC_FILES = {
    "docs/MIGRATION_GUIDE.md",
}


def _iter_active_doc_files(repo_root: Path) -> list[Path]:
    files = [repo_root / "README.md"]
    docs_root = repo_root / "docs"

    for path in docs_root.rglob("*"):
        if not path.is_file():
            continue
        relpath = path.relative_to(repo_root).as_posix()
        if any(relpath.startswith(prefix) for prefix in EXCLUDED_DOC_PREFIXES):
            continue
        if relpath in EXCLUDED_DOC_FILES:
            continue
        files.append(path)

    return files


@pytest.mark.unit
def test_active_docs_do_not_reintroduce_deprecated_surfaces() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    offenders: list[str] = []

    for path in _iter_active_doc_files(repo_root):
        relpath = path.relative_to(repo_root).as_posix()
        if path.suffix not in {".md", ".py", ".yaml", ".yml", ".txt"}:
            continue

        content = path.read_text()
        for pattern in FORBIDDEN_DOC_PATTERNS:
            if pattern in content:
                offenders.append(f"{relpath}: {pattern}")

    assert offenders == []
