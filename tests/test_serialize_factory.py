"""Tests for serializer factory."""

import pytest

from dhara.serialize.base import Serializer
from dhara.serialize.factory import create_serializer


class TestCreateSerializer:
    """Tests for create_serializer factory function."""

    def test_default_backend_is_msgspec(self):
        s = create_serializer()
        assert type(s).__name__ == "MsgspecSerializer"

    @pytest.mark.parametrize("backend", ["pickle", "msgspec", "fallback"])
    def test_creates_installed_backends(self, backend):
        s = create_serializer(backend=backend)
        assert isinstance(s, Serializer)

    def test_dill_backend_raises_import_error_without_dill(self):
        """dill is optional — should raise ImportError if not installed."""
        try:
            import dill  # noqa: F401
            pytest.skip("dill is installed, test not applicable")
        except ImportError:
            with pytest.raises(ImportError, match="dill"):
                create_serializer(backend="dill")

    def test_unknown_backend_raises_value_error(self):
        with pytest.raises(ValueError, match="Unknown serializer"):
            create_serializer(backend="unknown")

    def test_invalid_backend_type_raises_value_error(self):
        with pytest.raises(ValueError):
            create_serializer(backend=123)

    def test_kwargs_passed_to_backend(self):
        s = create_serializer(backend="pickle", protocol=4)
        assert s.protocol == 4

    def test_msgspec_kwargs_forwarded(self):
        s = create_serializer(backend="msgspec", format="json")
        assert s.format == "json"

    def test_fallback_with_allow_dill(self):
        try:
            import dill  # noqa: F401
        except ImportError:
            pytest.skip("dill not installed")
        s = create_serializer(backend="fallback", allow_dill=True)
        assert s.allow_dill is True

    def test_fallback_default_no_dill(self):
        s = create_serializer(backend="fallback")
        assert s.allow_dill is False

    def test_invalid_kwargs_raises_type_error(self):
        with pytest.raises(TypeError, match="Invalid arguments"):
            create_serializer(backend="msgspec", nonexistent_param=42)

    def test_empty_string_backend_raises_value_error(self):
        with pytest.raises(ValueError):
            create_serializer(backend="")
