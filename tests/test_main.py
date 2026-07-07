"""
Tests for dhara.__main__ module.

Covers the helper functions used by CLI entry points:
- get_storage_class() - detects storage class from magic bytes
- import_class() - dynamically imports a class by dotted name
- get_storage() - gets a storage instance
- usage() - prints usage information
- start_dhara() / stop_dhara() - server lifecycle helpers
- configure_readline() - readline setup helper
- SecurityWarning - custom warning class
"""

import os
import sys
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# SecurityWarning
# ---------------------------------------------------------------------------


class TestSecurityWarning:
    """Tests for the SecurityWarning class."""

    def test_is_subclass_of_user_warning(self):
        from dhara.__main__ import SecurityWarning

        assert issubclass(SecurityWarning, UserWarning)

    def test_can_be_raised_and_caught(self):
        from dhara.__main__ import SecurityWarning

        with pytest.raises(SecurityWarning):
            raise SecurityWarning("dangerous operation")

    def test_message_preserved(self):
        from dhara.__main__ import SecurityWarning

        warning = SecurityWarning("test message")
        assert str(warning) == "test message"


# ---------------------------------------------------------------------------
# configure_readline
# ---------------------------------------------------------------------------


class TestConfigureReadline:
    """Tests for the configure_readline helper."""

    def test_import_error_is_silenced(self):
        """When readline is unavailable (e.g. Windows), no error propagates."""
        from dhara.__main__ import configure_readline

        # Simulate readline not being available by removing it from
        # the module cache inside the function body. The function
        # imports readline/rlcompleter inside a try block.
        real_readline = sys.modules.get("readline")
        try:
            # Make readline unimportable by pointing it to None
            sys.modules["readline"] = None  # type: ignore[assignment]
            namespace = {}
            configure_readline(namespace, "/tmp/fake_history")
        finally:
            if real_readline is not None:
                sys.modules["readline"] = real_readline
            else:
                sys.modules.pop("readline", None)

    @patch("dhara.__main__.os.path.exists", return_value=False)
    def test_no_history_file_does_not_crash(self, mock_exists):
        from dhara.__main__ import configure_readline

        with patch.dict(sys.modules, {"readline": MagicMock(), "rlcompleter": MagicMock()}):
            configure_readline({}, "/tmp/nonexistent_history")

    def test_existing_history_file_is_read(self, tmp_path):
        """When the history file exists, ``readline.read_history_file`` is called."""
        from dhara.__main__ import configure_readline

        # Use a real file (not a mock of ``os.path.exists``) so the production
        # code's ``Path(history_path).exists()`` check sees the file.
        history_path = tmp_path / "existing_history"
        history_path.write_text("")

        mock_readline = MagicMock()
        mock_rlcompleter = MagicMock()
        mock_rlcompleter.Completer.return_value.complete = MagicMock()

        with patch.dict(
            sys.modules,
            {"readline": mock_readline, "rlcompleter": mock_rlcompleter},
        ):
            with patch("atexit.register"):
                configure_readline({}, str(history_path))

        mock_readline.read_history_file.assert_called_once_with(str(history_path))

    @patch("dhara.__main__.os.path.exists", return_value=False)
    def test_history_is_written_on_exit(self, mock_exists):
        from dhara.__main__ import configure_readline

        mock_readline = MagicMock()
        mock_rlcompleter = MagicMock()
        mock_rlcompleter.Completer.return_value.complete = MagicMock()
        saved = {}

        def register(fn):
            saved["fn"] = fn

        with patch.dict(
            sys.modules,
            {"readline": mock_readline, "rlcompleter": mock_rlcompleter},
        ):
            with patch("atexit.register", side_effect=register):
                configure_readline({}, "/tmp/history")

        saved["fn"]()
        mock_readline.write_history_file.assert_called_once_with("/tmp/history")


# ---------------------------------------------------------------------------
# get_storage_class
# ---------------------------------------------------------------------------


