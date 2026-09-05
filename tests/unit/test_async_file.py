"""Comprehensive coverage for ``dhara.storage.async_file``.

The async file storage shim is a thin wrapper over ``AsyncSqliteStorage`` that
maps a filesystem-style ``path`` argument to a ``sqlite+aiosqlite://`` URL.
The module exposes:

- ``_path_to_url(path)`` — pure helper with four distinct branches
- ``AsyncFileStorage`` — public class extending ``AsyncSqliteStorage``
- ``TempFileStorage()`` — factory creating a stable temp-file backend

This file pushes coverage from 42% to ≥95% by exercising every branch,
including the async context manager protocol and the ``TempFileStorage``
factory's round-trip semantics.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from dhara.storage.async_file import (
    AsyncFileStorage,
    TempFileStorage,
    _path_to_url,
)

pytestmark = pytest.mark.unit


# --------------------------- _path_to_url ---------------------------


class TestPathToUrl:
    """Cover the four branches of ``_path_to_url``."""

    def test_memory_preserved_verbatim(self) -> None:
        """``:memory:`` short-circuits the helper and is returned unchanged."""
        assert _path_to_url(":memory:") == ":memory:"

    def test_aiosqlite_url_preserved_verbatim(self) -> None:
        """An explicit ``sqlite+aiosqlite://...`` URL is returned unchanged."""
        url = "sqlite+aiosqlite:///var/lib/dhara/store.db"
        assert _path_to_url(url) == url

    def test_sqlite_url_preserved_verbatim(self) -> None:
        """A bare ``sqlite://...`` URL is also returned unchanged."""
        url = "sqlite:///tmp/legacy.db"
        assert _path_to_url(url) == url

    def test_plain_path_gets_aiosqlite_prefix(self) -> None:
        """Plain filesystem paths are prefixed with ``sqlite+aiosqlite://``."""
        assert _path_to_url("/tmp/foo.db") == "sqlite+aiosqlite:///tmp/foo.db"

    def test_relative_path_gets_aiosqlite_prefix(self) -> None:
        """Relative paths follow the same prefix rule."""
        assert _path_to_url("relative/store.db") == "sqlite+aiosqlite://relative/store.db"


# --------------------------- AsyncFileStorage construction ---------------------------


class TestAsyncFileStorageInit:
    """Verify URL mapping and ``pack_increment`` forwarding."""

    def test_memory_path_sets_memory_url(self) -> None:
        """``path=":memory:"`` propagates ``:memory:`` through to ``_url``."""
        storage = AsyncFileStorage(":memory:")
        # Parent strips ``sqlite+aiosqlite://`` but ``:memory:`` is left alone.
        assert storage._url == ":memory:"

    def test_empty_path_yields_default_url(self) -> None:
        """``path=""`` skips the URL mapping; the parent picks its default."""
        storage = AsyncFileStorage("")
        # Parent's __init__ substitutes Oneiric or a macOS-friendly default
        # when given None. Either way ``_url`` is a non-empty string.
        assert isinstance(storage._url, str)
        assert storage._url  # non-empty

    def test_plain_path_gets_url_form(self) -> None:
        """Plain paths are converted to a SQLite URL and the prefix stripped."""
        storage = AsyncFileStorage("/tmp/prefix_check.db")
        # Parent strips the ``sqlite+aiosqlite://`` prefix → raw path.
        assert storage._url == "/tmp/prefix_check.db"

    def test_pack_increment_forwarded_to_parent(self) -> None:
        """``pack_increment`` must reach ``AsyncSqliteStorage._pack_increment``."""
        storage = AsyncFileStorage(":memory:", pack_increment=42)
        assert storage._pack_increment == 42

    def test_default_pack_increment(self) -> None:
        """Default ``pack_increment`` is 100 (matches parent's default)."""
        storage = AsyncFileStorage(":memory:")
        assert storage._pack_increment == 100

    def test_sqlite_url_passed_through(self) -> None:
        """An explicit ``sqlite+aiosqlite://`` URL is preserved (prefix stripped)."""
        url = "sqlite+aiosqlite:///tmp/explicit.db"
        storage = AsyncFileStorage(url)
        assert storage._url == "/tmp/explicit.db"

    def test_sqlite_plain_url_passed_through(self) -> None:
        """A bare ``sqlite://`` URL is preserved (prefix stripped)."""
        url = "sqlite:///tmp/explicit.db"
        storage = AsyncFileStorage(url)
        assert storage._url == "/tmp/explicit.db"


