"""Extended coverage tests for ``dhara.serialize.factory``.

After the 0.11.0 CWE-502 migration, only the ``msgpack`` and ``msgspec``
backends are supported. The factory's ``Literal[...]`` type reflects this.
These tests sit alongside ``tests/test_serialize_factory.py`` and target the
``tests/unit/`` namespace so coverage is measured when running the unit-test
subset (the original file lives at ``tests/`` and is not picked up under
``tests/unit/``).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from dhara.serialize.base import Serializer
from dhara.serialize.factory import create_serializer
from dhara.serialize.msgpack import MsgpackSerializer
from dhara.serialize.msgspec import MsgspecSerializer


class TestCreateSerializerBackends:
    """Backend selection branches."""

    def test_default_backend_is_msgspec(self) -> None:
        s = create_serializer()
        assert isinstance(s, MsgspecSerializer)

    def test_explicit_msgspec_backend(self) -> None:
        s = create_serializer(backend="msgspec")
        assert isinstance(s, MsgspecSerializer)

    def test_msgpack_backend_returns_msgpack_serializer(self) -> None:
        s = create_serializer(backend="msgpack")
        assert isinstance(s, MsgpackSerializer)

    def test_msgpack_backend_uses_underlying_msgspec(self) -> None:
        s = create_serializer(backend="msgpack")
        # ``MsgpackSerializer`` wraps an internal ``MsgspecSerializer``;
        # verify the wrapper is wired up rather than being a stub.
        underlying = getattr(s, "_msgspec", None)
        assert underlying is not None
        assert isinstance(underlying, MsgspecSerializer)

    def test_msgpack_backend_accepts_no_args(self) -> None:
        # ``MsgpackSerializer`` has no constructor args; the factory must
        # not forward kwargs through to it. ``MsgpackSerializer.__init__``
        # rejects any kwargs with a ``TypeError`` (covered by the
        # ``test_invalid_kwargs_raises_type_error`` test), so passing any
        # would raise — keep this assertion at the no-kwargs happy path.
        s = create_serializer(backend="msgpack")
        assert isinstance(s, MsgpackSerializer)


class TestCreateSerializerReturnType:
    """Return-type invariants."""

    def test_returns_serializer_instance(self) -> None:
        assert isinstance(create_serializer(backend="msgspec"), Serializer)

    def test_returns_serializer_instance_msgpack(self) -> None:
        assert isinstance(create_serializer(backend="msgpack"), Serializer)

    def test_msgpack_serializer_round_trip(self) -> None:
        s = create_serializer(backend="msgpack")
        payload = {"a": 1, "b": [2, 3, 4], "c": "hello"}
        data = s.serialize(payload)
        assert isinstance(data, bytes)
        assert s.deserialize(data) == payload

    def test_msgspec_serializer_round_trip(self) -> None:
        s = create_serializer(backend="msgspec")
        payload = {"a": 1, "b": [2, 3, 4], "c": "hello"}
        data = s.serialize(payload)
        assert isinstance(data, bytes)
        assert s.deserialize(data) == payload


class TestCreateSerializerBackendErrors:
    """``else`` branch — unknown backend."""

    @pytest.mark.parametrize(
        "backend",
        ["pickle", "dill", "fallback", "json", "yaml", "toml", "marshal"],
    )
    def test_removed_backends_raise_value_error(self, backend: str) -> None:
        """Removed/invalid backend names must raise ``ValueError``."""
        with pytest.raises(ValueError, match="Unknown serializer"):
            create_serializer(backend=backend)

    def test_empty_string_backend_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="Unknown serializer"):
            create_serializer(backend="")

    def test_value_error_message_mentions_valid_choices(self) -> None:
        with pytest.raises(ValueError) as excinfo:
            create_serializer(backend="something-weird")
        msg = str(excinfo.value)
        assert "something-weird" in msg
        assert "msgpack" in msg
        assert "msgspec" in msg

    def test_invalid_backend_type_raises_value_error(self) -> None:
        # The ``Literal[...]`` type hint enforces strings at type-check time,
        # but the runtime guard is a plain ``elif`` chain. Pass a non-string
        # at runtime to verify the ``else`` branch fires.
        with pytest.raises(ValueError, match="Unknown serializer"):
            create_serializer(backend=123)  # type: ignore[arg-type]

    def test_invalid_backend_type_none_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="Unknown serializer"):
            create_serializer(backend=None)  # type: ignore[arg-type]


class TestCreateSerializerKwargs:
    """``kwargs`` forwarding to the resolved serializer class."""

    def test_msgspec_format_kwarg_forwarded(self) -> None:
        s = create_serializer(backend="msgspec", format="json")
        assert s.format == "json"

    def test_msgspec_format_msgpack_default(self) -> None:
        s = create_serializer(backend="msgspec")
        assert s.format == "msgpack"

    def test_msgspec_use_builtins_kwarg_forwarded(self) -> None:
        s = create_serializer(backend="msgspec", use_builtins=False)
        assert s.use_builtins is False

    def test_msgspec_allowed_modules_kwarg_forwarded(self) -> None:
        custom = {"dhara", "collections"}
        s = create_serializer(
            backend="msgspec",
            allowed_modules=custom,
        )
        assert s.allowed_modules == custom

    def test_invalid_msgspec_kwargs_raise_type_error(self) -> None:
        with pytest.raises(TypeError, match="Invalid arguments"):
            create_serializer(backend="msgspec", nonexistent_param=42)

    def test_type_error_message_includes_backend(self) -> None:
        with pytest.raises(TypeError) as excinfo:
            create_serializer(backend="msgspec", nonexistent_param=42)
        msg = str(excinfo.value)
        assert "msgspec" in msg


class TestCreateSerializerErrorWrapping:
    """``try/except ImportError`` and ``try/except TypeError`` branches.

    The ``try`` block in ``create_serializer`` wraps the
    ``serializer_class(**kwargs)`` instantiation call — *not* the
    in-function import of the serializer module. To exercise the
    ``except ImportError`` branch we have to make the serializer
    *constructor* itself raise ``ImportError`` (e.g. an optional
    dependency that loads at instantiation time). The simplest way to
    do that without touching production code is to patch the
    serializer class's ``__init__`` to raise on entry.
    """

    def test_import_error_is_wrapped_with_backend_context(self) -> None:
        """When the serializer class constructor raises ``ImportError``,
        the factory must re-raise ``ImportError`` with a backend-named
        message."""
        sentinel = ImportError("optional dep missing")

        def _raise_on_init(self: object) -> None:
            raise sentinel

        with patch.object(MsgspecSerializer, "__init__", _raise_on_init):
            with pytest.raises(ImportError) as excinfo:
                create_serializer(backend="msgspec")

        msg = str(excinfo.value)
        assert "msgspec" in msg
        assert "required dependencies" in msg

    def test_msgpack_import_error_is_wrapped_with_backend_context(self) -> None:
        """Same wrapping for the ``msgpack`` branch."""
        sentinel = ImportError("optional dep missing")

        def _raise_on_init(self: object) -> None:
            raise sentinel

        with patch.object(MsgpackSerializer, "__init__", _raise_on_init):
            with pytest.raises(ImportError) as excinfo:
                create_serializer(backend="msgpack")

        msg = str(excinfo.value)
        assert "msgpack" in msg
        assert "required dependencies" in msg

    def test_import_error_preserves_chained_cause(self) -> None:
        """The wrapped ``ImportError`` must chain to the original via
        ``raise ... from e`` so the traceback is preserved."""
        sentinel = ImportError("optional dep missing")

        def _raise_on_init(self: object) -> None:
            raise sentinel

        with patch.object(MsgspecSerializer, "__init__", _raise_on_init):
            with pytest.raises(ImportError) as excinfo:
                create_serializer(backend="msgspec")

        assert excinfo.value.__cause__ is sentinel

    def test_type_error_preserves_chained_cause(self) -> None:
        """The wrapped ``TypeError`` must chain to the original via
        ``raise ... from e``."""
        with pytest.raises(TypeError) as excinfo:
            create_serializer(backend="msgspec", totally_made_up_arg=True)
        assert excinfo.value.__cause__ is not None
        assert isinstance(excinfo.value.__cause__, TypeError)


class TestCreateSerializerSignature:
    """Signature-level invariants."""

    def test_takes_keyword_only_backend(self) -> None:
        import inspect

        sig = inspect.signature(create_serializer)
        assert "backend" in sig.parameters
        assert sig.parameters["backend"].default == "msgspec"

    def test_accepts_arbitrary_kwargs(self) -> None:
        import inspect

        sig = inspect.signature(create_serializer)
        # ``**kwargs: Any`` shows up as a VAR_KEYWORD parameter.
        var_kw = [
            p for p in sig.parameters.values()
            if p.kind == inspect.Parameter.VAR_KEYWORD
        ]
        assert len(var_kw) == 1


class TestCreateSerializerRepeatedInvocations:
    """Each invocation must construct a fresh instance."""

    def test_two_invocations_return_distinct_instances(self) -> None:
        s1 = create_serializer(backend="msgspec")
        s2 = create_serializer(backend="msgspec")
        assert s1 is not s2

    def test_two_msgpack_invocations_return_distinct_instances(self) -> None:
        s1 = create_serializer(backend="msgpack")
        s2 = create_serializer(backend="msgpack")
        assert s1 is not s2