class TestGetStorageClass:
    """Tests for get_storage_class which detects storage type from magic bytes."""

    def test_nonexistent_file_returns_file_storage(self):
        """A file that does not exist on disk returns FileStorage."""
        from dhara.__main__ import get_storage_class

        with patch("dhara.__main__.os.path.exists", return_value=False):
            result = get_storage_class("/nonexistent/path.dhara")

        from dhara.storage.file import FileStorage

        assert result is FileStorage

    def test_dfs20_header_raises_value_error(self):
        """A file starting with b'DFS20' raises ValueError (legacy format refused)."""
        from dhara.__main__ import get_storage_class

        mock_file = BytesIO(b"DFS20_some_data_here_extra")
        with patch("dhara.__main__.os.path.exists", return_value=True):
            with patch("builtins.open", return_value=mock_file):
                with pytest.raises(ValueError, match="DFS20"):
                    get_storage_class("test.dhara")

    def test_sqlite_header_returns_sqlite_storage(self):
        """A file starting with b'SQLite format ' returns SqliteStorage.

        Note: get_storage_class imports from dhara.sqlite_storage which is
        a legacy module path. We inject a mock module so the import succeeds
        and verify the class is returned.
        """
        from dhara.__main__ import get_storage_class

        mock_sqlite_storage = MagicMock()
        mock_sqlite_module = MagicMock()
        mock_sqlite_module.SqliteStorage = mock_sqlite_storage

        mock_file = BytesIO(b"SQLite format 3\x00extra")
        with patch("dhara.__main__.os.path.exists", return_value=True):
            with patch("builtins.open", return_value=mock_file):
                # ``dhara.__main__.get_storage_class`` imports from the
                # canonical path ``dhara.storage.sqlite`` (the legacy
                # ``dhara.sqlite_storage`` module was removed in the
                # 0.12.0 cross-checker cleanup).
                with patch.dict(
                    sys.modules, {"dhara.storage.sqlite": mock_sqlite_module}
                ):
                    result = get_storage_class("test.sqlite")

        assert result is mock_sqlite_storage

    def test_shelf_header_returns_file_storage(self):
        """A file starting with b'SHELF-1' returns FileStorage."""
        from dhara.__main__ import get_storage_class

        mock_file = BytesIO(b"SHELF-1_some_data_padding_xx")
        with patch("dhara.__main__.os.path.exists", return_value=True):
            with patch("builtins.open", return_value=mock_file):
                result = get_storage_class("test.shelf")

        from dhara.storage.file import FileStorage

        assert result is FileStorage

    def test_unknown_header_raises_value_error(self):
        """An unrecognized magic header raises ValueError."""
        from dhara.__main__ import get_storage_class

        mock_file = BytesIO(b"UNKNOWN_FORMAT_DATA!!")
        with patch("dhara.__main__.os.path.exists", return_value=True):
            with patch("builtins.open", return_value=mock_file):
                with pytest.raises(ValueError, match="unknown storage type"):
                    get_storage_class("test.unknown")

    def test_empty_file_raises_value_error(self):
        """An empty file (no magic bytes) raises ValueError."""
        from dhara.__main__ import get_storage_class

        mock_file = BytesIO(b"")
        with patch("dhara.__main__.os.path.exists", return_value=True):
            with patch("builtins.open", return_value=mock_file):
                with pytest.raises(ValueError, match="unknown storage type"):
                    get_storage_class("empty.dhara")

    def test_short_file_raises_value_error(self):
        """A file with fewer than 20 bytes but no valid header raises ValueError."""
        from dhara.__main__ import get_storage_class

        mock_file = BytesIO(b"SHORT")
        with patch("dhara.__main__.os.path.exists", return_value=True):
            with patch("builtins.open", return_value=mock_file):
                with pytest.raises(ValueError, match="unknown storage type"):
                    get_storage_class("short.dhara")

    def test_dfs20_header_raises_with_clear_message(self):
        """DFS20 refusal message clearly states the format is no longer supported."""
        from dhara.__main__ import get_storage_class

        # Exactly 20 bytes of legacy DFS20 content.
        content = b"DFS20" + b"\x00" * 15
        mock_file = BytesIO(content)
        with patch("dhara.__main__.os.path.exists", return_value=True):
            with patch("builtins.open", return_value=mock_file):
                with pytest.raises(ValueError, match="DFS20") as excinfo:
                    get_storage_class("exact.dhara")

        assert "no longer supported" in str(excinfo.value)


# ---------------------------------------------------------------------------
# import_class
# ---------------------------------------------------------------------------


class TestImportClass:
    """Tests for import_class which dynamically imports a class by dotted name."""

    def test_imports_real_module_class(self):
        """Can import a real class from the dhara package."""
        from dhara.__main__ import import_class

        result = import_class("dhara.storage.file.FileStorage")
        from dhara.storage.file import FileStorage

        assert result is FileStorage

    def test_imports_os_path_join(self):
        """Can import a well-known stdlib function."""
        from dhara.__main__ import import_class

        result = import_class("os.path.join")
        import os

        assert result is os.path.join

    def test_imports_module_level_constant(self):
        """Can import a module-level attribute."""
        from dhara.__main__ import import_class

        result = import_class("os.name")
        assert result == os.name

    def test_invalid_class_name_raises_attribute_error(self):
        """A valid module but nonexistent attribute raises AttributeError."""
        from dhara.__main__ import import_class

        with pytest.raises(AttributeError):
            import_class("os.definitely_not_a_real_attribute")

    def test_invalid_module_raises_import_error(self):
        """A completely invalid module name raises ModuleNotFoundError."""
        from dhara.__main__ import import_class

        with pytest.raises(ModuleNotFoundError):
            import_class("nonexistent_module.SomeClass")

    def test_no_dot_raises_attribute_error(self):
        """A string with no dot uses empty module name; raises error."""
        from dhara.__main__ import import_class

        # rpartition on "NoDots" returns ("", "", "NoDots")
        # __import__ with empty string raises
        with pytest.raises((ImportError, ModuleNotFoundError, ValueError)):
            import_class("NoDots")


