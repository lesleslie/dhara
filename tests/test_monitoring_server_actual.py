"""Tests for dhara.monitoring.server."""

from __future__ import annotations

import io
from unittest.mock import Mock

import pytest

from dhara.monitoring import server as monitoring_server


class DummyHandler:
    def __init__(self):
        self.path = "/"
        self.wfile = io.BytesIO()
        self.responses: list[tuple[int, str | None]] = []
        self.headers: list[tuple[str, str]] = []
        self.error: tuple[int, str] | None = None

    def send_response(self, code):
        self.responses.append((code, None))

    def send_header(self, name, value):
        self.headers.append((name, value))

    def end_headers(self):
        pass

    def send_error(self, code, message):
        self.error = (code, message)


def _make_handler() -> DummyHandler:
    return DummyHandler()


class TestFindAvailablePort:
    def test_returns_first_free_port(self, monkeypatch):
        class FakeSocket:
            def __init__(self, *args, **kwargs):
                pass

            def bind(self, addr):
                self.addr = addr

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        monkeypatch.setattr(monitoring_server.socket, "socket", FakeSocket)
        assert monitoring_server.find_available_port(9100, 9100) == 9100

    def test_returns_zero_when_all_ports_busy(self, monkeypatch):
        class BusySocket:
            def __init__(self, *args, **kwargs):
                pass

            def bind(self, addr):
                raise OSError("busy")

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        monkeypatch.setattr(monitoring_server.socket, "socket", BusySocket)
        assert monitoring_server.find_available_port(9100, 9101) == 0


class TestMetricsHandler:
    def test_do_get_metrics_string(self, monkeypatch):
        handler = _make_handler()
        handler.path = "/metrics"
        monkeypatch.setattr(monitoring_server, "get_server_metrics", lambda: "metric 1\\n")

        monitoring_server.MetricsHandler._serve_metrics(handler)

        assert handler.responses == [(200, None)]
        assert ("Content-Type", "text/plain; version=0.0.4; charset=utf-8") in handler.headers
        assert handler.wfile.getvalue() == b"metric 1\\n"

    def test_do_get_metrics_json(self, monkeypatch):
        handler = _make_handler()
        monkeypatch.setattr(monitoring_server, "get_server_metrics", lambda: {"a": 1})

        monitoring_server.MetricsHandler._serve_metrics(handler)

        assert handler.responses == [(200, None)]
        assert ("Content-Type", "application/json") in handler.headers
        assert handler.wfile.getvalue() == b'{"a": 1}'

    def test_do_get_metrics_error(self, monkeypatch):
        handler = _make_handler()
        monkeypatch.setattr(monitoring_server, "get_server_metrics", lambda: (_ for _ in ()).throw(RuntimeError("boom")))

        monitoring_server.MetricsHandler._serve_metrics(handler)

        assert handler.error == (500, "Failed to generate metrics: boom")

    def test_do_get_health_healthy(self, monkeypatch):
        handler = _make_handler()
        monkeypatch.setattr(monitoring_server, "get_health_status", lambda: {"status": "healthy", "checks": []})

        monitoring_server.MetricsHandler._serve_health(handler)

        assert handler.responses == [(200, None)]
        assert handler.wfile.getvalue() == b'{"status": "healthy", "checks": []}'

    def test_do_get_health_unhealthy(self, monkeypatch):
        handler = _make_handler()
        monkeypatch.setattr(monitoring_server, "get_health_status", lambda: {"status": "unhealthy", "checks": []})

        monitoring_server.MetricsHandler._serve_health(handler)

        assert handler.responses == [(503, None)]

    def test_do_get_health_error(self, monkeypatch):
        handler = _make_handler()
        monkeypatch.setattr(monitoring_server, "get_health_status", lambda: (_ for _ in ()).throw(RuntimeError("bad")))

        monitoring_server.MetricsHandler._serve_health(handler)

        assert handler.error == (500, "Failed to generate health status: bad")

    def test_do_get_ready_ready(self, monkeypatch):
        handler = _make_handler()
        checker = Mock()
        checker.is_ready.return_value = True
        monkeypatch.setattr(monitoring_server, "get_health_checker", lambda: checker)

        monitoring_server.MetricsHandler._serve_ready(handler)

        assert handler.responses == [(200, None)]
        assert handler.wfile.getvalue() == b'{"ready": true, "status": "ready"}'

    def test_do_get_ready_not_ready(self, monkeypatch):
        handler = _make_handler()
        checker = Mock()
        checker.is_ready.return_value = False
        monkeypatch.setattr(monitoring_server, "get_health_checker", lambda: checker)

        monitoring_server.MetricsHandler._serve_ready(handler)

        assert handler.responses == [(503, None)]

    def test_do_get_ready_error(self, monkeypatch):
        handler = _make_handler()
        monkeypatch.setattr(monitoring_server, "get_health_checker", lambda: (_ for _ in ()).throw(RuntimeError("oops")))

        monitoring_server.MetricsHandler._serve_ready(handler)

        assert handler.error == (500, "Failed to check readiness: oops")

    @pytest.mark.parametrize(
        "path, method_name",
        [
            ("/metrics", "_serve_metrics"),
            ("/health", "_serve_health"),
            ("/healthz", "_serve_health"),
            ("/ready", "_serve_ready"),
            ("/readyz", "_serve_ready"),
        ],
    )
    def test_do_get_dispatches(self, monkeypatch, path, method_name):
        handler = _make_handler()
        handler.path = path
        called: list[str] = []
        setattr(handler, method_name, lambda: called.append(method_name))

        monitoring_server.MetricsHandler.do_GET(handler)

        assert called == [method_name]

    def test_do_get_unknown_path(self):
        handler = _make_handler()
        handler.path = "/unknown"

        monitoring_server.MetricsHandler.do_GET(handler)

        assert handler.error == (404, "Not Found")

    def test_log_message_is_noop(self):
        handler = _make_handler()
        assert monitoring_server.MetricsHandler.log_message(handler, "x") is None