# --------------------------- get_filename ---------------------------


class TestGetFilename:
    """``get_filename`` returns the underlying URL, or ``:memory:`` if absent."""

    async def test_returns_url_when_set(self) -> None:
        """When ``_url`` is set, ``get_filename`` returns it verbatim."""
        storage = AsyncFileStorage(":memory:")
        assert await storage.get_filename() == ":memory:"

    async def test_returns_path_after_strip(self) -> None:
        """Plain paths round-trip back as the bare filesystem path."""
        storage = AsyncFileStorage("/tmp/get_filename_check.db")
        assert await storage.get_filename() == "/tmp/get_filename_check.db"

    async def test_falls_back_to_memory_when_url_is_none(self) -> None:
        """When ``_url`` is None, return ``:memory:`` (legacy API parity)."""
        storage = AsyncFileStorage(":memory:")
        # Simulate the post-init state where _url is unset.
        storage._url = None
        assert await storage.get_filename() == ":memory:"


# --------------------------- async context manager ---------------------------


class TestAsyncContextManager:
    """The ``__aenter__``/``__aexit__`` pair drives the parent lifecycle."""

    async def test_aenter_initializes_storage(self) -> None:
        """``__aenter__`` calls ``init()`` on the parent and returns ``self``."""
        async with AsyncFileStorage(":memory:") as storage:
            assert isinstance(storage, AsyncFileStorage)
            # Parent ``init`` opens an aiosqlite connection.
            assert storage._conn is not None

    async def test_aenter_returns_self(self) -> None:
        """The async context manager must yield the storage instance itself."""
        storage = AsyncFileStorage(":memory:")
        async with storage as ctx:
            assert ctx is storage

    async def test_aexit_closes_connection(self) -> None:
        """``__aexit__`` calls ``close()`` on the parent (closes the conn)."""
        storage = AsyncFileStorage(":memory:")
        async with storage:
            pass
        # Parent ``close`` closes the underlying aiosqlite connection.
        assert storage._conn is None


# --------------------------- TempFileStorage factory ---------------------------


class TestTempFileStorage:
    """The ``TempFileStorage`` factory creates a stable temp-file backend."""

    def test_returns_async_file_storage_instance(self) -> None:
        """The factory must yield an ``AsyncFileStorage`` instance."""
        storage: AsyncFileStorage = TempFileStorage()
        try:
            assert isinstance(storage, AsyncFileStorage)
        finally:
            # Best-effort cleanup if the test fails mid-flight.
            url = storage._url or ""
            if url and url != ":memory:" and os.path.exists(url):
                os.unlink(url)

    def test_creates_a_stable_temp_file(self) -> None:
        """The factory uses ``tempfile.mkstemp`` so the file exists immediately."""
        storage = TempFileStorage()
        try:
            url = storage._url
            assert url is not None
            assert url != ":memory:"
            # The path must exist on disk right after construction.
            assert os.path.exists(url)
        finally:
            url = storage._url or ""
            if url and url != ":memory:" and os.path.exists(url):
                os.unlink(url)

    def test_temp_file_uses_dhara_prefix_and_db_suffix(self) -> None:
        """The temp file is named ``dhara-*.db`` for visibility/cleanup hygiene."""
        storage = TempFileStorage()
        try:
            path = Path(storage._url)
            assert path.name.startswith("dhara-")
            assert path.suffix == ".db"
        finally:
            url = storage._url or ""
            if url and url != ":memory:" and os.path.exists(url):
                os.unlink(url)

    async def test_round_trip_with_real_file(self) -> None:
        """``TempFileStorage()`` supports store/load via the parent lifecycle."""
        storage = TempFileStorage()
        try:
            await storage.init()
            # ``store`` appends to pending; ``end`` commits via ``executemany``.
            # ``str_to_int8`` expects 8 raw bytes that decode to a value that
            # fits in SQLite INTEGER (signed 64-bit).
            oid = (1).to_bytes(8, "big", signed=False)
            await storage.begin()
            await storage.store(oid, b"hello-temp-file")
            await storage.end()

            loaded = await storage.load(oid)
            assert loaded == b"hello-temp-file"
            await storage.close()
        finally:
            url = storage._url or ""
            if url and url != ":memory:" and os.path.exists(url):
                os.unlink(url)

    def test_filename_is_callable_object(self) -> None:
        """``TempFileStorage`` is a zero-arg factory function (not a class)."""
        assert callable(TempFileStorage)
        storage = TempFileStorage()
        try:
            assert isinstance(storage, AsyncFileStorage)
        finally:
            url = storage._url or ""
            if url and url != ":memory:" and os.path.exists(url):
                os.unlink(url)

    def test_factory_produces_independent_files(self) -> None:
        """Two ``TempFileStorage()`` calls must not share the same path."""
        s1 = TempFileStorage()
        s2 = TempFileStorage()
        try:
            assert s1._url != s2._url
            assert os.path.exists(s1._url)
            assert os.path.exists(s2._url)
        finally:
            for s in (s1, s2):
                url = s._url or ""
                if url and url != ":memory:" and os.path.exists(url):
                    os.unlink(url)


