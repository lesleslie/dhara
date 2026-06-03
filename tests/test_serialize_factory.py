"""Tests for serializer factory.

After the 0.11.0 CWE-502 migration, only the `msgpack` and `msgspec`
backends are supported. The factory's `Literal[...]` type reflects this.
"""

import pytest

from dhara.serialize.base import Serializer
from dhara.serialize.factory import create_serializer
from dhara.serialize.msgpack import MsgpackSerializer
from dhara.serialize.msgspec import MsgspecSerializer


class TestCreateSerializer:
    """Tests for create_serializer factory function."""

    def test_default_backend_is_msgspec(self):
        s = create_serializer()
        assert type(s).__name__ == "MsgspecSerializer"

    @pytest.mark.parametrize("backend", ["msgpack", "msgspec"])
    def test_creates_installed_backends(self, backend):
        s = create_serializer(backend=backend)
        assert isinstance(s, Serializer)

    def test_msgpack_backend_returns_msgpack_serializer(self):
        s = create_serializer(backend="msgpack")
        assert isinstance(s, MsgpackSerializer)

    def test_msgspec_backend_returns_msgspec_serializer(self):
        s = create_serializer(backend="msgspec")
        assert isinstance(s, MsgspecSerializer)

    def test_unknown_backend_raises_value_error(self):
        with pytest.raises(ValueError, match="Unknown serializer"):
            create_serializer(backend="unknown")

    def test_pickle_backend_no_longer_supported(self):
        """The pickle backend was removed in 0.11.0 (CWE-502 migration)."""
        with pytest.raises(ValueError, match="Unknown serializer"):
            create_serializer(backend="pickle")

    def test_dill_backend_no_longer_supported(self):
        """The dill backend was removed in 0.11.0."""
        with pytest.raises(ValueError, match="Unknown serializer"):
            create_serializer(backend="dill")

    def test_fallback_backend_no_longer_supported(self):
        """The fallback backend was removed in 0.11.0."""
        with pytest.raises(ValueError, match="Unknown serializer"):
            create_serializer(backend="fallback")

    def test_invalid_backend_type_raises_value_error(self):
        with pytest.raises(ValueError):
            create_serializer(backend=123)

    def test_msgspec_kwargs_forwarded(self):
        s = create_serializer(backend="msgspec", format="json")
        assert s.format == "json"

    def test_msgpack_backend_accepts_no_args(self):
        """MsgpackSerializer has no constructor args (protocol shim removed)."""
        s = create_serializer(backend="msgpack")
        # No protocol= kwarg supported
        assert s is not None

    def test_invalid_kwargs_raises_type_error(self):
        with pytest.raises(TypeError, match="Invalid arguments"):
            create_serializer(backend="msgspec", nonexistent_param=42)

    def test_empty_string_backend_raises_value_error(self):
        with pytest.raises(ValueError):
            create_serializer(backend="")