# ---------------------------------------------------------------------------
# get_storage
# ---------------------------------------------------------------------------


class TestGetStorage:
    """Tests for get_storage which creates storage instances."""

    def test_with_explicit_storage_class_string(self):
        """When storage_class is a dotted string, it is imported and used."""
        from dhara.__main__ import get_storage

        mock_storage_cls = MagicMock(return_value=MagicMock())
        with patch("dhara.__main__.import_class", return_value=mock_storage_cls):
            result = get_storage("test.dhara", storage_class="some.Module")

        mock_storage_cls.assert_called_once_with("test.dhara")
        assert result == mock_storage_cls.return_value

    def test_with_none_file_and_no_storage_class(self):
        """file=None with no storage_class creates temporary FileStorage."""
        from dhara.__main__ import get_storage

        mock_storage = MagicMock()
        with patch("dhara.storage.file.FileStorage", return_value=mock_storage) as MockFS:
            result = get_storage(None, storage_class=None)

        MockFS.assert_called_once_with(None)
        assert result is mock_storage

    def test_with_existing_file_no_storage_class(self):
        """An existing file with no storage_class calls get_storage_class."""
        from dhara.__main__ import get_storage

        mock_storage_cls = MagicMock(return_value=MagicMock())
        with patch("dhara.__main__.get_storage_class", return_value=mock_storage_cls):
            result = get_storage("existing.dhara", storage_class=None)

        mock_storage_cls.assert_called_once_with("existing.dhara")
        assert result == mock_storage_cls.return_value

    def test_passes_kwargs_to_storage_class(self):
        """Extra keyword arguments are forwarded to the storage constructor."""
        from dhara.__main__ import get_storage

        mock_storage_cls = MagicMock(return_value=MagicMock())
        with patch("dhara.__main__.import_class", return_value=mock_storage_cls):
            _ = get_storage(
                "test.dhara",
                storage_class="some.Module",
                readonly=True,
                repair=False,
            )

        mock_storage_cls.assert_called_once_with(
            "test.dhara", readonly=True, repair=False
        )

    def test_storage_class_none_with_file_delegates(self):
        """storage_class=None and a file path delegates to get_storage_class."""
        from dhara.__main__ import get_storage

        mock_cls = MagicMock(return_value="storage_instance")
        with patch("dhara.__main__.get_storage_class", return_value=mock_cls):
            result = get_storage("mydata.dhara")

        assert result == "storage_instance"
        mock_cls.assert_called_once_with("mydata.dhara")


# ---------------------------------------------------------------------------
# usage
# ---------------------------------------------------------------------------


class TestUsage:
    """Tests for the usage() function."""

    def test_writes_to_stdout(self):
        """usage() writes the help text to stdout."""
        from dhara.__main__ import usage

        with patch("sys.stdout") as mock_stdout:
            usage()

        mock_stdout.write.assert_called_once()
        written = mock_stdout.write.call_args[0][0]
        assert "dhara" in written
        assert "-s" in written
        assert "-c" in written
        assert "-p" in written
        assert "-h" in written

    def test_usage_text_contains_all_modes(self):
        """The usage text documents server, client, and pack modes."""
        from dhara.__main__ import usage

        with patch("sys.stdout") as mock_stdout:
            usage()

        text = mock_stdout.write.call_args[0][0]
        assert "Start" in text or "server" in text.lower()
        assert "interactive client" in text.lower()
        assert "Pack" in text


# ---------------------------------------------------------------------------
# start_dhara
# ---------------------------------------------------------------------------