class TestMetricsServer:
    def test_init_with_explicit_port(self):
        server = monitoring_server.MetricsServer(host="127.0.0.1", port=9091)
        assert server.host == "127.0.0.1"
        assert server.port == 9091
        assert server.server is None
        assert server._running is False

    def test_init_with_discovered_port(self, monkeypatch):
        monkeypatch.setattr(monitoring_server, "find_available_port", lambda: 9123)
        server = monitoring_server.MetricsServer(host="127.0.0.1", port=None)
        assert server.port == 9123

    def test_start_when_already_running(self):
        server = monitoring_server.MetricsServer(port=9092)
        server._running = True
        assert server.start() is None

    def test_start_and_stop(self, monkeypatch):
        server = monitoring_server.MetricsServer(port=9093)
        fake_http = Mock()
        monkeypatch.setattr(monitoring_server, "HTTPServer", lambda addr, handler: fake_http)

        server.start()
        assert server.server is fake_http
        assert server._running is True

        server.stop()
        assert server._running is False
        fake_http.shutdown.assert_called_once()

    def test_stop_without_server(self):
        server = monitoring_server.MetricsServer(port=9093)
        server.stop()
        assert server._running is False

    def test_start_failure_raises(self, monkeypatch):
        server = monitoring_server.MetricsServer(port=9094)
        monkeypatch.setattr(monitoring_server, "HTTPServer", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("bind failed")))

        with pytest.raises(RuntimeError, match="bind failed"):
            server.start()

    def test_serve_forever(self):
        server = monitoring_server.MetricsServer(port=9095)
        fake_http = Mock()
        server.server = fake_http
        server.serve_forever()
        fake_http.serve_forever.assert_called_once()

    def test_serve_forever_without_server(self):
        server = monitoring_server.MetricsServer(port=9095)
        server.serve_forever()

    def test_start_metrics_server_helper(self, monkeypatch):
        created = Mock()
        monkeypatch.setattr(monitoring_server, "MetricsServer", lambda host, port: created)
        created.start = Mock()

        result = monitoring_server.start_metrics_server(host="0.0.0.0", port=9000)

        assert result is created
        created.start.assert_called_once()
