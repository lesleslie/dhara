dhruva
=====

**dhruva** is a modern continuation of **Durus**, a persistent object system
for applications written in the Python programming language.  It could be
called a noSQL database.  However, it does provide "ACID" properties
(Atomicity, Consistency, Isolation, Durability).

The implementation of dhruva is not multi-threaded but does provide
concurrency via a client/server model.  It is optimized for read heavy
work loads and aggressively caches persistent objects in memory.
For many applications, this design enables good performance with minimal
effort from application programmers.

Origin
------

dhruva was originally written by the MEMS Exchange software development
team at the Corporation for National Research Initiatives (CNRI).  dhruva
was designed to be the storage component for the Python-powered web sites
operated by the MEMS Exchange.  See `doc/README_CNRI.txt` for more
details.

Overview
--------

dhruva offers an easy way to use and maintain a consistent collection
of object instances used by one or more processes.  Access and change
of a persistent instances is managed through a cached Connection
instance which includes `commit()` and `abort()` methods so that changes
are transactional. 

Quick Demo
----------

Run `dhruva -s` in one window.  This starts a dhruva storage server using
a temporary file and listening for clients on localhost port 2972.  Run
`dhruva -c` in another window.  This connects to the storage server on
the port 2972 on the localhost.  When you start, you have access to only
one dictionary-like persistent object, `root`. If you make changes to
items of `root` and run `connection.commit()`, the changes are written
to the (in this case, temporary) file.  If you make changes to
attributes of `root`, and then run `connection.abort()`, the attributes
revert back to the values they had at the last commit.

Run another `dhruva -c` in a third window, and you can see how
committed changes to `root` in the first client are available in the
second client when it starts.  Subsequent changes committed in any
client are visible in any other client that synchronizes by calling
either `connection.abort()` or `connection.commit()`.

You can stop the server by *Control-C* or by running `dhruva -s --stop`.
You can stop the clients by *Control-D* or by your usual method of
terminating a Python interaction.

This demonstrates simple transactional behavior, but not persistence,
since the temporary file is removed as soon as the dhruva server is
stopped.

To see how persistence works, follow the same procedure again, except
add `--file test.dhruva` to the command that starts the server.  Make
changes to attributes of root, run `connection.commit()`, and
`dhruva -s --stop`, and the changes to root will be stored in test.dhruva,
so that you'll see the changes again if you restart again with the
`--file test.dhruva` option.

Finally, note that you can run `dhruva -c --file test.dhruva` (after
stopping the dhruva server) to use the file storage directly and
exclusively.  Everything works the same way as before, except that no
server is involved.

Both the `dhruva -s` and `dhruva -c` commands accept `--help` command
line options that explain more about their usage.


Using dhruva in a Program
------------------------

To use dhruva, a Python program needs to make a Storage instance and a
Connection instance.  For the Storage instance, you have two choices:
FileStorage or ClientStorage.  If your program is to be one of several
processes accessing a shared collection of objects, then you want
ClientStorage.  If your program has no competition, then choose
FileStorage.  There is only one Connection class, and the constructor
takes a storage instance as an argument.

Example using FileStorage to open a Connection to a file:

```py
from dhruva.file_storage import FileStorage
from dhruva.connection import Connection
connection = Connection(FileStorage("test.dhruva"))
```

Example using ClientStorage to open a Connection to a dhruva server:

```py
from dhruva.client_storage import ClientStorage
from dhruva.connection import Connection
connection = Connection(ClientStorage())
```

Note that the ClientStorage constructor supports the `address` keyword
that you can use to specify the address to use.  The value must be either
a (host, port) tuple or a string giving a path to use for a unix domain
socket. If you provide the address you should be sure to start the
storage server the same way.  The `dhruva` command line tool also supports 
options to specify the address.

The connection instance has a `get_root()` method that you can use to
obtain the root object.

In your program, you can make changes to the root object attributes,
and call `connection.commit()` or `connection.abort()` to lock in or
revert changes made since the last commit.  The root object is
actually an instance of `dhruva.persistent_dict.PersistentDict`, which
means that it can be used like a regular dict, except that changes
will be managed by the Connection.  There is a similar class,
`dhruva.persistent_list.PersistentList` that provides list-like behavior,
except managed by the Connection.

`PersistentList` and `PersistentDict` both inherit from
`dhruva.persistent.Persistent`, and this is the key to making your own
classes participate in the dhruva persistence system.  Just add
Persistent class A's list of bases, and your instances will know how
to manage changes to their attributes through a Connection.  To
actually store an instance x of A in the storage, though, you need to
commit a reference to x in some object that is already stored in the
database.  The root object is always there, for example, so you can do
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
object.  This management of the Persistent instance continues as long
as the instance is in the storage.  Sometimes, though, we wish to
remove "garbage" Persistent instances from the storage so that the file 
can be smaller.  This garbage collection can be done manually by calling
the Connection's pack() method.  If you are using a storage server to
share a Storage, you can use the `gcinterval` argument to tell it to
take care of garbage collection automatically.

Non-Persistent Containers
-------------------------

When you change an attribute of a `Persistent` instance, the fact that
the instance has been changed is noted with the Connection, so that
the Connection knows what instances need to be stored on the next
`commit()`.  The same change-tracking occurs automatically when you make
dict-like changes to `PersistentDict` instances or list-like changes to
PersistentList instances.  If, however, you make changes to a
non-persistent container, even if it is the value of an attribute of a
`Persistent` instance, the changes are *not* automatically noted with
the Connection.  To make sure that your changes do get saved, you must
call the `_p_note_change()` method of the Persistent instance that
refers to the changed non-persistent container.  You can see an
example of this by looking at the source code of `PersistentDict` and
`PersistentList`, both of which maintain a non-persistent container on a
`data` attribute, shadow the methods of the underlying container, and
add calls to `self._p_note_change()` in every method that makes changes.

Storage back-ends
----------------

This version of dhruva includes a number of back-end storage
implementations that may be used.  The default is `FileStorage`, an
append-only journal that includes an on-disk index of object record
offsets.  This module has the advantage of fast startup time with
slightly slower read performance (two disk seeks per object load).

Also available is `FileStorage2`, an older version of the `FileStorage`
format.  It uses an in-memory index for object offsets and so it has
slower startup time (reading the index into memory takes time,
especially on large databases) but faster read performance (one seek per
object load).

Finally, there is an experimental Sqlite storage module,
`SqliteStorage`.  The module uses a SQLite3 database to persist object
data.  One disadvantage of this module compared to the others is that
online backups are more difficult (for the other two it is safe to just
copy the file while the server is running).  You also lose the ability
to do point-in-time recovery (which the other two storage
implementations provide, assuming you did not yet pack the DB).

Acknowledgements
----------------

dhruva is a modern fork and continuation of **Durus**, originally developed
by the MEMS Exchange software development team at the Corporation for National
Research Initiatives (CNRI). We are grateful for the foundational work done
by the original Durus developers.

This modern version (dhruva) includes:
- Modern Python 3.13+ type hints
- Enhanced serialization options (msgspec, dill)
- Oneiric configuration and logging integration
- MCP server for modern AI/agent workflows
- Comprehensive security and performance improvements

The name **dhruva** (ध्रुव) is Sanskrit for "immovable, eternal, constant,"
or "Pole Star" - complementing the original Latin name **Durus**, meaning
"hard, sturdy, tough, enduring."

License
-------

dhruva is released under an open-source license.  See LICENSE.txt for
details.
