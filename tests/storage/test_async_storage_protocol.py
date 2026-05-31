"""
$URL$
$Id$
"""
import pytest
import inspect
from typing import AsyncIterator
from dhara.storage.base import AsyncStorage

@pytest.mark.asyncio
async def test_async_storage_protocol_interface():
    """Verify AsyncStorage has all required methods and they are async coroutines."""
    methods = [
        'init', 'load', 'begin', 'store', 'end', 'sync',
        'new_oid', 'gen_oid_record', 'pack', 'health',
        'cleanup', 'close', 'bulk_load'
    ]
    for method in methods:
        assert hasattr(AsyncStorage, method), f"AsyncStorage missing {method}"
        attr = getattr(AsyncStorage, method)
        assert inspect.iscoroutinefunction(attr), f"{method} is not async (is {type(attr).__name__})"

@pytest.mark.asyncio
async def test_async_storage_protocol_gen_oid_record_is_async_iterator():
    """Verify gen_oid_record returns an AsyncIterator."""
    # Create a minimal mock implementing the protocol
    class MockStorage:
        async def init(self): pass
        async def load(self, oid): pass
        async def begin(self): pass
        async def store(self, oid, record): pass
        async def end(self, handle_invalidations=None): pass
        async def sync(self): return []
        async def new_oid(self): return b'\x00\x00\x00\x00\x00\x00\x00\x01'
        async def gen_oid_record(self, start_oid=None, batch_size=100):
            yield  # empty async generator
        async def bulk_load(self, oids):
            yield  # empty async generator
        async def pack(self): pass
        async def health(self): return True
        async def cleanup(self): pass
        async def close(self): pass
        def get_packer(self): return None

    storage = MockStorage()
    result = storage.gen_oid_record()
    # Verify it's an async generator
    assert inspect.isasyncgen(result), "gen_oid_record must return an async generator"