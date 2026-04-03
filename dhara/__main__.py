#!/usr/bin/env python
"""
$URL$
$Id$
"""

import os
import socket
import sys
from optparse import OptionParser
from pprint import pprint
from time import sleep
from types import ModuleType
from warnings import warn


class SecurityWarning(UserWarning):
    """Warning raised for security-sensitive operations."""

    pass


from dhara.core import Connection
from dhara.logger import direct_output, log, logger
from dhara.security.tls import (
    TLSConfig,
    generate_self_signed_cert,
)
from dhara.server.server import (
    DEFAULT_GCBYTES,
    DEFAULT_HOST,
    DEFAULT_PORT,
    SocketAddress,
    StorageServer,
    wait_for_server,
)
from dhara.storage.client import ClientStorage
from dhara.utils import int8_to_str, str_to_int8, write


def configure_readline(namespace, history_path):
    try:
        import atexit
        import readline
        import rlcompleter

        readline.set_completer(rlcompleter.Completer(namespace=namespace).complete)
        readline.parse_and_bind("tab: complete")

        def save_history(history_path=history_path):
            readline.write_history_file(history_path)

        atexit.register(save_history)
        if os.path.exists(history_path):
            readline.read_history_file(history_path)
    except ImportError:
        pass


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
        from IPython.terminal.embed import InteractiveShellEmbed
        from IPython.terminal.ipapp import load_default_config

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
        ipshell = InteractiveShellEmbed(
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
        configure_readline(vars(console_module), os.path.expanduser("~/.durushistory"))
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


def client_main():
    from optparse import OptionParser

    parser = OptionParser()
    parser.set_description("Opens a client connection to a Durus server.")
    parser.add_option(
        "--file",
        dest="file",
        default=None,
        help="If this is not given, the storage is through a Durus server.",
    )
    parser.add_option(
        "--port",
        dest="port",
        default=DEFAULT_PORT,
        type="int",
        help=f"Port the server is on. (default={DEFAULT_PORT})",
    )
    parser.add_option(
        "--host",
        dest="host",
        default=DEFAULT_HOST,
        help=f"Host of the server. (default={DEFAULT_HOST})",
    )
    parser.add_option(
        "--address",
        dest="address",
        default=None,
        help=(
            "Address of the server.\n"
            "If given, this is the path to a Unix domain socket for "
            "the server."
        ),
    )
    parser.add_option(
        "--storage-class",
        dest="storage",
        default=None,
        help="Storage class (e.g. durus.file_storage.FileStorage).",
    )
    parser.add_option(
        "--cache_size",
        dest="cache_size",
        default=10000,
        type="int",
        help="Size of client cache (default=10000)",
    )
    parser.add_option(
        "--repair",
        dest="repair",
        action="store_true",
        help=(
            "Repair the filestorage by truncating to remove anything "
            "that is malformed.  Without this option, errors "
            "will cause the program to report and terminate without "
            "attempting any repair."
        ),
    )
    parser.add_option(
        "--readonly",
        dest="readonly",
        action="store_true",
        help="Open the file in read-only mode.",
    )
    parser.add_option(
        "--startup",
        dest="startup",
        default=os.environ.get("DURUSSTARTUP", ""),
        help=(
            "⚠️ SECURITY WARNING: Full path to a python startup file to execute on startup.\n"
            "This executes arbitrary Python code which is a security risk.\n"
            "Only use with trusted files from secure locations.\n"
            "(default=DURUSSTARTUP from environment, if set)"
        ),
    )

    # TLS/SSL client options
    parser.add_option(
        "--tls-cafile",
        dest="tls_cafile",
        default=None,
        help=(
            "Path to CA certificate file for server verification.\n"
            "Required for TLS connections unless system certificates are used."
        ),
    )
    parser.add_option(
        "--tls-capath",
        dest="tls_capath",
        default=None,
        help=(
            "Path to CA certificate directory for server verification.\n"
            "Alternative to --tls-cafile."
        ),
    )
    parser.add_option(
        "--tls-certfile",
        dest="tls_certfile",
        default=None,
        help=(
            "Path to client certificate file for mutual TLS authentication.\n"
            "Optional, enables client authentication."
        ),
    )
    parser.add_option(
        "--tls-keyfile",
        dest="tls_keyfile",
        default=None,
        help=(
            "Path to client private key file for mutual TLS authentication.\n"
            "Required if --tls-certfile is specified."
        ),
    )
    parser.add_option(
        "--tls-no-verify",
        dest="tls_no_verify",
        action="store_true",
        help=(
            "Disable TLS certificate verification.\n"
            "⚠️ SECURITY WARNING: This is insecure and should only be used for testing."
        ),
    )
    (options, args) = parser.parse_args()

    # Create TLS config if TLS options are provided
    tls_config = None
    if (
        options.tls_cafile
        or options.tls_capath
        or options.tls_certfile
        or options.tls_keyfile
    ):
        try:
            import ssl

            verify_mode = ssl.CERT_NONE if options.tls_no_verify else ssl.CERT_REQUIRED
            tls_config = TLSConfig(
                cafile=options.tls_cafile,
                capath=options.tls_capath,
                client_certfile=options.tls_certfile,
                client_keyfile=options.tls_keyfile,
                verify_mode=verify_mode,
            )
        except (ValueError, FileNotFoundError) as e:
            log(20, "TLS configuration error: %s", e)
            return
    if options.address is None:
        address = (options.host, options.port)
    else:
        address = options.address
    interactive_client(
        options.file,
        address,
        options.cache_size,
        options.readonly,
        options.repair,
        options.startup,
        options.storage,
        tls_config,
    )


def get_storage_class(file):
    """Return the corresponding storage class based on an existing file."""
    if not os.path.exists(file):
        from dhara.file_storage import FileStorage

        return FileStorage
    fp = open(file, "rb")
    d = fp.read(20)
    fp.close()
    if d.startswith(b"DFS20"):
        from dhara.file_storage2 import FileStorage2

        return FileStorage2
    elif d.startswith(b"SQLite format "):
        from dhara.sqlite_storage import SqliteStorage

        return SqliteStorage
    elif d.startswith(b"SHELF-1"):
        from dhara.file_storage import FileStorage

        return FileStorage
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
            from dhara.file_storage import FileStorage

            # passing file=None will create temporary storage
            storage_class = FileStorage
        else:
            storage_class = get_storage_class(file)
    return storage_class(file, **kwargs)


def start_durus(logfile, logginglevel, address, storage, gcbytes, tls_config=None):
    if logfile is None:
        logfile = sys.stderr
    else:
        logfile = open(logfile, "a+")
    direct_output(logfile)
    logger.setLevel(logginglevel)
    socket_address = SocketAddress.new(address)
    if hasattr(storage, "get_filename"):
        log(20, "Storage file=%s address=%s", storage.get_filename(), socket_address)
    StorageServer(
        storage, address=socket_address, gcbytes=gcbytes, tls_config=tls_config
    ).serve()


def stop_durus(address):
    socket_address = SocketAddress.new(address)
    sock = socket_address.get_connected_socket()
    if sock is None:
        log(20, f"Durus server {str(address)} doesn't seem to be running.")
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


def run_durus_main():
    parser = OptionParser()
    parser.set_description("Run a Durus Server")
    parser.add_option(
        "--port",
        dest="port",
        default=DEFAULT_PORT,
        type="int",
        help=f"Port to listen on. (default={DEFAULT_PORT})",
    )
    parser.add_option(
        "--file",
        dest="file",
        default=None,
        help=("If not given, the storage is in a new temporary file."),
    )
    parser.add_option(
        "--host",
        dest="host",
        default=DEFAULT_HOST,
        help=f"Host to listen on. (default={DEFAULT_HOST})",
    )
    parser.add_option(
        "--storage-class",
        dest="storage",
        default=None,
        help="Storage class (e.g. durus.file_storage.FileStorage).",
    )
    parser.add_option(
        "--gcbytes",
        dest="gcbytes",
        default=DEFAULT_GCBYTES,
        type="int",
        help=(
            f"Trigger garbage collection after this many commits. (default={DEFAULT_GCBYTES})"
        ),
    )
    if hasattr(socket, "AF_UNIX"):
        parser.add_option(
            "--address",
            dest="address",
            default=None,
            help=(
                "Address of the server.\n"
                "If given, this is the path to a Unix domain socket for "
                "the server."
            ),
        )
        parser.add_option(
            "--owner",
            dest="owner",
            default=None,
            help="Owner of the Unix domain socket (the --address value).",
        )
        parser.add_option(
            "--group",
            dest="group",
            default=None,
            help="group of the Unix domain socket (the --address value).",
        )
        parser.add_option(
            "--umask",
            dest="umask",
            default=None,
            type="int",
            help="umask for the Unix domain socket (the --address value).",
        )
    logginglevel = logger.getEffectiveLevel()
    parser.add_option(
        "--logginglevel",
        dest="logginglevel",
        default=logginglevel,
        type="int",
        help=(
            f"Logging level. Lower positive numbers log more. (default={logginglevel})"
        ),
    )
    parser.add_option(
        "--logfile", dest="logfile", default=None, help=("Log file. (default=stderr)")
    )
    parser.add_option(
        "--repair",
        dest="repair",
        action="store_true",
        help=(
            "Repair the filestorage by truncating to remove anything "
            "that is malformed.  Without this option, errors "
            "will cause the program to report and terminate without "
            "attempting any repair."
        ),
    )
    parser.add_option(
        "--readonly",
        dest="readonly",
        action="store_true",
        help="Open the file in read-only mode.",
    )
    parser.add_option(
        "--stop",
        dest="stop",
        action="store_true",
        help="Instead of starting the server, try to stop a running one.",
    )

    # TLS/SSL options
    parser.add_option(
        "--tls-certfile",
        dest="tls_certfile",
        default=None,
        help=(
            "Path to server certificate file for TLS/SSL (PEM format).\n"
            "Required for TLS. Use --generate-tls-cert to create a self-signed cert for testing."
        ),
    )
    parser.add_option(
        "--tls-keyfile",
        dest="tls_keyfile",
        default=None,
        help=(
            "Path to server private key file for TLS/SSL (PEM format).\n"
            "Required for TLS. Use --generate-tls-cert to create a self-signed key for testing."
        ),
    )
    parser.add_option(
        "--tls-cafile",
        dest="tls_cafile",
        default=None,
        help=(
            "Path to CA certificate file for client verification.\n"
            "Enables mutual TLS if specified."
        ),
    )
    parser.add_option(
        "--tls-capath",
        dest="tls_capath",
        default=None,
        help=(
            "Path to CA certificate directory for client verification.\n"
            "Enables mutual TLS if specified."
        ),
    )
    parser.add_option(
        "--generate-tls-cert",
        dest="generate_tls_cert",
        default=None,
        metavar="HOSTNAME",
        help=(
            "Generate a self-signed certificate for testing/development.\n"
            "Creates server.crt and server.key in the current directory.\n"
            "WARNING: Self-signed certificates should ONLY be used for development/testing.\n"
            "Argument: hostname for certificate (default: localhost)"
        ),
    )
    (options, args) = parser.parse_args()

    # Handle TLS certificate generation
    if options.generate_tls_cert:
        hostname = options.generate_tls_cert
        certfile = "server.crt"
        keyfile = "server.key"
        log(20, "Generating self-signed certificate for %s...", hostname)
        log(20, "Certificate: %s", certfile)
        log(20, "Private key: %s", keyfile)
        log(20, "WARNING: Self-signed certificates are for testing only!")
        try:
            generate_self_signed_cert(certfile, keyfile, hostname=hostname)
            log(20, "Certificate generated successfully.")
            log(
                20,
                "Use: dhara -s --tls-certfile %s --tls-keyfile %s",
                certfile,
                keyfile,
            )
            return
        except ImportError as e:
            log(20, "Error: %s", e)
            log(20, "Install cryptography module: pip install cryptography")
            return
        except Exception as e:
            log(20, "Failed to generate certificate: %s", e)
            return

    # Create TLS config if certificates are provided
    tls_config = None
    if options.tls_certfile or options.tls_keyfile:
        try:
            tls_config = TLSConfig(
                certfile=options.tls_certfile,
                keyfile=options.tls_keyfile,
                cafile=options.tls_cafile,
                capath=options.tls_capath,
            )
            log(20, "TLS/SSL enabled on server")
        except (ValueError, FileNotFoundError) as e:
            log(20, "TLS configuration error: %s", e)
            return
    if getattr(options, "address", None) is None:
        address = SocketAddress.new((options.host, options.port))
    elif options.address.startswith("@"):
        # abstract unix socket
        address = SocketAddress.new(address=options.address)
    else:
        # unix socket
        address = SocketAddress.new(
            address=options.address,
            owner=options.owner,
            group=options.group,
            umask=options.umask,
        )
    if not options.stop:
        storage = get_storage(
            options.file,
            storage_class=options.storage,
            repair=options.repair,
            readonly=options.readonly,
        )
        start_durus(
            options.logfile,
            options.logginglevel,
            address,
            storage,
            options.gcbytes,
            tls_config,
        )
    else:
        stop_durus(address)


def pack_storage_main():
    parser = OptionParser()
    parser.set_description("Packs a Durus storage.")
    parser.add_option(
        "--file",
        dest="file",
        default=None,
        help="If this is not given, the storage is through a Durus server.",
    )
    parser.add_option(
        "--port",
        dest="port",
        default=DEFAULT_PORT,
        type="int",
        help=f"Port the server is on. (default={DEFAULT_PORT})",
    )
    parser.add_option(
        "--host",
        dest="host",
        default=DEFAULT_HOST,
        help=f"Host of the server. (default={DEFAULT_HOST})",
    )
    # TLS client options for pack
    parser.add_option(
        "--tls-cafile",
        dest="tls_cafile",
        default=None,
        help="Path to CA certificate file for server verification.",
    )
    parser.add_option(
        "--tls-certfile",
        dest="tls_certfile",
        default=None,
        help="Path to client certificate for mutual TLS.",
    )
    parser.add_option(
        "--tls-keyfile",
        dest="tls_keyfile",
        default=None,
        help="Path to client private key for mutual TLS.",
    )
    (options, args) = parser.parse_args()

    # Create TLS config if TLS options provided
    tls_config = None
    if options.tls_cafile or options.tls_certfile:
        try:
            tls_config = TLSConfig(
                cafile=options.tls_cafile,
                client_certfile=options.tls_certfile,
                client_keyfile=options.tls_keyfile,
            )
        except (ValueError, FileNotFoundError) as e:
            log(20, "TLS configuration error: %s", e)
            return

    if options.file is None:
        wait_for_server(options.host, options.port)
        storage = ClientStorage(
            host=options.host, port=options.port, tls_config=tls_config
        )
    else:
        storage = get_storage(options.file)
    connection = Connection(storage)
    connection.pack()


def usage():
    sys.stdout.write(
        "durus [ -c | -s | -p ] [ -h ] [<specific options>]\n"
        "    -s   Start or stop a Durus storage server.\n"
        "    -c   Start a low-level interactive client.\n"
        "    -p   Pack a storage file.\n"
        "    -h   Get help on specific options.\n"
    )


def main():
    if len(sys.argv) == 1:
        usage()
    else:
        arg = sys.argv[1]
        sys.argv[1:] = sys.argv[2:]
        if arg == "-c":
            client_main()
        elif arg == "-s":
            run_durus_main()
        elif arg == "-p":
            pack_storage_main()
        else:
            usage()


if __name__ == "__main__":
    main()