class TestStartDhara:
    """Tests for start_dhara server lifecycle helper."""

    @patch("dhara.__main__.StorageServer")
    @patch("dhara.__main__.SocketAddress")
    @patch("dhara.__main__.logger")
    @patch("dhara.__main__.direct_output")
    def test_with_default_stderr_logfile(
        self, mock_direct_output, mock_logger, mock_sa, mock_ss
    ):
        """When logfile is None, sys.stderr is used for log output."""
        from dhara.__main__ import start_dhara

        mock_storage = MagicMock()
        mock_address = MagicMock()
        mock_sa.new.return_value = mock_address

        start_dhara(None, 20, ("localhost", 2970), mock_storage, 100000000)

        mock_direct_output.assert_called_once_with(sys.stderr)
        mock_logger.setLevel.assert_called_once_with(20)

    @patch("dhara.__main__.StorageServer")
    @patch("dhara.__main__.SocketAddress")
    @patch("dhara.__main__.logger")
    @patch("dhara.__main__.direct_output")
    @patch("builtins.open")
    def test_with_custom_logfile(
        self, mock_open, mock_direct_output, mock_logger, mock_sa, mock_ss
    ):
        """When a logfile path is given, it is opened for appending."""
        from dhara.__main__ import start_dhara

        mock_storage = MagicMock()
        mock_address = MagicMock()
        mock_sa.new.return_value = mock_address
        mock_open.return_value = MagicMock()

        start_dhara("server.log", 30, ("localhost", 2970), mock_storage, 100000000)

        mock_open.assert_called_once_with("server.log", "a+")
        mock_direct_output.assert_called_once_with(mock_open.return_value)

    @patch("dhara.__main__.StorageServer")
    @patch("dhara.__main__.SocketAddress")
    @patch("dhara.__main__.logger")
    @patch("dhara.__main__.direct_output")
    @patch("dhara.__main__.log")
    def test_logs_storage_filename_when_available(
        self, mock_log, mock_direct_output, mock_logger, mock_sa, mock_ss
    ):
        """When storage has get_filename, it is included in the log message."""
        from dhara.__main__ import start_dhara

        mock_storage = MagicMock()
        mock_storage.get_filename.return_value = "data.dhara"
        mock_address = MagicMock()
        mock_sa.new.return_value = mock_address

        start_dhara(None, 20, ("localhost", 2970), mock_storage, 100000000)

        mock_log.assert_called_once()
        log_args = mock_log.call_args
        assert "data.dhara" in str(log_args)

    @patch("dhara.__main__.StorageServer")
    @patch("dhara.__main__.SocketAddress")
    @patch("dhara.__main__.logger")
    @patch("dhara.__main__.direct_output")
    @patch("dhara.__main__.log")
    def test_no_log_filename_when_storage_lacks_it(
        self, mock_log, mock_direct_output, mock_logger, mock_sa, mock_ss
    ):
        """When storage lacks get_filename, no filename log is emitted."""
        from dhara.__main__ import start_dhara

        mock_storage = MagicMock(spec=[])  # No get_filename attribute
        mock_address = MagicMock()
        mock_sa.new.return_value = mock_address

        start_dhara(None, 20, ("localhost", 2970), mock_storage, 100000000)

        mock_log.assert_not_called()

    @patch("dhara.__main__.StorageServer")
    @patch("dhara.__main__.SocketAddress")
    @patch("dhara.__main__.logger")
    @patch("dhara.__main__.direct_output")
    def test_creates_storage_server_and_serves(
        self, mock_direct_output, mock_logger, mock_sa, mock_ss
    ):
        """start_dhara creates a StorageServer and calls serve()."""
        from dhara.__main__ import start_dhara

        mock_storage = MagicMock()
        mock_address = MagicMock()
        mock_sa.new.return_value = mock_address
        mock_server_instance = MagicMock()
        mock_ss.return_value = mock_server_instance

        start_dhara(None, 20, ("localhost", 2970), mock_storage, 500000000)

        mock_ss.assert_called_once_with(
            mock_storage,
            address=mock_address,
            gcbytes=500000000,
            tls_config=None,
        )
        mock_server_instance.serve.assert_called_once()

    @patch("dhara.__main__.StorageServer")
    @patch("dhara.__main__.SocketAddress")
    @patch("dhara.__main__.logger")
    @patch("dhara.__main__.direct_output")
    def test_passes_tls_config(
        self, mock_direct_output, mock_logger, mock_sa, mock_ss
    ):
        """TLS config is forwarded to StorageServer."""
        from dhara.__main__ import start_dhara

        mock_storage = MagicMock()
        mock_address = MagicMock()
        mock_sa.new.return_value = mock_address
        mock_tls = MagicMock()

        start_dhara(
            None, 20, ("localhost", 2970), mock_storage, 100000000,
            tls_config=mock_tls,
        )

        mock_ss.assert_called_once_with(
            mock_storage,
            address=mock_address,
            gcbytes=100000000,
            tls_config=mock_tls,
        )


# ---------------------------------------------------------------------------
# stop_dhara
# ---------------------------------------------------------------------------


