#!/usr/bin/env python
"""
from __future__ import annotations
$URL$
$Id$
"""

import os
import sys
from pathlib import Path
from pprint import pprint
from time import sleep
from types import ModuleType
from warnings import warn


class SecurityWarning(UserWarning):
    """Warning raised for security-sensitive operations."""


from dhara.core import Connection
from dhara.logger import direct_output, log, logger
from dhara.server.server import (
    SocketAddress,
    StorageServer,
    wait_for_server,
)
from dhara.storage.client import ClientStorage
from dhara.utils import int8_to_str, str_to_int8, write


def configure_readline(namespace, history_path):
    from contextlib import suppress

    with suppress(ImportError):
        import atexit
        import readline
        import rlcompleter

        readline.set_completer(rlcompleter.Completer(namespace=namespace).complete)
        readline.parse_and_bind("tab: complete")

        def save_history(history_path=history_path):
            readline.write_history_file(history_path)

        atexit.register(save_history)
        if Path(history_path).exists():
            readline.read_history_file(history_path)


def interactive_client(
    file,
    address,
    cache_size,
    readonly,
    repair,
    startup,
    storage_class=None,
    tls_config=None,
):
    if file:
        storage = get_storage(
            file, storage_class=storage_class, readonly=readonly, repair=repair
        )
        description = file
    else:
        socket_address = SocketAddress.new(address)
        wait_for_server(address=socket_address)
        storage = ClientStorage(address=socket_address, tls_config=tls_config)
        description = socket_address
    connection = Connection(storage, cache_size=cache_size)

    # Import adapter registry for new adapter distribution features
    try:
        from dhara.mcp.adapter_tools import AdapterRegistry

        registry = AdapterRegistry(connection)
        has_adapters = True
    except ImportError:
        registry = None
        has_adapters = False

    # Try to use IPython if available, fall back to InteractiveConsole
    try:
        # Intentional: legacy interactive admin console for the Dhara CLI.
        # The interactive REPL is the entire purpose of this branch.
        from IPython.terminal.embed import InteractiveShellEmbed  # noqa: T100
        from IPython.terminal.ipapp import load_default_config  # noqa: F401

        use_ipython = True
    except ImportError:
        from code import InteractiveConsole

        use_ipython = False

    # Build namespace with adapter management if available
    namespace = {
        "connection": connection,
        "root": connection.get_root(),
        "get": connection.get,
        "sys": sys,
        "os": os,
        "int8_to_str": int8_to_str,
        "str_to_int8": str_to_int8,
        "pp": pprint,
    }

    # Add adapter management if available
    if has_adapters and registry:
        namespace.update(
            {
                "registry": registry,
                "adapters": registry,
                # Convenience methods
                "store_adapter": registry.store_adapter,
                "get_adapter": registry.get_adapter,
                "list_adapters": registry.list_adapters,
                "list_versions": registry.list_adapter_versions,
                "validate_adapter": registry.validate_adapter,
                "check_health": registry.check_adapter_health,
                "adapter_count": registry.count,
            }
        )

    # Build help text
    help_text = "    connection -> the Connection\n    root       -> the root instance"
    if has_adapters:
        help_text += "\n\nAdapter Management:\n"
        help_text += "    registry/adapters -> AdapterRegistry instance\n"
        help_text += "    store_adapter()    -> Store an adapter\n"
        help_text += "    get_adapter()      -> Retrieve an adapter\n"
        help_text += "    list_adapters()    -> List all adapters\n"
        help_text += "    list_versions()    -> List adapter versions\n"
        help_text += "    validate_adapter()  -> Validate adapter config\n"
        help_text += "    check_health()     -> Check adapter health\n"
        help_text += "    adapter_count()    -> Count total adapters"

    if use_ipython:
        # Use IPython with enhanced features
        # (Intentional interactive console: see noqa above.)
        ipshell = InteractiveShellEmbed(  # noqa: T100
            banner1=f"🦀 Druva Admin Shell - {description}\n{help_text}\n",
            exit_msg="Exiting Druva Admin Shell",
            user_ns=namespace,
        )
        ipshell()
    else:
        # Fall back to InteractiveConsole
        console_module = ModuleType("__console__")
        sys.modules["__console__"] = console_module
        vars(console_module).update(namespace)
        configure_readline(vars(console_module), os.path.expanduser("~/.dharahistory"))
        console = InteractiveConsole(vars(console_module))
        if startup:
            warn(
                f"Executing startup file: {startup}. "
                "This can execute arbitrary Python code. "
                "Only use trusted files from secure locations.",
                SecurityWarning,
                stacklevel=2,
            )
            console.runsource(f'execfile("{os.path.expanduser(startup)}")')
        console.interact(f"Druva {description}\n{help_text}")


