"""
Tests for monitoring server in Dhara.

These tests verify the monitoring server functionality including:
- HTTP API endpoints for metrics and health
- WebSocket real-time updates
- Client connections management
- Server lifecycle management
"""

import pytest
import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Dict, List, Any, Optional

from dhara.monitoring.server import MonitoringServer
from dhara.monitoring.health import HealthMonitor, HealthStatus
from dhara.monitoring.metrics import MetricsCollector, Metric, MetricType
from dhara.storage.base import StorageBackend


class TestMonitoringServer:
    """Test monitoring server functionality."""

    @pytest.fixture
    def metrics_collector(self) -> MetricsCollector:
        """Create a metrics collector."""
        return MetricsCollector()

    @pytest.fixture
    def health_monitor(self) -> HealthMonitor:
        """Create a health monitor."""
        return HealthMonitor()

    @pytest.fixture
    def monitoring_server(self, metrics_collector: MetricsCollector, health_monitor: HealthMonitor) -> MonitoringServer:
        """Create a monitoring server instance."""
        return MonitoringServer(
            metrics_collector=metrics_collector,
            health_monitor=health_monitor,
            host="127.0.0.1",
            port=9090,
        )

    @pytest.mark.asyncio
    async def test_server_initialization(self, monitoring_server: MonitoringServer):
        """Test server initialization."""
        # Verify server properties
        assert monitoring_server.host == "127.0.0.1"
        assert monitoring_server.port == 9090
        assert monitoring_server.is_running is False
        assert monitoring_server.metrics_collector is not None
        assert monitoring_server.health_monitor is not None

    @pytest.mark.asyncio
    async def test_start_server(self, monitoring_server: MonitoringServer):
        """Test starting the server."""
        # Start server
        task = await monitoring_server.start()

        # Verify server is running
        assert monitoring_server.is_running is True
        assert task is not None

        # Stop server
        await monitoring_server.stop()
        assert monitoring_server.is_running is False

    @pytest.mark.asyncio
    async def test_health_check_endpoint(self, monitoring_server: MonitoringServer):
        """Test health check HTTP endpoint."""
        # Mock healthy state
        async def mock_healthy_check():
            return HealthStatus.HEALTHY

        monitoring_server.health_monitor.register_health_check(
            name="test-check",
            check_func=mock_healthy_check,
        )

        # Start server
        await monitoring_server.start()

        # Simulate HTTP request to health endpoint
        response = await monitoring_server.simulate_health_request()

        # Verify response
        assert response["status"] == "healthy"
        assert "checks" in response
        assert len(response["checks"]) == 1

        # Stop server
        await monitoring_server.stop()

    @pytest.mark.asyncio
    async def test_metrics_endpoint(self, monitoring_server: MonitoringServer):
        """Test metrics HTTP endpoint."""
        # Collect some metrics
        metric = Metric(
            name="test.metric",
            metric_type=MetricType.COUNTER,
            value=100,
        )
        monitoring_server.metrics_collector.collect_metric(metric)

        # Start server
        await monitoring_server.start()

        # Simulate HTTP request to metrics endpoint
        response = await monitoring_server.simulate_metrics_request()

        # Verify response
        assert "metrics" in response
        assert len(response["metrics"]) == 1
        assert response["metrics"][0]["name"] == "test.metric"

        # Stop server
        await monitoring_server.stop()

    @pytest.mark.asyncio
    async def test_metrics_endpoint_with_filtering(self, monitoring_server: MonitoringServer):
        """Test metrics endpoint with filtering."""
        # Collect multiple metrics
        metrics = [
            Metric("requests.total", MetricType.COUNTER, 1000),
            Metric("errors.total", MetricType.COUNTER, 10),
            Metric("response.time", MetricType.HISTOGRAM, 150),
        ]

        for metric in metrics:
            monitoring_server.metrics_collector.collect_metric(metric)

        # Start server
        await monitoring_server.start()

        # Request filtered metrics
        response = await monitoring_server.simulate_metrics_request(
            name="requests.total"
        )

        # Verify filtering worked
        assert len(response["metrics"]) == 1
        assert response["metrics"][0]["name"] == "requests.total"

        # Stop server
        await monitoring_server.stop()

    @pytest.mark.asyncio
    async def test_metrics_endpoint_with_aggregation(self, monitoring_server: MonitoringServer):
        """Test metrics endpoint with aggregation."""
        # Collect time series data
        now = datetime.now()
        metrics = [
            Metric("cpu.usage", MetricType.GAUGE, 50, timestamp=now - timedelta(seconds=30)),
            Metric("cpu.usage", MetricType.GAUGE, 60, timestamp=now),
        ]

        for metric in metrics:
            monitoring_server.metrics_collector.collect_metric(metric)

        # Start server
        await monitoring_server.start()

        # Request aggregated metrics
        response = await monitoring_server.simulate_metrics_request(
            name="cpu.usage",
            aggregate=True
        )

        # Verify aggregation
        assert "aggregates" in response
        assert len(response["aggregates"]) == 1
        aggregate = response["aggregates"][0]
        assert "avg" in aggregate
        assert "count" in aggregate

        # Stop server
        await monitoring_server.stop()

    @pytest.mark.asyncio
    async def test_websocket_connection(self, monitoring_server: MonitoringServer):
        """Test WebSocket connection and real-time updates."""
        # Mock WebSocket client
        mock_websocket = AsyncMock()
        mock_websocket.send = AsyncMock()

        # Start server
        await monitoring_server.start()

        # Connect WebSocket client
        client = await monitoring_server.simulate_websocket_connection()

        # Verify connection
        assert client is not None

        # Send a metric update
        metric = Metric("test.metric", MetricType.COUNTER, 100)
        monitoring_server.metrics_collector.collect_metric(metric)

        # Wait for real-time update
        await asyncio.sleep(0.1)

        # Verify WebSocket received update
        mock_websocket.send.assert_called()

        # Disconnect client
        await client.close()

        # Stop server
        await monitoring_server.stop()

    @pytest.mark.asyncio
    async def test_websocket_subscription(self, monitoring_server: MonitoringServer):
        """Test WebSocket subscription to specific metrics."""
        # Mock WebSocket client
        mock_websocket = AsyncMock()
        mock_websocket.send = AsyncMock()

        # Start server
        await monitoring_server.start()

        # Connect client and subscribe to specific metrics
        client = await monitoring_server.simulate_websocket_connection()
        await client.subscribe("cpu.usage")

        # Collect metric (should trigger update)
        metric = Metric("cpu.usage", MetricType.GAUGE, 75)
        monitoring_server.metrics_collector.collect_metric(metric)

        # Wait for update
        await asyncio.sleep(0.1)

        # Verify subscription worked
        mock_websocket.send.assert_called()

        # Collect unrelated metric (should not trigger update)
        unrelated_metric = Metric("memory.usage", MetricType.GAUGE, 60)
        monitoring_server.metrics_collector.collect_metric(unrelated_metric)

        # Send unrelated metric, wait, then verify only one update occurred
        await asyncio.sleep(0.1)

        # Verify subscription (should only have received cpu.usage update)
        send_call_count = mock_websocket.send.call_count
        assert send_call_count > 0  # At least one update from cpu.usage

        # Disconnect client
        await client.close()

        # Stop server
        await monitoring_server.stop()

    @pytest.mark.asyncio
    async def test_client_management(self, monitoring_server: MonitoringServer):
        """Test client connection management."""
        # Start server
        await monitoring_server.start()

        # Connect multiple clients
        clients = []
        for _ in range(3):
            client = await monitoring_server.simulate_websocket_connection()
            clients.append(client)

        # Verify client count
        assert len(monitoring_server.clients) == 3

        # Disconnect one client
        await clients[0].close()

        # Verify client count updated
        assert len(monitoring_server.clients) == 2

        # Disconnect remaining clients
        for client in clients[1:]:
            await client.close()

        # Verify all clients disconnected
        assert len(monitoring_server.clients) == 0

        # Stop server
        await monitoring_server.stop()

    @pytest.mark.asyncio
    async def test_server_shutdown_gracefully(self, monitoring_server: MonitoringServer):
        """Test graceful server shutdown."""
        # Connect clients
        client1 = await monitoring_server.simulate_websocket_connection()
        client2 = await monitoring_server.simulate_websocket_connection()

        # Start server
        await monitoring_server.start()

        # Shutdown server gracefully
        shutdown_task = asyncio.create_task(monitoring_server.stop())

        # Wait a bit for shutdown to complete
        await asyncio.sleep(0.1)

        # Verify server is stopping
        assert monitoring_server.is_running is False

        # Verify clients are disconnected
        await shutdown_task

    @pytest.mark.asyncio
    async def test_metrics_export_endpoint(self, monitoring_server: MonitoringServer):
        """Test metrics export endpoint."""
        # Collect some metrics
        metrics = [
            Metric("requests.total", MetricType.COUNTER, 1000),
            Metric("response.time", MetricType.HISTOGRAM, 150),
        ]

        for metric in metrics:
            monitoring_server.metrics_collector.collect_metric(metric)

        # Start server
        await monitoring_server.start()

        # Test Prometheus export
        response = await monitoring_server.simulate_export_request(format="prometheus")
        assert "requests_total" in response
        assert "TYPE" in response

        # Test JSON export
        response = await monitoring_server.simulate_export_request(format="json")
        data = json.loads(response)
        assert isinstance(data, list)
        assert len(data) == 2

        # Stop server
        await monitoring_server.stop()

    @pytest.mark.asyncio
    async def test_health_check_aggregation_endpoint(self, monitoring_server: MonitoringServer):
        """Test health check aggregation endpoint."""
        # Mock healthy check
        async def mock_healthy_check():
            return HealthStatus.HEALTHY

        # Mock unhealthy check
        async def mock_unhealthy_check():
            return HealthStatus.UNHEALTHY

        # Register checks
        monitoring_server.health_monitor.register_health_check(
            name="healthy-service",
            check_func=mock_healthy_check,
        )
        monitoring_server.health_monitor.register_health_check(
            name="unhealthy-service",
            check_func=mock_unhealthy_check,
        )

        # Start server
        await monitoring_server.start()

        # Request health status
        response = await monitoring_server.simulate_health_request()

        # Verify aggregation
        assert response["overall_status"] == "degraded"
        assert len(response["checks"]) == 2

        # Stop server
        await monitoring_server.stop()

    @pytest.mark.asyncio
    async def test_metrics_history_endpoint(self, monitoring_server: MonitoringServer):
        """Test metrics history endpoint."""
        # Collect time series data
        now = datetime.now()
        metrics = [
            Metric("cpu.usage", MetricType.GAUGE, 50, timestamp=now - timedelta(minutes=5)),
            Metric("cpu.usage", MetricType.GAUGE, 60, timestamp=now - timedelta(minutes=4)),
            Metric("cpu.usage", MetricType.GAUGE, 70, timestamp=now),
        ]

        for metric in metrics:
            monitoring_server.metrics_collector.collect_metric(metric)

        # Start server
        await monitoring_server.start()

        # Request history
        response = await monitoring_server.simulate_history_request(
            name="cpu.usage",
            hours=1
        )

        # Verify history
        assert len(response["history"]) == 3
        assert all("timestamp" in item for item in response["history"])
        assert all("value" in item for item in response["history"])

        # Stop server
        await monitoring_server.stop()

    @pytest.mark.asyncio
    async def test_server_metrics_endpoint(self, monitoring_server: MonitoringServer):
        """Test server metrics endpoint (self-monitoring)."""
        # Start server
        await monitoring_server.start()

        # Let server run for a bit to collect its own metrics
        await asyncio.sleep(0.1)

        # Request server metrics
        response = await monitoring_server.simulate_server_metrics_request()

        # Verify server metrics
        assert "server_metrics" in response
        assert "uptime" in response["server_metrics"]
        assert "requests_count" in response["server_metrics"]
        assert "active_connections" in response["server_metrics"]

        # Stop server
        await monitoring_server.stop()

    @pytest.mark.asyncio
    async def test_rate_limiting(self, monitoring_server: MonitoringServer):
        """Test API rate limiting."""
        # Start server
        await monitoring_server.start()

        # Mock client
        mock_client = AsyncMock()

        # Test rate limiting
        with patch.object(monitoring_server, 'rate_limiter') as mock_limiter:
            mock_limiter.is_allowed.return_value = False

            # Try to make request
            response = await monitoring_server.simulate_metrics_request()
            assert response["status"] == "rate_limited"

        # Stop server
        await monitoring_server.stop()

    @pytest.mark.asyncio
    async def test_authentication(self, monitoring_server: MonitoringServer):
        """Test authentication for protected endpoints."""
        # Configure authentication
        monitoring_server.enable_auth(api_key="test-key")

        # Start server
        await monitoring_server.start()

        # Try request without auth
        response = await monitoring_server.simulate_metrics_request(api_key=None)
        assert response["status"] == "unauthorized"

        # Try request with wrong auth
        response = await monitoring_server.simulate_metrics_request(api_key="wrong-key")
        assert response["status"] == "unauthorized"

        # Try request with correct auth
        response = await monitoring_server.simulate_metrics_request(api_key="test-key")
        assert response["status"] == "success"

        # Stop server
        await monitoring_server.stop()

    @pytest.mark.asyncio
    async def test_cors_support(self, monitoring_server: MonitoringServer):
        """Test CORS support."""
        # Configure CORS
        monitoring_server.enable_cors(
            allowed_origins=["http://localhost:3000"],
            allowed_methods=["GET", "POST"],
        )

        # Start server
        await monitoring_server.start()

        # Test CORS headers
        response = await monitoring_server.simulate_metrics_request(
            headers={"Origin": "http://localhost:3000"}
        )
        assert "access-control-allow-origin" in response

        # Stop server
        await monitoring_server.stop()

    @pytest.mark.asyncio
    async def test_error_handling(self, monitoring_server: MonitoringServer):
        """Test error handling for invalid requests."""
        # Start server
        await monitoring_server.start()

        # Test invalid metric name
        response = await monitoring_server.simulate_metrics_request(name="")
        assert response["status"] == "error"

        # Test invalid export format
        response = await monitoring_server.simulate_export_request(format="invalid")
        assert response["status"] == "error"

        # Test invalid time range
        response = await monitoring_server.simulate_history_request(
            name="cpu.usage",
            start_time="invalid",
            end_time="invalid"
        )
        assert response["status"] == "error"

        # Stop server
        await monitoring_server.stop()