class TestStopDhara:
    """Tests for stop_dhara server shutdown helper."""

    @patch("dhara.__main__.SocketAddress")
    @patch("dhara.__main__.write")
    @patch("dhara.__main__.sleep")
    @patch("dhara.__main__.log")
    def test_server_not_running_returns_false(
        self, mock_log, mock_sleep, mock_write, mock_sa
    ):
        """When the server socket cannot be connected, returns False."""
        from dhara.__main__ import stop_dhara

        mock_address = MagicMock()
        mock_address.get_connected_socket.return_value = None
        mock_sa.new.return_value = mock_address

        result = stop_dhara(("localhost", 2970))

        assert result is False
        mock_log.assert_called_once()
        assert "doesn't seem to be running" in mock_log.call_args[0][1]

    @patch("dhara.__main__.SocketAddress")
    @patch("dhara.__main__.write")
    @patch("dhara.__main__.sleep")
    @patch("dhara.__main__.log")
    def test_sends_quit_message_and_returns_true(
        self, mock_log, mock_sleep, mock_write, mock_sa
    ):
        """When server is reachable, sends 'Q' and returns True."""
        from dhara.__main__ import stop_dhara

        mock_sock = MagicMock()
        mock_address = MagicMock()
        # First call: server is running; subsequent calls: server gone
        mock_address.get_connected_socket.side_effect = [
            mock_sock,
            None,
        ]
        mock_sa.new.return_value = mock_address

        result = stop_dhara(("localhost", 2970))

        assert result is True
        mock_write.assert_called_once_with(mock_sock, "Q")
        mock_sock.close.assert_called()

    @patch("dhara.__main__.SocketAddress")
    @patch("dhara.__main__.write")
    @patch("dhara.__main__.sleep")
    @patch("dhara.__main__.log")
    def test_retries_until_server_gone(self, mock_log, mock_sleep, mock_write, mock_sa):
        """stop_dhara polls up to 20 times waiting for the server to stop."""
        from dhara.__main__ import stop_dhara

        mock_sock = MagicMock()
        mock_address = MagicMock()
        # First: connect succeeds (initial check)
        # Then: 3 more connects during retry loop, then None
        mock_address.get_connected_socket.side_effect = [
            mock_sock,
            mock_sock,
            mock_sock,
            mock_sock,
            None,
        ]
        mock_sa.new.return_value = mock_address

        result = stop_dhara(("localhost", 2970))

        assert result is True
        # sleep is called between retries
        assert mock_sleep.call_count >= 3

    @patch("dhara.__main__.SocketAddress")
    @patch("dhara.__main__.write")
    @patch("dhara.__main__.sleep")
    @patch("dhara.__main__.log")
    def test_closes_retry_sockets(self, mock_log, mock_sleep, mock_write, mock_sa):
        """Sockets opened during retry polling are closed."""
        from dhara.__main__ import stop_dhara

        mock_sock = MagicMock()
        retry_sock = MagicMock()
        mock_address = MagicMock()
        mock_address.get_connected_socket.side_effect = [
            mock_sock,   # initial connection
            retry_sock,  # first retry (still running)
            None,        # second retry (gone)
        ]
        mock_sa.new.return_value = mock_address

        result = stop_dhara(("localhost", 2970))

        assert result is True
        # The retry socket should be closed
        retry_sock.close.assert_called_once()

    @patch("dhara.__main__.SocketAddress")
    @patch("dhara.__main__.write")
    @patch("dhara.__main__.sleep")
    @patch("dhara.__main__.log")
    def test_max_retries_exhausted(self, mock_log, mock_sleep, mock_write, mock_sa):
        """After 20 retries with server still running, returns True anyway."""
        from dhara.__main__ import stop_dhara

        mock_sock = MagicMock()
        mock_address = MagicMock()
        # Initial connection + 20 retry connections all succeed
        mock_address.get_connected_socket.side_effect = [
            mock_sock,
        ] + [MagicMock()] * 20
        mock_sa.new.return_value = mock_address

        result = stop_dhara(("localhost", 2970))

        assert result is True
        assert mock_sleep.call_count == 20

    @patch("dhara.__main__.SocketAddress")
    @patch("dhara.__main__.write")
    @patch("dhara.__main__.sleep")
    @patch("dhara.__main__.log")
    def test_unix_socket_address(self, mock_log, mock_sleep, mock_write, mock_sa):
        """stop_dhara works with unix socket address strings."""
        from dhara.__main__ import stop_dhara

        mock_address = MagicMock()
        mock_address.get_connected_socket.return_value = None
        mock_sa.new.return_value = mock_address

        result = stop_dhara("/tmp/dhara.sock")

        mock_sa.new.assert_called_once_with("/tmp/dhara.sock")
        assert result is False


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


