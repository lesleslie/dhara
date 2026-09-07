# dhara

[![Code style: crackerjack](https://img.shields.io/badge/code%20style-crackerjack-000042)](https://github.com/lesleslie/crackerjack)
[![Runtime: oneiric](https://img.shields.io/badge/runtime-oneiric-6e5494)](https://github.com/lesleslie/oneiric)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![Python: 3.14+](https://img.shields.io/badge/python-3.14%2B-green)](https://www.python.org/downloads/)

**dhara** is a modern continuation of **Durus**, a persistent object system
for applications written in the Python programming language. It could be
called a noSQL database. However, it does provide "ACID" properties
(Atomicity, Consistency, Isolation, Durability).

The implementation of dhara is not multi-threaded but does provide
concurrency via a client/server model. It is optimized for read heavy
work loads and aggressively caches persistent objects in memory.
For many applications, this design enables good performance with minimal
effort from application programmers.

## Bodai Ecosystem Role

Dhara is the **curator** of the [Bodai ecosystem](https://github.com/lesleslie/bodai) — the persistent object storage backend for adapter configs, service lifecycle state, and ecosystem events consumed by Mahavishnu, Akosha, Session-Buddy, Crackerjack, and Oneiric.

Standalone operation is a first-class design goal, not an afterthought —
see [Standalone use](#standalone-use) below. For how Dhara fits into the
broader Bodai control plane, see the [Bodai ecosystem notes](https://github.com/lesleslie/bodai).

## Standalone Use

Dhara is a member of the [Bodai ecosystem](https://github.com/lesleslie/bodai)
and serves there as the curator component — but it is **fully usable on its own**
by any Python application. The Bodai control plane is one set of consumers;
your service is not a special case, and you do not need to pull in any
other Bodai component to use Dhara.

A standalone install has zero ecosystem dependencies:

```bash
uv pip install dhara
dhara db start --file ~/my_app.dhara
```

**Three deployment shapes work without anything Bodai-specific:**

- **In-process.** `AsyncFileStorage` + `AsyncConnection` open the database
  inside your Python process. No server, no socket, no extra runtime.
- **Single-host server.** `dhara db start` brings up the storage server on
  TCP `:8685` by default (configurable via `--port`). Multiple processes on
  the same machine share one store.
- **Distributed server.** The same storage protocol across hosts.
  ACID transactions still serialize through the storage server; clients
  keep a persistent on-disk cache like ZEO clients do.

**Serverless-friendly by design.** With `AsyncConnection` and the asyncio-first
API, Dhara fits cleanly into function-as-a-service contexts:

- **AWS Lambda / Cloud Run / Vercel functions** — use `AsyncFileStorage` for
  cold-fast access, or point all functions at a shared managed PostgreSQL.
- **Cold-start mitigation** — instantiate the storage inside the handler
  rather than at module scope. Per-connection caches reset to disk on every
  commit (the same persistent on-disk cache pattern ZEO pioneered, returned
  for asyncio), so cold starts are cheap.
- **DuckDB analytical queries** — the DuckDB backend reads from the same
  store and answers OLAP-shaped questions in one shot, useful for
  serverless "summarise and return" handlers.
- **In-memory `Storage` backend** — useful for unit tests and ephemeral
  pipelines that don't need to persist anything.

The MCP server (`dhara mcp start`, default port `8683`) is itself optional —
if your application does not need an AI/agent surface, skip it. The
storage server and the MCP server are independent services.

## Why Dhara, Not ZODB/ZEO?

A reasonable first question when you land here is: *how does Dhara compare
to [ZODB](https://zodb.org) and [ZEO](https://zeo.readthedocs.io/en/latest/),
the older and more widely-deployed Python object database with a similar
design point?*

The full feature-by-feature matrix — including a Mermaid diagram of both
stacks, the lineage notes, and a "where each one still wins" section —
lives in [`docs/ZODB_COMPARISON.md`](./docs/ZODB_COMPARISON.md). The short
version for the Bodai use case:

- **The MCP layer.** ZEO has nothing like this. Dhara exposes a [FastMCP]
  server on port `8683` so AI agents (and the rest of the Bodai stack) can
  read and write persistent state without a Python ZODB client in the loop.
  Most of the Bodai integration depends on this surface.
- **The Oneiric adapter registry role.** ZEO is a generic object store.
  Dhara is the canonical Oneiric adapter config store for the entire Bodai
  control plane — config for Mahavishnu adapters, Akosha embeddings, and
  Crackerjack quality gates all live here.
- **Single-threaded by design.** ZODB runs multi-threaded. Dhara explicitly
  does not. That is a deliberate trade — most Bodai-shaped workloads are
  read-heavy with short, infrequent writes that benefit from a simpler
  concurrency story.
- **Modern Python stack.** 3.13+ type hints throughout, `msgspec` for
  serialization alongside pickle, Oneiric layered config, asyncio-first
  `AsyncConnection`. ZODB 5.x is solid and production-proven, but is in
  maintenance rather than active development.

For non-Bodai workloads the comparison doc also covers the longer answer,
including **where ZODB/ZEO still wins** — most notably ZODB's mature
`BTrees` family of large-index containers (Dhara ships `BTree` since
0.10.0 but not the full family), and the `_p_resolveConflict`
application-level merge hook for collaborative-edit patterns, which Dhara
does not replicate.

> **A note on "asyncio-first":** the `AsyncConnection` API fits asyncio
> handlers cleanly, but the *storage server itself* is single-writer —
> writes serialize through the server rather than running in parallel.
> "asyncio-first" here is about the client API shape, not server-side
> parallelism.

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

Dhara ships a Typer-based unified CLI. All subcommands accept `--help`.

### Top-level subcommands

| Command | Purpose |
| --- | --- |
| `dhara version` | Print the installed Dhara version. |
| `dhara doctor` | Run diagnostic checks against the local runtime. |
| `dhara health` | Probe the local runtime health (used by the Bodai radar). |
| `dhara adapters` | List registered Oneiric adapters. |
| `dhara storage` | Display storage information (backend, file, port). |
| `dhara admin` | Launch the Dhara admin shell (IPython). |
| `dhara mcp ...` | MCP server lifecycle (see below). |
| `dhara db ...` | Legacy-compatible database operations (Durus v0.x scripts). |

### MCP server lifecycle (`dhara mcp ...`)

```bash
dhara mcp start               # Start the FastMCP server (default :8683)
dhara mcp stop                # Stop it
dhara mcp status              # Is it running?
dhara mcp health              # Health probe
dhara mcp restart             # stop + start
dhara mcp config              # Show resolved MCP settings
```

### Database operations (`dhara db ...`)

The `db` subcommand tree is the legacy-compatible interface carried over
from the Durus 0.x CLI. Most new code should prefer `dhara start --mode=...`
(see *Modes* below), but `dhara db` keeps existing scripts working.

```bash
dhara db start                # Start Dhara storage server
dhara db client               # Connect to a running server (interactive IPython)
dhara db pack                 # Reclaim storage space
```

Common options for database commands:

- `--file PATH` or `-f PATH` - Database file path
- `--host HOST` or `-h HOST` - Server host (default: 127.0.0.1)
- `--port PORT` or `-p PORT` - Server port (default: `8685` for the storage server, `8683` for the MCP server)
- `--readonly` - Open in read-only mode

### Modes

Dhara's startup modes are the recommended way to bring the storage server
up. They pre-wire host/port and the default backend so you do not have
to memorize the right flags for each scenario.

```bash
dhara start --mode=lite         # Zero-config, local SQLite, port 8683
dhara start --mode=standard     # Full feature set, configurable storage, port 8685
```

The two modes are implemented in `dhara/modes/lite.py` and
`dhara/modes/standard.py`. See `dhara/modes/__init__.py` for the mode
detection and resolution rules.

## Validation

The preferred local validation path is `crackerjack` (the CLI, not
`python -m crackerjack`):

```bash
crackerjack run                # Full quality gate (format + lint + type + tests)
crackerjack run -p minor       # Bump + commit + tag + push + publish (when hooks pass)
crackerjack run -p patch       # Patch-level release
crackerjack doctor             # Diagnostic checks (pre-flight)
crackerjack health             # Health probe
```

For a single test file or a specific failure, drop down to `pytest` directly:

```bash
pytest tests/unit/test_storage_sqlite.py
pytest -k "test_cache_shrink" -x
```

When `crackerjack run` reports issues, fix them via Crackerjack's
AI-assisted flow rather than re-running the gates by hand.

## Configuration Surfaces

Dhara currently exposes two configuration layers:

- `dhara.core.config.DharaSettings` is the canonical runtime settings model for the CLI and MCP server
- `dhara.config` remains available for lightweight dataclass helpers and compatibility with older code

For service startup, operator configuration, and environment-variable overrides, use `DharaSettings`.

## Deprecation Policy

Dhara is in an active compatibility-reduction window.

- Deprecated compatibility imports remain available in `0.8.x`
- They are planned for stronger enforcement in `0.9.x`
- Convenience compatibility shims are candidates for removal in `1.0.0`

The current policy and migration targets are documented in
`docs/LEGACY_COMPATIBILITY_AND_REMOVAL_PLAN.md`.

## Quick Demo

**Start a Dhara server (recommended):**

```bash
dhara start --mode=lite
```

This starts the storage server in *lite* mode — a local SQLite-backed
file, listening on `127.0.0.1:8683`. Use `--mode=standard` for the
production-shaped configuration (default port `8685`).

If you have an existing Durus-style script that still calls
`dhara db start`, that path is preserved under the `dhara db ...`
subcommand tree for compatibility — see *CLI Commands* above.

**Connect as a client:**

```bash
dhara admin
```

This opens an interactive IPython shell connected to the running server.
You have access to a dictionary-like persistent object, `root`. If you
make changes to items of `root` and run `connection.commit()`, the
changes are written to the file. If you make changes and then run
`connection.abort()`, the attributes revert back to the values they
had at the last commit.

**Multiple clients:** open a second terminal and run `dhara admin`
again. Committed changes to `root` in one client are visible in other
clients after the next `connection.abort()` or `connection.commit()`.

**Stop the server:** Press *Control-C* in the server terminal.

**Persistence example (using the legacy `db` commands):**

```bash
# Start server with a persistent file
dhara db start --file test.dhara

# Connect, make changes, commit
dhara db client --file test.dhara
# In the shell:
# >>> root["hello"] = "world"
# >>> connection.commit()

# Stop and restart - data persists
dhara db start --file test.dhara
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
AsyncFileStorage or ClientStorage. If your program is to be one of several
processes accessing a shared collection of objects, then you want
ClientStorage. If your program has no competition, then choose
AsyncFileStorage. There is only one Connection class, and the constructor
takes a storage instance as an argument.

Example using AsyncFileStorage to open an async Connection to a file:

```py
import asyncio
from dhara.core.connection import AsyncConnection
from dhara.storage.async_file import AsyncFileStorage

async def main() -> None:
    storage = AsyncFileStorage("test.dhara")
    await storage.init()
    connection = await AsyncConnection.new(storage)

asyncio.run(main())
```

Example using ClientStorage to open a Connection to a dhara server:

```py
from dhara.core.connection import Connection
from dhara.storage.client import ClientStorage

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
actually an instance of `dhara.collections.dict.PersistentDict`, which
means that it can be used like a regular dict, except that changes
will be managed by the Connection. There is a similar class,
`dhara.collections.list.PersistentList` that provides list-like behavior,
except managed by the Connection.

`PersistentList` and `PersistentDict` both inherit from
`dhara.core.persistent.Persistent`, and this is the key to making your own
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

Dhara ships several storage backends, all implemented under
`dhara/storage/`. Pick the one that matches your durability and
concurrency story.

| Backend | Module | Use it for |
| --- | --- | --- |
| `AsyncFileStorage` | `dhara/storage/async_file.py` | Local single-process persistence. **Default.** A thin alias for `AsyncSqliteStorage` that maps a filesystem path to a `sqlite+aiosqlite://` URL — drop-in for the legacy `FileStorage` path-style API. |
| `AsyncSqliteStorage` | `dhara/storage/sqlite.py` | The canonical async SQLite backend. Use this when you want the URL form directly (`sqlite+aiosqlite:///path/to.db`). |
| `SqliteStorage` | `dhara/storage/sqlite.py` | Sync SQLite backend (Durus-compatible). Useful for batch jobs and existing scripts that need the blocking API. Online backups and point-in-time recovery are *not* available with this backend. |
| `PostgresStorage` | `dhara/storage/postgres.py` | Multi-process, multi-host persistence. Drop-in for managed PostgreSQL or self-hosted clusters. Install the `cloud` dep group to enable. |
| `DuckDBStorage` | `dhara/storage/duckdb_adapter.py` | OLAP-shaped analytical queries over the same persistent store. Useful for serverless "summarise and return" handlers. Install the `duckdb` dep group to enable. |
| `MemoryStorage` | `dhara/storage/memory.py` | Ephemeral, in-process. Tests and short-lived pipelines. |
| `ClientStorage` | `dhara/storage/client.py` | Connect to a remote Dhara storage server over TCP or Unix domain socket. The standard choice when several processes share a store. |

> **Removed:** `FileStorage` (the pre-async Durus path-style class) and
> `SHELF-1` are gone. New and migrated code should use
> `AsyncFileStorage` (path-style) or `AsyncSqliteStorage` (URL-style)
> directly. `AsyncFileStorage("test.dhara")` and
> `AsyncSqliteStorage("sqlite+aiosqlite:///test.dhara")` point at the
> same database.

## Acknowledgements

dhara is a modern fork and continuation of **Durus**, originally developed
by the MEMS Exchange software development team at the Corporation for National
Research Initiatives (CNRI). We are grateful for the foundational work done
by the original Durus developers.

This modern version (dhara) includes:

- Modern Python 3.13+ type hints
- Enhanced serialization options (msgspec)
- Oneiric configuration and logging integration
- MCP server for modern AI/agent workflows
- Comprehensive security and performance improvements

The name **dhara** (ध्रुव) is Sanskrit for "immovable, eternal, constant,"
or "Pole Star" - complementing the original Latin name **Durus**, meaning
"hard, sturdy, tough, enduring."

## License

BSD 3-Clause License — see `LICENSE` in the project root for details.

[fastmcp]: https://github.com/modelcontextprotocol/python-sdk
