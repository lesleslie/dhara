# dhara

[![Code style: crackerjack](https://img.shields.io/badge/code%20style-crackerjack-000042)](https://github.com/lesleslie/crackerjack)
[![Runtime: oneiric](https://img.shields.io/badge/runtime-oneiric-6e5494)](https://github.com/lesleslie/oneiric)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![Python: 3.13+](https://img.shields.io/badge/python-3.13%2B-green)](https://www.python.org/downloads/)

**dhara** is a modern continuation of **Durus**, a persistent object system
for applications written in the Python programming language. It could be
called a noSQL database. However, it does provide "ACID" properties
(Atomicity, Consistency, Isolation, Durability).

The implementation of dhara is not multi-threaded but does provide
concurrency via a client/server model. It is optimized for read heavy
work loads and aggressively caches persistent objects in memory.
For many applications, this design enables good performance with minimal
effort from application programmers.

## Origin

dhara was originally written by the MEMS Exchange software development
team at the Corporation for National Research Initiatives (CNRI). dhara
was designed to be the storage component for the Python-powered web sites
operated by the MEMS Exchange. See `doc/README_CNRI.txt` for more
details.

## Overview

dhara offers an easy way to use and maintain a consistent collection
of object instances used by one or more processes. Access and change
of a persistent instances is managed through a cached Connection
instance which includes `commit()` and `abort()` methods so that changes
are transactional.

## CLI Commands

Dhara provides a unified CLI with three command groups:

### MCP Server Commands (for AI/Agent Workflows)

```bash
dhara mcp start              # Start MCP server
dhara mcp stop               # Stop MCP server
dhara mcp status             # Check server status
dhara mcp health             # Health check
```

### Database Commands (Durus Operations)

```bash
dhara db start               # Start Durus storage server
dhara db client              # Connect to server (interactive)
dhara db pack                # Reclaim storage space
```

Common options for database commands:

- `--file PATH` or `-f PATH` - Database file path
- `--host HOST` or `-h HOST` - Server host (default: 127.0.0.1)
- `--port PORT` or `-p PORT` - Server port (default: 2972)
- `--readonly` - Open in read-only mode

### Dhara-Specific Commands

```bash
dhara adapters               # List registered adapters
dhara storage                # Display storage information
dhara admin                  # Launch admin shell (IPython)
```

## Quick Demo

**Start a Dhara server:**

```bash
dhara db start
```

This starts a Dhara storage server using a temporary file and listening for clients on localhost port 2972.

**Connect as a client:**

```bash
dhara db client
```

This opens an interactive IPython shell connected to the storage server. You have access to a dictionary-like persistent object, `root`. If you make changes to items of `root` and run `connection.commit()`, the changes are written to the file. If you make changes and then run `connection.abort()`, the attributes revert back to the values they had at the last commit.

**Multiple clients:** Run `dhara db client` in another terminal to see how committed changes to `root` in one client are available in other clients when they synchronize via `connection.abort()` or `connection.commit()`.

**Stop the server:** Press *Control-C* in the server terminal.

**Persistence example:**

```bash
# Start server with a persistent file
dhara db server --file test.dhara

# Connect, make changes, commit
dhara db client --file test.dhara
# In the shell:
# >>> root["hello"] = "world"
# >>> connection.commit()

# Stop and restart - data persists
dhara db server --file test.dhara
dhara db client --file test.dhara
# >>> root["hello"]
# 'world'
```

**Direct file access (no server):**

```bash
dhara db client --file test.dhara
```

All commands accept `--help` for more options.

## Using dhara in a Program

To use dhara, a Python program needs to make a Storage instance and a
Connection instance. For the Storage instance, you have two choices:
FileStorage or ClientStorage. If your program is to be one of several
processes accessing a shared collection of objects, then you want
ClientStorage. If your program has no competition, then choose
FileStorage. There is only one Connection class, and the constructor
takes a storage instance as an argument.

Example using FileStorage to open a Connection to a file:

```py
from dhara.file_storage import FileStorage
from dhara.connection import Connection
connection = Connection(FileStorage("test.dhara"))
```

Example using ClientStorage to open a Connection to a dhara server:

```py
from dhara.client_storage import ClientStorage
from dhara.connection import Connection
connection = Connection(ClientStorage())
```

Note that the ClientStorage constructor supports the `address` keyword
that you can use to specify the address to use. The value must be either
a (host, port) tuple or a string giving a path to use for a unix domain
socket. If you provide the address you should be sure to start the
storage server the same way. The `dhara` command line tool also supports
options to specify the address.

The connection instance has a `get_root()` method that you can use to
obtain the root object.

In your program, you can make changes to the root object attributes,
and call `connection.commit()` or `connection.abort()` to lock in or
revert changes made since the last commit. The root object is
actually an instance of `dhara.persistent_dict.PersistentDict`, which
means that it can be used like a regular dict, except that changes
will be managed by the Connection. There is a similar class,
`dhara.persistent_list.PersistentList` that provides list-like behavior,
except managed by the Connection.

`PersistentList` and `PersistentDict` both inherit from
`dhara.persistent.Persistent`, and this is the key to making your own
classes participate in the dhara persistence system. Just add
Persistent class A's list of bases, and your instances will know how
to manage changes to their attributes through a Connection. To
actually store an instance x of A in the storage, though, you need to
commit a reference to x in some object that is already stored in the
database. The root object is always there, for example, so you can do
something like this:

```py
# Assume mymodule defines A as a subclass of Persistent.
from mymodule import A
x = A()
root = connection.get_root() # connection set as shown above.
root["sample"] = x           # root is dict-like
connection.commit()          # Now x is stored.
```

Subsequent changes to x, or to new A instances put on attributes of X,
and so on, will all be managed by the Connection just as for the root
object. This management of the Persistent instance continues as long
as the instance is in the storage. Sometimes, though, we wish to
remove "garbage" Persistent instances from the storage so that the file
can be smaller. This garbage collection can be done manually by calling
the Connection's pack() method. If you are using a storage server to
share a Storage, you can use the `gcinterval` argument to tell it to
take care of garbage collection automatically.

## Non-Persistent Containers

When you change an attribute of a `Persistent` instance, the fact that
the instance has been changed is noted with the Connection, so that
the Connection knows what instances need to be stored on the next
`commit()`. The same change-tracking occurs automatically when you make
dict-like changes to `PersistentDict` instances or list-like changes to
PersistentList instances. If, however, you make changes to a
non-persistent container, even if it is the value of an attribute of a
`Persistent` instance, the changes are *not* automatically noted with
the Connection. To make sure that your changes do get saved, you must
call the `_p_note_change()` method of the Persistent instance that
refers to the changed non-persistent container. You can see an
example of this by looking at the source code of `PersistentDict` and
`PersistentList`, both of which maintain a non-persistent container on a
`data` attribute, shadow the methods of the underlying container, and
add calls to `self._p_note_change()` in every method that makes changes.

## Storage back-ends

This version of dhara includes a number of back-end storage
implementations that may be used. The default is `FileStorage`, an
append-only journal that includes an on-disk index of object record
offsets. This module has the advantage of fast startup time with
slightly slower read performance (two disk seeks per object load).

Also available is `FileStorage2`, an older version of the `FileStorage`
format. It uses an in-memory index for object offsets and so it has
slower startup time (reading the index into memory takes time,
especially on large databases) but faster read performance (one seek per
object load).

Finally, there is an experimental Sqlite storage module,
`SqliteStorage`. The module uses a SQLite3 database to persist object
data. One disadvantage of this module compared to the others is that
online backups are more difficult (for the other two it is safe to just
copy the file while the server is running). You also lose the ability
to do point-in-time recovery (which the other two storage
implementations provide, assuming you did not yet pack the DB).

## Acknowledgements

dhara is a modern fork and continuation of **Durus**, originally developed
by the MEMS Exchange software development team at the Corporation for National
Research Initiatives (CNRI). We are grateful for the foundational work done
by the original Durus developers.

This modern version (dhara) includes:

- Modern Python 3.13+ type hints
- Enhanced serialization options (msgspec, dill)
- Oneiric configuration and logging integration
- MCP server for modern AI/agent workflows
- Comprehensive security and performance improvements

The name **dhara** (ध्रुव) is Sanskrit for "immovable, eternal, constant,"
or "Pole Star" - complementing the original Latin name **Durus**, meaning
"hard, sturdy, tough, enduring."

## License

dhara is released under an open-source license. See LICENSE.txt for
details.
