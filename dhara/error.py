"""
from __future__ import annotations
$URL$
$Id$
"""

from dhara.utils import str_to_int8


class DruvaError(Exception):
    """Dhara persistent storage error."""


class DruvaKeyError(KeyError, DruvaError):
    """Key not found in database."""

    def __init__(self, oids: list | None = None) -> None:
        super().__init__()
        self.oids = oids

    def __str__(self):
        if not self.oids:
            return ""
        first_oid = self.oids[0]
        return str(first_oid and str_to_int8(first_oid))


class ConflictError(DruvaError):
    """
    There has been some kind of conflict involving the named oids.
    """

    def __init__(self, oids=None):
        self.oids = oids

    def __str__(self):
        if self.oids is None:
            return "conflicting oids not available"
        else:
            if len(self.oids) > 1:
                s = "oids=[%s ...]"
            else:
                s = "oids=[%s]"
            first_oid = self.oids[0]
            return s % (first_oid and str_to_int8(first_oid))


class WriteConflictError(ConflictError):
    """
    Two transactions tried to modify the same object at once.
    """


class ReadConflictError(ConflictError):
    """
    Conflict detected when object was loaded.
    An attempt was made to read an object that has changed in another
    transaction (eg. another process).
    """


class ProtocolError(DruvaError):
    """
    An error occurred during communication between the storage server
    and the client.
    """


# Backward compatibility alias for the historical Durus 4.x naming.
# Removed: callers that still reference the legacy name should update to
# ``DruvaKeyError`` (or ``ConflictError`` for storage-state conflicts).
# DurusKeyError = DruvaKeyError
