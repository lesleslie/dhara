import importlib
import io
import logging
import sys
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def logger_mod():
    return importlib.import_module("dhara.logging.logger")


def test_setup_logging_builds_config(logger_mod, monkeypatch):
    captured = {}

    def fake_configure_logging(config):
        captured["config"] = config

    monkeypatch.setattr(logger_mod, "configure_logging", fake_configure_logging)

    output = io.StringIO()
    logger_mod.setup_logging(
        level=logging.DEBUG,
        format="%(levelname)s:%(message)s",
        output=output,
        emit_json=True,
        traceback_style="dict",
    )

    config = captured["config"]
    assert config.level == "DEBUG"
    assert config.emit_json is True
    assert len(config.sinks) == 1
    assert config.sinks[0].target == "stderr"


def test_setup_logging_uses_stdout_target(logger_mod, monkeypatch):
    captured = {}

    def fake_configure_logging(config):
        captured["config"] = config

    monkeypatch.setattr(logger_mod, "configure_logging", fake_configure_logging)

    logger_mod.setup_logging(level="warning", output=sys.stdout)

    config = captured["config"]
    assert config.level == "WARNING"
    assert config.sinks[0].target == "stdout"


def test_get_logger_and_storage_logger(logger_mod, monkeypatch):
    created = {}

    def fake_get_logger(name):
        logger = MagicMock(name=f"logger:{name}")
        logger.logger_name = name
        logger.bind.return_value = MagicMock(name=f"bound:{name}")
        created[name] = logger
        return logger

    monkeypatch.setattr(logger_mod, "_oneiric_get_logger", fake_get_logger)

    root_logger = logger_mod.get_logger()
    child_logger = logger_mod.get_logger("storage")
    conn_logger = logger_mod.get_connection_logger("conn-001")
    storage_logger = logger_mod.get_storage_logger("file", "/data/my.db")
    bare_storage_logger = logger_mod.get_storage_logger("sqlite")

    assert root_logger.logger_name == "durus"
    assert child_logger.logger_name == "durus.storage"
    assert conn_logger.logger_name == "durus.connection.conn-001"
    assert storage_logger.logger_name == "durus.storage.file._data_my_db"
    assert bare_storage_logger.logger_name == "durus.storage.sqlite"


def test_log_operation_logs_success_and_failure(logger_mod, monkeypatch):
    func_logger = MagicMock()
    monkeypatch.setattr(logger_mod, "get_logger", MagicMock(return_value=func_logger))

    with logger_mod.log_operation("commit", oid_count=3):
        pass

    func_logger.debug.assert_any_call("Started %s", "commit", oid_count=3)
    func_logger.debug.assert_any_call("Completed %s", "commit")

    func_logger.reset_mock()

    with pytest.raises(ValueError, match="boom"):
        with logger_mod.log_operation("load", oid=7):
            raise ValueError("boom")

    func_logger.exception.assert_called_once()
    assert func_logger.exception.call_args.args[0] == "Failed %s: %s"
    assert func_logger.exception.call_args.args[1] == "load"
    assert isinstance(func_logger.exception.call_args.args[2], ValueError)


def test_log_operation_decorator_logs_success_and_failure(logger_mod, monkeypatch):
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

    func_logger.exception.assert_called_once()
    assert func_logger.exception.call_args.args[0] == "Failed %s: %s"


def test_log_context_returns_bound_logger(logger_mod, monkeypatch):
    base_logger = MagicMock()
    bound_logger = MagicMock()
    base_logger.bind.return_value = bound_logger
    monkeypatch.setattr(logger_mod, "get_logger", MagicMock(return_value=base_logger))

    adapter = logger_mod.log_context(request_id="req-1", user="alice")

    base_logger.bind.assert_called_once_with(request_id="req-1", user="alice")
    assert adapter is bound_logger


def test_import_time_does_not_auto_configure_logging(logger_mod):
    original_handlers = list(logger_mod.logger.handlers)
    logger_mod.logger.handlers.clear()

    try:
        reloaded = importlib.reload(logger_mod)
        assert reloaded is logger_mod
        assert reloaded.logger.handlers == []
    finally:
        logger_mod.logger.handlers.clear()
        logger_mod.logger.handlers.extend(original_handlers)
        importlib.reload(logger_mod)
