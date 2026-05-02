"""Tests for dhara.serialize.adapter — ObjectReader, ObjectWriter wrappers.

NOTE: The adapter module wraps legacy pickle-based serialization. Pickle usage
in the underlying serialize_legacy module is intentional for backward compatibility.
These tests mock the legacy layer and verify the adapter wrapper behavior.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


class TestObjectReader:
    def test_init_default_serializer(self):
        from dhara.serialize.adapter import ObjectReader

        conn = MagicMock()
        reader = ObjectReader(conn)
        assert reader.connection is conn
        assert reader._new_serializer is not None

    def test_init_custom_serializer(self):
        from dhara.serialize.adapter import ObjectReader
        from dhara.serialize.msgspec import MsgspecSerializer

        conn = MagicMock()
        serializer = MsgspecSerializer(format="msgpack")
        reader = ObjectReader(conn, serializer=serializer)
        assert reader._new_serializer is serializer

    def test_init_calls_parent(self):
        from dhara.serialize.adapter import ObjectReader

        conn = MagicMock()
        with patch("dhara.serialize.adapter.OldObjectReader.__init__") as mock_parent:
            reader = ObjectReader(conn)
            mock_parent.assert_called_once()
            args = mock_parent.call_args[0]
            assert args[1] is conn

    def test_get_ghost_delegates_to_parent(self):
        from dhara.serialize.adapter import ObjectReader

        conn = MagicMock()
        record = b"test_record"
        with patch("dhara.serialize.adapter.OldObjectReader.get_ghost") as mock_ghost:
            reader = ObjectReader(conn)
            result = reader.get_ghost(record)
            mock_ghost.assert_called_once()
            assert mock_ghost.call_args[0][1] == record

    def test_get_state_delegates_to_parent(self):
        from dhara.serialize.adapter import ObjectReader

        conn = MagicMock()
        record = b"test_record"
        with patch("dhara.serialize.adapter.OldObjectReader.get_state") as mock_state:
            reader = ObjectReader(conn)
            result = reader.get_state(record, load=True)
            mock_state.assert_called_once()
            assert mock_state.call_args[0][1] == record
            assert mock_state.call_args[0][2] is True

    def test_get_state_load_false(self):
        from dhara.serialize.adapter import ObjectReader

        conn = MagicMock()
        record = b"test_record"
        with patch("dhara.serialize.adapter.OldObjectReader.get_state") as mock_state:
            reader = ObjectReader(conn)
            result = reader.get_state(record, load=False)
            mock_state.assert_called_once()
            assert mock_state.call_args[0][2] is False


class TestObjectWriter:
    def test_init_default_serializer(self):
        from dhara.serialize.adapter import ObjectWriter

        conn = MagicMock()
        writer = ObjectWriter(conn)
        assert writer.connection is conn
        assert writer._new_serializer is not None

    def test_init_custom_serializer(self):
        from dhara.serialize.adapter import ObjectWriter
        from dhara.serialize.msgspec import MsgspecSerializer

        conn = MagicMock()
        serializer = MsgspecSerializer(format="json")
        writer = ObjectWriter(conn, serializer=serializer)
        assert writer._new_serializer is serializer

    def test_init_calls_parent(self):
        from dhara.serialize.adapter import ObjectWriter

        conn = MagicMock()
        with patch("dhara.serialize.adapter.OldObjectWriter.__init__") as mock_parent:
            writer = ObjectWriter(conn)
            mock_parent.assert_called_once()
            assert mock_parent.call_args[0][1] is conn

    def test_get_state_delegates_to_parent(self):
        from dhara.serialize.adapter import ObjectWriter

        conn = MagicMock()
        obj = MagicMock()
        with patch("dhara.serialize.adapter.OldObjectWriter.get_state") as mock_state:
            writer = ObjectWriter(conn)
            result = writer.get_state(obj)
            mock_state.assert_called_once()
            assert mock_state.call_args[0][1] is obj

    def test_gen_new_objects_delegates_to_parent(self):
        from dhara.serialize.adapter import ObjectWriter

        conn = MagicMock()
        obj = MagicMock()
        with patch("dhara.serialize.adapter.OldObjectWriter.gen_new_objects") as mock_gen:
            writer = ObjectWriter(conn)
            result = list(writer.gen_new_objects(obj))
            mock_gen.assert_called_once()
            assert mock_gen.call_args[0][1] is obj


class TestModuleExports:
    def test_all_exports(self):
        from dhara.serialize import adapter

        expected = [
            "ObjectReader",
            "ObjectWriter",
            "pack_record",
            "unpack_record",
            "split_oids",
            "persistent_load",
            "extract_class_name",
        ]
        for name in expected:
            assert hasattr(adapter, name), f"Missing export: {name}"