class TestMain:
    """Tests for the main() entry point dispatcher."""

    def test_no_args_calls_usage(self):
        """When no arguments are provided, usage() is called."""
        from dhara.__main__ import main

        with patch("sys.argv", ["dhara"]):
            with patch("dhara.__main__.usage") as mock_usage:
                main()

        mock_usage.assert_called_once()

    def test_client_flag_calls_client_main(self):
        """The -c flag dispatches to client_main."""
        from dhara.__main__ import main

        with patch("sys.argv", ["dhara", "-c"]):
            with patch("dhara.__main__.client_main") as mock_client:
                main()

        mock_client.assert_called_once()

    def test_server_flag_calls_run_dhara_main(self):
        """The -s flag dispatches to run_dhara_main."""
        from dhara.__main__ import main

        with patch("sys.argv", ["dhara", "-s"]):
            with patch("dhara.__main__.run_dhara_main") as mock_server:
                main()

        mock_server.assert_called_once()

    def test_pack_flag_calls_pack_storage_main(self):
        """The -p flag dispatches to pack_storage_main."""
        from dhara.__main__ import main

        with patch("sys.argv", ["dhara", "-p"]):
            with patch("dhara.__main__.pack_storage_main") as mock_pack:
                main()

        mock_pack.assert_called_once()

    def test_unknown_flag_calls_usage(self):
        """An unrecognized flag calls usage instead of crashing."""
        from dhara.__main__ import main

        with patch("sys.argv", ["dhara", "--bogus"]):
            with patch("dhara.__main__.usage") as mock_usage:
                main()

        mock_usage.assert_called_once()

    def test_strips_first_arg_before_dispatch(self):
        """main() removes the mode flag from sys.argv before calling subcommand."""
        from dhara.__main__ import main

        original_argv = ["dhara", "-s", "--port", "9999"]

        with patch("sys.argv", original_argv):
            with patch("dhara.__main__.run_dhara_main") as mock_server:
                # Verify sys.argv was modified before the subcommand runs
                def check_argv():
                    assert sys.argv == ["dhara", "--port", "9999"]

                mock_server.side_effect = check_argv
                main()

    def test_help_flag_calls_usage(self):
        """The -h flag calls usage (it is not a recognized mode)."""
        from dhara.__main__ import main

        with patch("sys.argv", ["dhara", "-h"]):
            with patch("dhara.__main__.usage") as mock_usage:
                main()

        mock_usage.assert_called_once()


# ---------------------------------------------------------------------------
# client_main / run_dhara_main / pack_storage_main / interactive_client
# ---------------------------------------------------------------------------


