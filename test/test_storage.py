"""
$URL$
$Id$
"""

import pytest

from dhruva.serialize.adapter import pack_record
from dhruva.storage.base import MemoryStorage
from dhruva.utils import as_bytes, int8_to_str


class Test:
    def test_check_memory_storage(self):
        b = MemoryStorage()
        assert b.new_oid() == int8_to_str(0)
        assert b.new_oid() == int8_to_str(1)
        assert b.new_oid() == int8_to_str(2)
        with pytest.raises(KeyError):
            b.load(int8_to_str(0))
        record = pack_record(int8_to_str(0), as_bytes("ok"), as_bytes(""))
        b.begin()
        b.store(int8_to_str(0), record)
        b.end()
        b.sync()
        b.begin()
        b.store(
            int8_to_str(1), pack_record(int8_to_str(1), as_bytes("no"), as_bytes(""))
        )
        b.end()
        assert len(list(b.gen_oid_record())) == 1
        assert record == b.load(int8_to_str(0))
        records = b.bulk_load([int8_to_str(0), int8_to_str(1)])
        assert len(list(records)) == 2
        records = b.bulk_load([int8_to_str(0), int8_to_str(1), int8_to_str(2)])
        with pytest.raises(KeyError):
            list(records)
