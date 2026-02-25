"""Adapter to bridge old pickle-based serialization with new Serializer interface.

This module wraps the existing ObjectReader/ObjectWriter from serialize_legacy.py
to work with the new Serializer adapter pattern. This provides backward compatibility
during the transition from Durus 4.x to druva 5.0.
"""

from druva.serialize_legacy import (
    ObjectReader as OldObjectReader,
)
from druva.serialize_legacy import (
    ObjectWriter as OldObjectWriter,
)
from druva.serialize_legacy import (
    extract_class_name,
    pack_record,
    persistent_load,
    split_oids,
    unpack_record,
)


class ObjectReader(OldObjectReader):
    """Wrapper for old ObjectReader with new serializer interface.

    This provides backward compatibility by wrapping the existing ObjectReader
    while allowing integration with the new Serializer adapter pattern.
    """

    def __init__(self, connection, serializer=None):
        """Initialize ObjectReader with optional serializer.

        Args:
            connection: Durus Connection instance
            serializer: Optional Serializer instance (uses MsgspecSerializer if None)
        """
        if serializer is None:
            # Use msgspec for security and performance (default for druva 5.0)
            # For Durus 4.x compatibility, explicitly pass PickleSerializer()
            from druva.serialize.msgspec import MsgspecSerializer

            serializer = MsgspecSerializer(format="msgpack", use_builtins=True)

        self._new_serializer = serializer

        # Call parent __init__ to initialize old ObjectReader
        # The old ObjectReader will still use pickle internally
        OldObjectReader.__init__(self, connection)

    def get_ghost(self, record):
        """Get ghost object from record.

        This method is overridden to integrate with new serializers.
        For now, it delegates to the parent class.

        TODO: Refactor to use Serializer.deserialize()
        """
        return OldObjectReader.get_ghost(self, record)

    def get_state(self, record, load=True):
        """Extract state from record.

        Args:
            record: The record to extract state from
            load: Whether to load the object (default True)

        TODO: Refactor to use Serializer interface
        """
        return OldObjectReader.get_state(self, record, load)


class ObjectWriter(OldObjectWriter):
    """Wrapper for old ObjectWriter with new serializer interface.

    This provides backward compatibility by wrapping the existing ObjectWriter
    while allowing integration with the new Serializer adapter pattern.
    """

    def __init__(self, connection, serializer=None):
        """Initialize ObjectWriter with optional serializer.

        Args:
            connection: Durus Connection instance
            serializer: Optional Serializer instance (uses PickleSerializer if None)
        """
        if serializer is None:
            # Use pickle for backward compatibility with Durus 4.x databases
            from druva.serialize.pickle import PickleSerializer

            serializer = PickleSerializer()

        self._new_serializer = serializer

        # Call parent __init__ to initialize old ObjectWriter
        # The old ObjectWriter will still use pickle internally
        OldObjectWriter.__init__(self, connection)

    def get_state(self, obj):
        """Get serializable state from object.

        This method is overridden to integrate with new serializers.
        For now, it delegates to the parent class.

        TODO: Refactor to use Serializer.get_state()
        """
        return OldObjectWriter.get_state(self, obj)

    def gen_new_objects(self, obj):
        """Generate all new objects reachable from obj.

        TODO: Refactor to use Serializer.serialize()
        """
        return OldObjectWriter.gen_new_objects(self, obj)


__all__ = [
    "ObjectReader",
    "ObjectWriter",
    "pack_record",
    "unpack_record",
    "split_oids",
    "persistent_load",
    "extract_class_name",
]
