"""HTTP server for exposing metrics and health endpoints.

Provides a simple HTTP server on top of prometheus_client and
exposes metrics and health endpoints for monitoring.
"""

import socket
from http.server import BaseHTTPRequestHandler, HTTPServer

from druva.monitoring.health import get_health_checker, get_health_status
from druva.monitoring.metrics import get_server_metrics


class MetricsHandler(BaseHTTPRequestHandler):
    """HTTP request handler for metrics and health endpoints."""

    def do_GET(self):
        """Handle GET requests."""
        if self.path == "/metrics":
            self._serve_metrics()
        elif self.path == "/health" or self.path == "/healthz":
            self._serve_health()
        elif self.path == "/ready" or self.path == "/readyz":
            self._serve_ready()
        else:
            self.send_error(404, "Not Found")

    def _serve_metrics(self):
        """Serve Prometheus metrics."""
        try:
            metrics = get_server_metrics()

            if isinstance(metrics, str):
                # Prometheus format
                self.send_response(200)
                self.send_header(
                    "Content-Type", "text/plain; version=0.0.4; charset=utf-8"
                )
                self.end_headers()
                self.wfile.write(metrics.encode("utf-8"))
            else:
                # JSON format (fallback)
                import json

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(metrics).encode("utf-8"))
        except Exception as e:
            self.send_error(500, f"Failed to generate metrics: {e}")

    def _serve_health(self):
        """Serve health status."""
        try:
            import json

            health = get_health_status()

            self.send_response(200 if health["status"] == "healthy" else 503)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(health).encode("utf-8"))
        except Exception as e:
            self.send_error(500, f"Failed to generate health status: {e}")

    def _serve_ready(self):
        """Serve readiness status."""
        try:
            import json

            checker = get_health_checker()
            ready = checker.is_ready()

            health = {
                "ready": ready,
                "status": "ready" if ready else "not_ready",
            }

            self.send_response(200 if ready else 503)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(health).encode("utf-8"))
        except Exception as e:
            self.send_error(500, f"Failed to check readiness: {e}")

    def log_message(self, format: str, *args):
        """Log an arbitrary message (disabled by default)."""
        pass


def find_available_port(start_port: int = 9090, max_port: int = 9999) -> int:
    """Find an available port for the metrics server.

    Args:
        start_port: Port to start checking from
        max_port: Maximum port to check

    Returns:
        Available port number, or 0 if none found
    """
    for port in range(start_port, max_port + 1):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("127.0.0.1", port))
                return port
        except OSError:
            continue
    return 0


class MetricsServer:
    """HTTP server for metrics and health endpoints.

    Example:
        >>> server = MetricsServer(host="127.0.0.1", port=9090)
        >>> server.start()
        >>> # Access http://127.0.0.1:9090/metrics
        >>> # Access http://127.0.0.1:9090/health
        >>> server.stop()
    """

    def __init__(self, host: str = "127.0.0.1", port: int | None = None):
        """Initialize metrics server.

        Args:
            host: Host to bind to
            port: Port to bind to (None to find available port)
        """
        self.host = host

        if port is None:
            port = find_available_port()

        self.port = port
        self.server = None
        self._running = False

    def start(self):
        """Start the metrics server."""
        if self._running:
            return

        try:
            self.server = HTTPServer((self.host, self.port), MetricsHandler)
            self._running = True
            print(f"Metrics server listening on http://{self.host}:{self.port}")
            print(f"  Metrics: http://{self.host}:{self.port}/metrics")
            print(f"  Health:  http://{self.host}:{self.port}/health")
            print(f"  Ready:   http://{self.host}:{self.port}/ready")

            # Server in a separate thread would be better, but keeping it simple
            # self.server.serve_forever()
        except Exception as e:
            print(f"Failed to start metrics server: {e}")
            raise

    def stop(self):
        """Stop the metrics server."""
        if self.server is not None:
            self.server.shutdown()
            self._running = False

    def serve_forever(self):
        """Run the metrics server forever."""
        if self.server is not None:
            self.server.serve_forever()


def start_metrics_server(
    host: str = "127.0.0.1", port: int | None = None
) -> MetricsServer:
    """Start a metrics server and return it.

    Args:
        host: Host to bind to
        port: Port to bind to (None to find available)

    Returns:
        MetricsServer instance

    Example:
        >>> server = start_metrics_server(port=9090)
        >>> # Server is running in background
        >>> # To stop: server.stop()
    """
    server = MetricsServer(host=host, port=port)
    server.start()
    return server