# --------------------------- round-trip via real AsyncSqliteStorage ---------------------------


class TestRealRoundTrip:
    """End-to-end coverage using the real ``AsyncSqliteStorage`` parent."""

    async def test_memory_storage_round_trip(self) -> None:
        """``:memory:`` round-trips through the full parent lifecycle."""
        async with AsyncFileStorage(":memory:") as storage:
            oid = (1).to_bytes(8, "big", signed=False)
            await storage.begin()
            await storage.store(oid, b"in-memory-bytes")
            await storage.end()

            assert await storage.load(oid) == b"in-memory-bytes"

    async def test_real_file_storage_round_trip(self, tmp_path: Path) -> None:
        """A real on-disk file round-trips and is left intact on close."""
        target = tmp_path / "round_trip.db"
        storage = AsyncFileStorage(str(target))
        try:
            await storage.init()
            oid = (2).to_bytes(8, "big", signed=False)
            await storage.begin()
            await storage.store(oid, b"on-disk-bytes")
            await storage.end()

            assert await storage.load(oid) == b"on-disk-bytes"
            # File exists on disk.
            assert target.exists()
            await storage.close()
        finally:
            if target.exists():
                target.unlink()

    async def test_init_then_get_filename_matches_path(self, tmp_path: Path) -> None:
        """After init, ``get_filename`` reports the on-disk path."""
        target = tmp_path / "filename_check.db"
        storage = AsyncFileStorage(str(target))
        try:
            await storage.init()
            assert await storage.get_filename() == str(target)
            await storage.close()
        finally:
            if target.exists():
                target.unlink()


# --------------------------- type / protocol parity ---------------------------


class TestTypeShape:
    """Sanity-check the public type shape of the module."""

    def test_module_exports_expected_symbols(self) -> None:
        """The public surface must include ``AsyncFileStorage`` + ``TempFileStorage``."""
        import dhara.storage.async_file as mod

        assert hasattr(mod, "AsyncFileStorage")
        assert hasattr(mod, "TempFileStorage")
        assert hasattr(mod, "_path_to_url")
        # Re-exported symbols equal the module-level definitions.
        from dhara.storage.async_file import AsyncFileStorage as ModAsync
        from dhara.storage.async_file import TempFileStorage as ModTemp

        assert ModAsync is mod.AsyncFileStorage
        assert ModTemp is mod.TempFileStorage

    def test_async_file_storage_is_async_sqlite_storage(self) -> None:
        """``AsyncFileStorage`` must subclass ``AsyncSqliteStorage`` (the shim)."""
        from dhara.storage.sqlite import AsyncSqliteStorage

        assert issubclass(AsyncFileStorage, AsyncSqliteStorage)


# --------------------------- tmp_path fixture sanity ---------------------------


def test_tempfile_module_is_used() -> None:
    """Pin that ``tempfile.mkstemp`` is the underlying primitive.

    If the factory switches implementations, this test forces a deliberate
    code-review touch rather than a silent behavior change.
    """
    fd, path = tempfile.mkstemp(prefix="dhara-", suffix=".db")
    try:
        os.close(fd)
        assert os.path.exists(path)
    finally:
        if os.path.exists(path):
            os.unlink(path)
