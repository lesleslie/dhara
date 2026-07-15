"""
Async file storage shim — drop-in replacement for the legacy sync
``FileStorage`` path-arg pattern.

The async-first migration deletes ``dhara/storage/file.py`` (Duru's SHELF
format) in favor of async backends. ``AsyncSqliteStorage`` is the canonical
async file-backed store, but its constructor accepts a SQLite URL rather
than a filesystem path. This shim provides the ``AsyncFileStorage`` /
``TempFileStorage`` symbols that callers expect, mapping ``str(path)`` →
``sqlite+aiosqlite://<path>`` so the legacy call sites keep their
ergonomics.

This module exists only to ease the migration; new code should construct
``AsyncSqliteStorage`` directly with a URL.
"""
from __future__ import annotations

import os
import tempfile
from typing import Any

from dhara.storage.sqlite import AsyncSqliteStorage


def _path_to_url(path: str) -> str:
    """Convert a filesystem path to a ``sqlite+aiosqlite://`` URL.

    ``:memory:`` is preserved as-is. ``sqlite+aiosqlite:///...`` URLs are
    returned unchanged so callers can opt into URL-form explicitly.
    """
    if path == ":memory:":
        return ":memory:"
    if path.startswith("sqlite+aiosqlite://") or path.startswith("sqlite://"):
        return path
    return f"sqlite+aiosqlite://{path}"


class AsyncFileStorage(AsyncSqliteStorage):
    """Async file-backed storage with path-style construction.

    Accepts a filesystem path (matching the legacy ``FileStorage(path)``
    pattern). Maps the path to a SQLite URL and delegates to
    :class:`AsyncSqliteStorage` for the actual implementation.
    """

    def __init__(self, path: str = "", pack_increment: int = 100) -> None:
        url = _path_to_url(path) if path else None
        super().__init__(url=url, pack_increment=pack_increment)

    async def get_filename(self) -> str:
        """Return the underlying database path.

        Mirrors the legacy ``FileStorage.get_filename()`` API for callers
        that introspect the storage's filename.
        """
        return self._url or ":memory:"

    async def __aenter__(self) -> AsyncFileStorage:
        await self.init()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.close()


def TempFileStorage() -> AsyncFileStorage:
    """Return an async file storage backed by a temporary file.

    Matches the legacy ``TempFileStorage()`` factory shape used by tests
    and tooling. The temporary file is created via ``tempfile.mkstemp``
    so the storage has a stable filesystem path for the lifetime of the
    process; callers are expected to ``close()`` the storage when done.
    """
    fd, path = tempfile.mkstemp(prefix="dhara-", suffix=".db")
    os.close(fd)
    return AsyncFileStorage(path)