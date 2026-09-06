"""
pytest configuration and shared fixtures for Durus tests.

This file provides common fixtures used across multiple test files,
migrated from the legacy test/ directory.
"""

from unittest.mock import MagicMock
import sys
import types

# NOTE on duckdb stubbing: there is NO duckdb stub here on purpose.
#
# The two unit tests that need a mocked duckdb (because their production
# code transitively imports it and the duckdb C extension breaks under
# coverage tracing) carry their own local ``sys.modules.setdefault("duckdb",
# MagicMock())`` at the top of the file: tests/unit/test_lock_routes.py
# and tests/unit/test_adapter_tools_extended.py.
#
# Stubbing duckdb globally here would silently break the integration tests
# (tests/integration/mcp/test_lock_routes_integration.py and friends) that
# use real duckdb as their backing store — the stub turns duckdb.connect()
# into a MagicMock, so every chained call returns a mock object and the
# assertions fail with confusing errors (TypeError on json.loads(MagicMock)).
# Real duckdb must reach those tests intact.

# Stub out the ``key_value`` package tree so that ``beartype_this_package()``
# (which runs as a top-level side effect in ``key_value/aio/__init__.py``)
# never executes under pytest-cov. The beartype import hook installed by that
# call races with coverage tracing on Python 3.14 and crashes pytest collection.
#
# Why this is test-only and safe:
#   * Production code never runs under pytest-cov, so production is unaffected.
#   * dhara itself does not import ``key_value``; only ``fastmcp`` (a transitive
#     dep) does, and fastmcp is only used by MCP code paths.
#   * ``fastmcp/__init__.py`` imports ``key_value.aio.*`` at module-load time,
#     so the hook fires on the very first ``import fastmcp``. Stubbing
#     ``key_value.aio`` before pytest discovery prevents that.
#   * Tests that exercise MCP code paths already use ``FastMCP`` as a class
#     reference; they don't construct ``MemoryStore`` or ``PydanticAdapter``
#     directly, so a MagicMock stand-in is observationally equivalent.
class _StubPackage(types.ModuleType):
    """Module stub with ``__path__`` set so dotted-name imports resolve."""

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.__path__ = []  # makes this a package, not a leaf module


# Leaf submodules fastmcp pulls in across all of its server-side code paths.
# Every ancestor in the dotted path is registered as ``_StubPackage`` so that
# ``from key_value.aio.X.Y import Z`` can resolve each segment via sys.modules.
_KEY_VALUE_LEAVES: tuple[str, ...] = (
    "key_value.aio.adapters.pydantic",
    "key_value.aio.protocols",
    "key_value.aio.protocols.key_value",
    "key_value.aio.stores.memory",
    "key_value.aio.stores.redis",
    "key_value.aio.stores.filetree",
    "key_value.aio.wrappers.limit_size",
    "key_value.aio.wrappers.statistics",
    "key_value.aio.wrappers.statistics.wrapper",
    "key_value.aio.wrappers.encryption",
)

for _leaf in _KEY_VALUE_LEAVES:
    sys.modules.setdefault(_leaf, MagicMock())
    _parts = _leaf.split(".")
    for _i in range(1, len(_parts)):
        _ancestor = ".".join(_parts[:_i])
        if _ancestor not in sys.modules:
            sys.modules[_ancestor] = _StubPackage(_ancestor)

from os import unlink
from os.path import exists

import pytest
import pytest_asyncio

from dhara.core import AsyncConnection, Connection
from dhara.storage import AsyncMemoryStorage, MemoryStorage
from dhara.storage.async_file import AsyncFileStorage


@pytest.fixture
def memory_storage():
    return MemoryStorage()


@pytest.fixture
def async_memory_storage():
    return AsyncMemoryStorage()


@pytest.fixture
def temp_file_storage():
    from tempfile import mktemp

    filename = mktemp(suffix=".dhara")
    # ``AsyncFileStorage`` is a path-compatible drop-in for the legacy
    # ``FileStorage``; the legacy SHELF-format class is being removed by
    # the async-first migration.  Tests that consumed ``temp_file_storage``
    # as a sync ``Storage`` instance must now ``await`` its lifecycle;
    # the few call sites in this tree (test_core_connection_methods)
    # adapt to the async shape below.
    storage = AsyncFileStorage(filename)
    yield storage
    if exists(filename):
        unlink(filename)


@pytest.fixture
def connection(memory_storage):
    return Connection(memory_storage)


@pytest_asyncio.fixture
async def async_connection(async_memory_storage):
    """AsyncConnection backed by AsyncMemoryStorage for async tests."""
    return await AsyncConnection.new(async_memory_storage)


@pytest.fixture
def file_connection(temp_file_storage):
    # ``file_connection`` is used by tests that expect a real on-disk
    # store; the new ``AsyncFileStorage`` requires an async init, so the
    # fixture spins up an ``AsyncConnection`` and wraps it in the
    # production ``_SyncConnectionFacade`` so callers can keep using the
    # sync ``get_root()`` / ``commit()`` / ``abort()`` API. The facade
    # dispatches via ``asyncio.run_coroutine_threadsafe`` which requires a
    # live event loop on a background thread.
    import asyncio
    import threading

    from dhara.mcp.server_core import _SyncConnectionFacade

    loop = asyncio.new_event_loop()

    def _runner() -> None:
        asyncio.set_event_loop(loop)
        loop.run_forever()

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    loop._dhara_wire_thread = thread  # ty: ignore[unresolved-attribute]

    async def _open() -> AsyncConnection:
        await temp_file_storage.init()
        return await AsyncConnection.new(temp_file_storage)

    async_conn = asyncio.run_coroutine_threadsafe(_open(), loop).result()
    return _SyncConnectionFacade(async_conn, loop)


@pytest.fixture
def msgspec_serializer():
    from dhara.serialize import MsgspecSerializer
    return MsgspecSerializer()


@pytest.fixture
def fallback_serializer():
    from dhara.serialize import FallbackSerializer
    return FallbackSerializer()


@pytest.fixture
def temp_storage_dir():
    from tempfile import TemporaryDirectory
    with TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def empty_root(connection):
    return connection.get_root()


@pytest.fixture
def sample_data():
    return {
        "users": {
            "alice": {"email": "alice@example.com", "age": 30},
            "bob": {"email": "bob@example.com", "age": 25},
        },
        "settings": {
            "theme": "dark",
            "language": "en",
        },
    }


@pytest.fixture
def large_dataset():
    return {f"key_{i}": f"value_{i}" * 100 for i in range(1000)}


@pytest.fixture
def persistent_class():
    from dhara import Persistent

    class TestObject(Persistent):
        def __init__(self, value):
            self.value = value

    return TestObject


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register the ``--pg-url`` option consumed by Postgres-backed tests.

    Without this hook, ``config.getoption('--pg-url')`` raises
    ``AttributeError: 'Namespace' object has no attribute '--pg-url'`` and
    the live Postgres fixtures in
    ``tests/integration/mcp/test_lock_pg_migration.py`` blow up at fixture
    setup instead of cleanly skipping when ``DHARA_TEST_PG_URL`` is unset.
    """
    parser.addoption(
        "--pg-url",
        action="store",
        default=None,
        help="Postgres connection URL for live integration tests "
        "(falls back to DHARA_TEST_PG_URL env var).",
    )
