"""Lazy-export map tests for ``dhara/__init__.py``.

Verifies the public surface area of the top-level ``dhara`` package
after the CWE-502 / pickle-removal migration:

* The new safe serializer names (``MsgpackSerializer``,
  ``MsgspecSerializer``, ``create_serializer``) resolve.
* The removed legacy symbols (``PickleSerializer``, ``DillSerializer``,
  ``FallbackSerializer``, ``ObjectReader``) raise ``AttributeError``
  when imported at the top level. (They may still exist under
  ``dhara.serialize``; only the top-level package must reject them.)
* ``dhara.__version__`` is pinned to ``"0.11.0"``.

The top-level package uses a ``__getattr__`` lazy-export shim for
serializer symbols, so an ``AttributeError`` here proves the shim is
not (and must not be) back-filled with removed backends.
"""

from __future__ import annotations

import pytest

import dhara
from dhara.serialize import MsgpackSerializer as _MsgpackSerializer
from dhara.serialize import MsgspecSerializer as _MsgspecSerializer
from dhara.serialize import create_serializer as _create_serializer


# ---------------------------------------------------------------------------
# Version
# ---------------------------------------------------------------------------


class TestVersion:
    """``dhara.__version__`` is pinned to the post-migration release."""

    def test_version_is_0_11_0(self):
        assert dhara.__version__ == "0.11.0"

    def test_version_is_string(self):
        assert isinstance(dhara.__version__, str)


# ---------------------------------------------------------------------------
# New (post-migration) symbols resolve at the top level
# ---------------------------------------------------------------------------


class TestNewSymbolsResolve:
    """The new safe serializer names resolve at the top level."""

    def test_msgpack_serializer_resolves(self):
        # ``from dhara import MsgpackSerializer`` must succeed.
        from dhara import MsgpackSerializer  # noqa: F401

        assert MsgpackSerializer is _MsgpackSerializer

    def test_msgspec_serializer_resolves(self):
        from dhara import MsgspecSerializer  # noqa: F401

        assert MsgspecSerializer is _MsgspecSerializer

    def test_create_serializer_resolves(self):
        from dhara import create_serializer  # noqa: F401

        assert create_serializer is _create_serializer

    def test_msgpack_serializer_is_in_all(self):
        # The public surface must list it; otherwise ``dir(dhara)``
        # would not show the name to introspectors.
        assert "MsgpackSerializer" in dhara.__all__

    def test_msgspec_serializer_is_in_all(self):
        assert "MsgspecSerializer" in dhara.__all__

    def test_create_serializer_is_in_all(self):
        assert "create_serializer" in dhara.__all__

    def test_msgpack_serializer_can_instantiate(self):
        from dhara import MsgpackSerializer

        instance = MsgpackSerializer()
        assert instance is not None

    def test_msgspec_serializer_can_instantiate(self):
        from dhara import MsgspecSerializer

        instance = MsgspecSerializer()
        assert instance is not None

    def test_create_serializer_can_instantiate_msgpack(self):
        from dhara import create_serializer

        instance = create_serializer(backend="msgpack")
        assert isinstance(instance, _MsgpackSerializer)

    def test_create_serializer_can_instantiate_msgspec(self):
        from dhara import create_serializer

        instance = create_serializer(backend="msgspec")
        assert isinstance(instance, _MsgspecSerializer)


# ---------------------------------------------------------------------------
# Removed (legacy) symbols raise AttributeError
# ---------------------------------------------------------------------------


class TestLegacySymbolsRemoved:
    """The removed legacy backends are NOT exported at the top level."""

    def test_dill_serializer_raises(self):
        with pytest.raises(AttributeError):
            _ = dhara.DillSerializer

    def test_pickle_serializer_raises(self):
        with pytest.raises(AttributeError):
            _ = dhara.PickleSerializer

    def test_fallback_serializer_raises(self):
        with pytest.raises(AttributeError):
            _ = dhara.FallbackSerializer

    def test_object_reader_removed_from_top_level(self):
        # ObjectReader used to live in ``dhara``; it is no longer exported
        # from the top-level package. It still exists under
        # ``dhara.serialize`` for internal use.
        with pytest.raises(AttributeError):
            _ = dhara.ObjectReader

    def test_object_writer_removed_from_top_level(self):
        # Same situation as ObjectReader.
        with pytest.raises(AttributeError):
            _ = dhara.ObjectWriter

    def test_legacy_symbols_not_in_all(self):
        # The public surface must not advertise the removed backends.
        for name in (
            "DillSerializer",
            "PickleSerializer",
            "FallbackSerializer",
            "ObjectReader",
            "ObjectWriter",
        ):
            assert name not in dhara.__all__, (
                f"{name} should be removed from dhara.__all__"
            )


# ---------------------------------------------------------------------------
# dir() / __getattr__ interaction
# ---------------------------------------------------------------------------


class TestDirAndGetattr:
    """The lazy export map is consistent with ``dir()``."""

    def test_new_serializer_names_visible_in_dir(self):
        names = dir(dhara)
        assert "MsgpackSerializer" in names
        assert "MsgspecSerializer" in names
        assert "create_serializer" in names

    def test_removed_names_not_visible_in_dir(self):
        names = dir(dhara)
        for name in (
            "DillSerializer",
            "PickleSerializer",
            "FallbackSerializer",
            "ObjectReader",
            "ObjectWriter",
        ):
            assert name not in names, (
                f"{name} should not appear in dir(dhara)"
            )

    def test_unknown_name_raises(self):
        with pytest.raises(AttributeError):
            _ = dhara.DoesNotExist

    def test_version_visible_in_dir(self):
        assert "__version__" in dir(dhara)