def get_storage_class(file):
    """Return the storage class for an existing file.

    Raises ``ValueError`` if the file is a DFS20/legacy 4.x format. There is
    no in-place format migration; use ``AsyncFileStorage`` (sqlite+aiosqlite)
    for new and migrated databases.
    """
    if not Path(file).exists():
        from dhara.storage.async_file import AsyncFileStorage

        return AsyncFileStorage
    # ``file`` may be a ``str`` or ``pathlib.Path``; the test suite patches
    # ``builtins.open``, so call through the builtin rather than the
    # ``pathlib.Path.open`` method.
    with open(file, "rb") as fp:
        d = fp.read(20)
    if d.startswith(b"DFS20"):
        logger.error("Refused DFS20/legacy 4.x file: %s", file)
        raise ValueError(
            "DFS20/legacy 4.x format no longer supported. There is no automatic "
            "migration path. Use AsyncFileStorage (sqlite+aiosqlite) for new and "
            "migrated databases."
        )
    elif d.startswith(b"SQLite format "):
        from dhara.storage.sqlite import SqliteStorage  # type: ignore[no-redef]

        return SqliteStorage
    elif d.startswith(b"SHELF-1"):
        from dhara.storage.async_file import AsyncFileStorage

        return AsyncFileStorage
    else:
        raise ValueError("unknown storage type for file")


def import_class(name):
    module_name, _, class_name = name.rpartition(".")
    module = __import__(module_name, globals(), locals(), [class_name])
    return getattr(module, class_name)


def get_storage(file, storage_class=None, **kwargs):
    if storage_class is not None:
        storage_class = import_class(storage_class)
    else:
        if file is None:
            from dhara.storage.async_file import AsyncFileStorage

            # passing file=None will create temporary storage
            storage_class = AsyncFileStorage
        else:
            storage_class = get_storage_class(file)
    return storage_class(file, **kwargs)


def start_dhara(logfile, logginglevel, address, storage, gcbytes, tls_config=None):
    opened_logfile = None
    if logfile is None:
        logfile = sys.stderr
    else:
        # ``logfile`` may be a ``str`` (typical) or ``pathlib.Path``; use
        # the builtin ``open`` so either works. The handle is kept open
        # for the lifetime of the server (long-lived; `with` would close
        # before the server uses it) and released in `finally` below.
        opened_logfile = open(logfile, "a+")  # noqa: SIM115
        logfile = opened_logfile
    try:
        direct_output(logfile)
        logger.setLevel(logginglevel)
        socket_address = SocketAddress.new(address)
        if hasattr(storage, "get_filename"):
            log(
                20, "Storage file=%s address=%s", storage.get_filename(), socket_address
            )
        StorageServer(
            storage, address=socket_address, gcbytes=gcbytes, tls_config=tls_config
        ).serve()
    finally:
        if opened_logfile is not None:
            opened_logfile.close()


def stop_dhara(address):
    socket_address = SocketAddress.new(address)
    sock = socket_address.get_connected_socket()
    if sock is None:
        log(20, f"Dhara server {address} doesn't seem to be running")
        return False
    write(sock, "Q")  # graceful exit message
    sock.close()
    # Try to wait until the address is free.
    for attempt in range(20):
        sleep(0.5)
        sock = socket_address.get_connected_socket()
        if sock is None:
            break
        sock.close()
    return True


def usage():
    sys.stdout.write(
        "dhara [ -c | -s | -p ] [ -h ] [<specific options>]\n"
        "    -s   Start or stop a Dhara storage server.\n"
        "    -c   Start a low-level interactive client.\n"
        "    -p   Pack a storage file.\n"
        "    -h   Get help on specific options.\n"
    )


def main():
    """Entry point for ``python -m dhara``.

    Delegates to the Typer-based CLI in ``dhara.cli``. The legacy
    ``-c/-s/-p`` optparse dispatcher has been removed; the same
    functionality is now available under ``dhara db client/start/pack``
    (see ``dhara/cli.py``).
    """
    from dhara.cli import main as cli_main

    cli_main()


if __name__ == "__main__":
    main()