class TestCliEntryPoints:
    def _parse_args(self, options):
        return patch("dhara.__main__.OptionParser.parse_args", return_value=(options, []))

    def test_client_main_invokes_interactive_client(self):
        from dhara.__main__ import client_main

        options = SimpleNamespace(
            file="client.dhara",
            host="localhost",
            port=2970,
            address=None,
            storage=None,
            cache_size=123,
            readonly=True,
            repair=True,
            startup="",
            tls_cafile=None,
            tls_capath=None,
            tls_certfile=None,
            tls_keyfile=None,
            tls_no_verify=False,
        )
        with self._parse_args(options), patch("dhara.__main__.interactive_client") as mock_client:
            client_main()

        mock_client.assert_called_once_with(
            "client.dhara",
            ("localhost", 2970),
            123,
            True,
            True,
            "",
            None,
            None,
        )

    def test_client_main_explicit_address(self):
        from dhara.__main__ import client_main

        options = SimpleNamespace(
            file=None,
            host="localhost",
            port=2970,
            address="/tmp/dhara.sock",
            storage=None,
            cache_size=10000,
            readonly=False,
            repair=False,
            startup="",
            tls_cafile=None,
            tls_capath=None,
            tls_certfile=None,
            tls_keyfile=None,
            tls_no_verify=False,
        )
        with self._parse_args(options), patch("dhara.__main__.interactive_client") as mock_client:
            client_main()

        mock_client.assert_called_once_with(
            None,
            "/tmp/dhara.sock",
            10000,
            False,
            False,
            "",
            None,
            None,
        )

    def test_client_main_tls_error_returns(self):
        from dhara.__main__ import client_main

        options = SimpleNamespace(
            file=None,
            host="localhost",
            port=2970,
            address="socket",
            storage=None,
            cache_size=10000,
            readonly=False,
            repair=False,
            startup="",
            tls_cafile="ca.pem",
            tls_capath=None,
            tls_certfile=None,
            tls_keyfile=None,
            tls_no_verify=False,
        )
        with (
            self._parse_args(options),
            patch("dhara.__main__.TLSConfig", side_effect=ValueError("bad tls")),
            patch("dhara.__main__.log") as mock_log,
            patch("dhara.__main__.interactive_client") as mock_client,
        ):
            client_main()

        mock_log.assert_called_once()
        mock_client.assert_not_called()

    def test_run_dhara_main_start_and_stop_paths(self):
        from dhara.__main__ import run_dhara_main

        start_options = SimpleNamespace(
            port=2970,
            file="server.dhara",
            host="localhost",
            storage=None,
            gcbytes=1000,
            address=None,
            owner=None,
            group=None,
            umask=None,
            logginglevel=20,
            logfile=None,
            repair=False,
            readonly=False,
            stop=False,
            tls_certfile=None,
            tls_keyfile=None,
            tls_cafile=None,
            tls_capath=None,
            generate_tls_cert=None,
        )
        stop_options = SimpleNamespace(**{**start_options.__dict__, "address": "@sock", "stop": True})

        with (
            self._parse_args(start_options),
            patch("dhara.__main__.get_storage", return_value=MagicMock()),
            patch("dhara.__main__.start_dhara") as mock_start,
            patch("dhara.__main__.SocketAddress.new", return_value="addr"),
        ):
            run_dhara_main()
        mock_start.assert_called_once()

        with (
            self._parse_args(stop_options),
            patch("dhara.__main__.stop_dhara") as mock_stop,
            patch("dhara.__main__.SocketAddress.new", return_value="addr"),
        ):
            run_dhara_main()
        mock_stop.assert_called_once_with("addr")

    def test_run_dhara_main_tls_generation_and_error(self):
        from dhara.__main__ import run_dhara_main

        generate_options = SimpleNamespace(
            port=2970,
            file=None,
            host="localhost",
            storage=None,
            gcbytes=1000,
            address=None,
            owner=None,
            group=None,
            umask=None,
            logginglevel=20,
            logfile=None,
            repair=False,
            readonly=False,
            stop=False,
            tls_certfile=None,
            tls_keyfile=None,
            tls_cafile=None,
            tls_capath=None,
            generate_tls_cert="example.com",
        )
        error_options = SimpleNamespace(**{**generate_options.__dict__, "generate_tls_cert": None, "tls_certfile": "cert.pem", "tls_keyfile": "key.pem"})

        with (
            self._parse_args(generate_options),
            patch("dhara.__main__.generate_self_signed_cert") as mock_gen,
            patch("dhara.__main__.log"),
        ):
            run_dhara_main()
        mock_gen.assert_called_once_with("server.crt", "server.key", hostname="example.com")

        with (
            self._parse_args(generate_options),
            patch("dhara.__main__.generate_self_signed_cert", side_effect=RuntimeError("boom")),
            patch("dhara.__main__.log") as mock_log,
        ):
            run_dhara_main()
        assert mock_log.called

        with (
            self._parse_args(error_options),
            patch("dhara.__main__.TLSConfig", side_effect=ValueError("bad tls")),
            patch("dhara.__main__.log") as mock_log,
        ):
            run_dhara_main()
        assert mock_log.called

    def test_run_dhara_main_tls_config_and_unix_address(self):
        from dhara.__main__ import run_dhara_main

        options = SimpleNamespace(
            port=2970,
            file="server.dhara",
            host="localhost",
            storage=None,
            gcbytes=1000,
            address="/tmp/dhara.sock",
            owner="owner",
            group="group",
            umask=0o077,
            logginglevel=20,
            logfile=None,
            repair=False,
            readonly=False,
            stop=False,
            tls_certfile="cert.pem",
            tls_keyfile="key.pem",
            tls_cafile="ca.pem",
            tls_capath=None,
            generate_tls_cert=None,
        )
        with (
            self._parse_args(options),
            patch("dhara.__main__.TLSConfig", return_value=MagicMock()) as mock_tls,
            patch("dhara.__main__.get_storage", return_value=MagicMock()),
            patch("dhara.__main__.start_dhara") as mock_start,
            patch("dhara.__main__.SocketAddress.new", return_value="addr") as mock_sa,
        ):
            run_dhara_main()

        mock_tls.assert_called_once()
        mock_sa.assert_called_once_with(
            address="/tmp/dhara.sock", owner="owner", group="group", umask=0o077
        )
        mock_start.assert_called_once()

    def test_run_dhara_main_without_af_unix_uses_tcp_address(self):
        from dhara.__main__ import run_dhara_main

        options = SimpleNamespace(
            port=2970,
            file="server.dhara",
            host="localhost",
            storage=None,
            gcbytes=1000,
            address=None,
            owner=None,
            group=None,
            umask=None,
            logginglevel=20,
            logfile=None,
            repair=False,
            readonly=False,
            stop=False,
            tls_certfile=None,
            tls_keyfile=None,
            tls_cafile=None,
            tls_capath=None,
            generate_tls_cert=None,
        )

        with (
            self._parse_args(options),
            patch("dhara.__main__.get_storage", return_value=MagicMock()),
            patch("dhara.__main__.start_dhara") as mock_start,
            patch("dhara.__main__.socket") as mock_socket,
        ):
            del mock_socket.AF_UNIX
            run_dhara_main()

        mock_start.assert_called_once()

    def test_pack_storage_main_file_and_socket_paths(self):
        from dhara.__main__ import pack_storage_main

        file_options = SimpleNamespace(
            file="pack.dhara",
            port=2970,
            host="localhost",
            tls_cafile=None,
            tls_certfile=None,
            tls_keyfile=None,
        )
        socket_options = SimpleNamespace(
            file=None,
            port=2999,
            host="127.0.0.1",
            tls_cafile=None,
            tls_certfile=None,
            tls_keyfile=None,
        )

        with (
            self._parse_args(file_options),
            patch("dhara.__main__.get_storage", return_value=MagicMock()) as mock_get_storage,
            patch("dhara.__main__.Connection") as mock_connection,
        ):
            pack_storage_main()
        mock_get_storage.assert_called_once_with("pack.dhara")
        mock_connection.assert_called_once()

        with (
            self._parse_args(socket_options),
            patch("dhara.__main__.wait_for_server") as mock_wait,
            patch("dhara.__main__.ClientStorage", return_value=MagicMock()) as mock_client,
            patch("dhara.__main__.Connection") as mock_connection2,
        ):
            pack_storage_main()
        mock_wait.assert_called_once_with("127.0.0.1", 2999)
        mock_client.assert_called_once()
        mock_connection2.assert_called()

    def test_pack_storage_main_tls_error(self):
        from dhara.__main__ import pack_storage_main

        options = SimpleNamespace(
            file=None,
            port=2999,
            host="127.0.0.1",
            tls_cafile="ca.pem",
            tls_certfile=None,
            tls_keyfile=None,
        )

        with (
            self._parse_args(options),
            patch("dhara.__main__.TLSConfig", side_effect=ValueError("bad tls")),
            patch("dhara.__main__.log") as mock_log,
        ):
            pack_storage_main()

        assert mock_log.called

    def test_interactive_client_fallback_console_and_socket_paths(self, monkeypatch):
        from dhara.__main__ import interactive_client

        class FakeConsole:
            def __init__(self, ns):
                self.ns = ns
                self.runsource = MagicMock()
                self.interact = MagicMock()

        fake_console = MagicMock(return_value=FakeConsole({}))
        fake_storage = MagicMock()
        fake_connection = MagicMock()
        fake_connection.get_root.return_value = {"root": True}
        fake_registry = MagicMock()
        fake_registry.store_adapter = MagicMock()
        fake_registry.get_adapter = MagicMock()
        fake_registry.list_adapters = MagicMock()
        fake_registry.list_adapter_versions = MagicMock()
        fake_registry.validate_adapter = MagicMock()
        fake_registry.check_adapter_health = MagicMock()
        fake_registry.count = 0

        monkeypatch.setitem(sys.modules, "IPython", None)
        monkeypatch.setitem(sys.modules, "IPython.terminal.embed", None)
        monkeypatch.setitem(sys.modules, "IPython.terminal.ipapp", None)

        with (
            patch("dhara.__main__.get_storage", return_value=fake_storage),
            patch("dhara.__main__.Connection", return_value=fake_connection),
            patch("dhara.mcp.adapter_tools.AdapterRegistry", return_value=fake_registry),
            patch("code.InteractiveConsole", fake_console),
            patch("dhara.__main__.configure_readline"),
            patch("dhara.__main__.warn"),
        ):
            interactive_client(
                file="client.dhara",
                address=None,
                cache_size=42,
                readonly=False,
                repair=False,
                startup="startup.py",
                storage_class=None,
                tls_config=None,
            )

        fake_console.return_value.runsource.assert_called_once()
        fake_console.return_value.interact.assert_called_once()

        with (
            patch("dhara.__main__.SocketAddress.new", return_value="sockaddr"),
            patch("dhara.__main__.wait_for_server"),
            patch("dhara.__main__.ClientStorage", return_value=fake_storage) as mock_client,
            patch("dhara.__main__.Connection", return_value=fake_connection),
            patch("dhara.mcp.adapter_tools.AdapterRegistry", side_effect=ImportError),
            patch("code.InteractiveConsole", fake_console),
            patch("dhara.__main__.configure_readline"),
        ):
            interactive_client(
                file=None,
                address=("localhost", 2970),
                cache_size=11,
                readonly=False,
                repair=False,
                startup="",
                storage_class=None,
                tls_config=None,
            )

        mock_client.assert_called_once()

    def test_interactive_client_ipython_path(self, monkeypatch):
        from types import ModuleType

        from dhara.__main__ import interactive_client

        fake_ipython = ModuleType("IPython")
        fake_terminal = ModuleType("IPython.terminal")
        fake_embed = ModuleType("IPython.terminal.embed")
        fake_ipapp = ModuleType("IPython.terminal.ipapp")
        shell = MagicMock()
        fake_embed.InteractiveShellEmbed = MagicMock(return_value=shell)
        fake_ipapp.load_default_config = MagicMock()
        fake_terminal.embed = fake_embed
        fake_terminal.ipapp = fake_ipapp
        fake_ipython.terminal = fake_terminal

        fake_storage = MagicMock()
        fake_connection = MagicMock()
        fake_connection.get_root.return_value = {"root": True}

        monkeypatch.setitem(sys.modules, "IPython", fake_ipython)
        monkeypatch.setitem(sys.modules, "IPython.terminal", fake_terminal)
        monkeypatch.setitem(sys.modules, "IPython.terminal.embed", fake_embed)
        monkeypatch.setitem(sys.modules, "IPython.terminal.ipapp", fake_ipapp)

        with (
            patch("dhara.__main__.get_storage", return_value=fake_storage),
            patch("dhara.__main__.Connection", return_value=fake_connection),
            patch("dhara.mcp.adapter_tools.AdapterRegistry", side_effect=ImportError),
        ):
            interactive_client(
                file="client.dhara",
                address=None,
                cache_size=42,
                readonly=False,
                repair=False,
                startup="",
                storage_class=None,
                tls_config=None,
            )

        shell.assert_called_once()
