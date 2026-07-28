#!/usr/bin/env python
"""
This script creates a new storage with the oids of all instances,
(except the root) reassigned so that they are in a minimal range,
which makes FileStorage (when using the Shelf format) more compact
and efficient for some operations.
"""

import asyncio
import sys
from os.path import exists
from tempfile import TemporaryFile

from dhara.core.connection import AsyncConnection
from dhara.storage.sqlite import AsyncSqliteStorage

if sys.version_info < (3, 0):
    from cPickle import dump, load
else:
    from pickle import dump, load


def usage():
    print(f"{sys.argv[0]} <old-file-storage> <new-file-storage>")
    print(__doc__)
    raise SystemExit


async def main(old_file, new_file):
    if old_file.startswith("-"):
        usage()
    if new_file.startswith("-"):
        usage()
    assert not exists(new_file)
    old_storage = AsyncSqliteStorage(old_file)
    await old_storage.init()
    connection = await AsyncConnection.new(old_storage)
    # Long-lived handle: tmpfile is seeked and read again after the
    # pickle round-trip; `with` would close it before the second use.
    tmpfile = TemporaryFile()  # noqa: SIM115
    print("pickling from " + old_file)
    dump((await connection.get_root()).__getstate__(), tmpfile, 2)
    await connection.pack()
    await old_storage.close()
    tmpfile.seek(0)
    new_storage = AsyncSqliteStorage(new_file)
    await new_storage.init()
    connection2 = await AsyncConnection.new(new_storage)
    print("unpickling")
    (await connection2.get_root()).__setstate__(load(tmpfile))
    (await connection2.get_root())._p_note_change()
    print("commit to " + new_file)
    await connection2.commit()
    print("pack")
    await connection2.pack()
    await new_storage.close()


if __name__ == "__main__":
    if len(sys.argv) != 3:
        usage()
    asyncio.run(main(*sys.argv[1:]))
