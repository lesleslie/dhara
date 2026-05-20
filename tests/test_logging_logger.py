import io
import logging
import importlib
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def isolated_logger(monkeypatch):
    logger_mod = importlib.import_module("dhara.logging.logger")

    test_logger = logging.Logger("durus.test.logger")
    test_logger.handlers.clear()
    test_logger.propagate = True
    monkeypatch.setattr(logger_mod, "logger", test_logger)
    return logger_mod, test_logger


def test_setup_logging_configures_handler(isolated_logger):
    logger_mod, test_logger = isolated_logger
    output = io.StringIO()

    logger_mod.setup_logging(
        level=logging.DEBUG,
        format="%(levelname)s:%(message)s",
        output=output,
    )

    assert len(test_logger.handlers) == 1
    assert test_logger.level == logging.DEBUG
    assert test_logger.propagate is False

    test_logger.info("hello")
    assert output.getvalue().strip() == "INFO:hello"


def test_setup_logging_is_idempotent(isolated_logger):
    logger_mod, test_logger = isolated_logger
    existing_handler = logging.StreamHandler(io.StringIO())
    test_logger.addHandler(existing_handler)

    logger_mod.setup_logging(level=logging.DEBUG, output=io.StringIO())

    assert test_logger.handlers == [existing_handler]


def test_get_logger_and_storage_logger(isolated_logger):
    logger_mod, test_logger = isolated_logger

    root_logger = logger_mod.get_logger()
    child_logger = logger_mod.get_logger("storage")
    conn_logger = logger_mod.get_connection_logger("conn-001")
    storage_logger = logger_mod.get_storage_logger("file", "/data/my.db")
    bare_storage_logger = logger_mod.get_storage_logger("sqlite")

    assert root_logger is test_logger
    assert child_logger.name == "durus.test.logger.storage"
    assert conn_logger.name == "durus.test.logger.connection.conn-001"
    assert storage_logger.name == "durus.test.logger.storage.file._data_my_db"
    assert bare_storage_logger.name == "durus.test.logger.storage.sqlite"


def test_log_operation_logs_success_and_failure(isolated_logger, monkeypatch):
    logger_mod, _ = isolated_logger
    debug = MagicMock()
    error = MagicMock()
    monkeypatch_logger = MagicMock()
    monkeypatch_logger.debug = debug
    monkeypatch_logger.error = error
    monkeypatch.setattr(logger_mod, "logger", monkeypatch_logger)

    with logger_mod.log_operation("commit", oid_count=3):
        pass

    debug.assert_any_call("Started %s", "commit", extra={"oid_count": 3})
    debug.assert_any_call("Completed %s", "commit")

    debug.reset_mock()
    error.reset_mock()

    with pytest.raises(ValueError, match="boom"):
        with logger_mod.log_operation("load", oid=7):
            raise ValueError("boom")

    error.assert_called_once()
    assert error.call_args.args[0] == "Failed %s: %s"
    assert error.call_args.args[1] == "load"
    assert isinstance(error.call_args.args[2], ValueError)
    assert str(error.call_args.args[2]) == "boom"


def test_log_operation_decorator_logs_success_and_failure(isolated_logger, monkeypatch):
    logger_mod, _ = isolated_logger
    func_logger = MagicMock()
    monkeypatch.setattr(logger_mod, "get_logger", MagicMock(return_value=func_logger))

    @logger_mod.log_operation_decorator("backup")
    def build(value):
        return value * 2

    assert build(4) == 8
    func_logger.debug.assert_any_call("Started %s", "backup")
    func_logger.debug.assert_any_call("Completed %s", "backup")

    func_logger.reset_mock()

    @logger_mod.log_operation_decorator()
    def explode():
        raise RuntimeError("nope")

    with pytest.raises(RuntimeError, match="nope"):
        explode()

    func_logger.error.assert_called_once()
    assert func_logger.error.call_args.args[0] == "Failed %s: %s"


def test_log_context_returns_adapter(isolated_logger):
    logger_mod, test_logger = isolated_logger

    adapter = logger_mod.log_context(request_id="req-1", user="alice")

    assert adapter.logger is test_logger
    assert adapter.extra == {"request_id": "req-1", "user": "alice"}


def test_import_time_setup_logging_runs_when_logger_has_no_handlers(monkeypatch):
    logger_mod = importlib.import_module("dhara.logging.logger")
    original_handlers = list(logger_mod.logger.handlers)
    logger_mod.logger.handlers.clear()

    try:
        reloaded = importlib.reload(logger_mod)
        assert reloaded is logger_mod
        assert reloaded.logger.handlers
    finally:
        logger_mod.logger.handlers.clear()
        logger_mod.logger.handlers.extend(original_handlers)
        importlib.reload(logger_mod)
