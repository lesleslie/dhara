"""
Tests for metrics collection system in Dhara.

These tests verify the metrics collector functionality including:
- Metric collection from various sources
- Metric aggregation and processing
- Metrics storage and retrieval
- Metric export formats
"""

import pytest
import asyncio
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Dict, List, Any, Optional

from dhara.monitoring.metrics import MetricsCollector, Metric, MetricType, MetricValue
from dhara.storage.base import StorageBackend


class TestMetricsCollector:
    """Test metrics collector functionality."""

    @pytest.fixture
    def metrics_collector(self) -> MetricsCollector:
        """Create a metrics collector instance."""
        return MetricsCollector()

    @pytest.fixture
    def sample_metric(self) -> Metric:
        """Create a sample metric for testing."""
        return Metric(
            name="database.connections.active",
            metric_type=MetricType.COUNTER,
            value=45,
            timestamp=datetime.now(),
            metadata={
                "tenant_id": "test-tenant",
                "database": "primary",
                "region": "us-west",
            },
        )

    def test_metric_creation(self, sample_metric: Metric):
        """Test metric creation and validation."""
        # Verify metric properties
        assert sample_metric.name == "database.connections.active"
        assert sample_metric.metric_type == MetricType.COUNTER
        assert sample_metric.value == 45
        assert sample_metric.timestamp is not None
        assert "tenant_id" in sample_metric.metadata

    def test_metric_types(self):
        """Test different metric types."""
        # Test counter metric
        counter = Metric(
            name="requests.total",
            metric_type=MetricType.COUNTER,
            value=1000,
        )
        assert counter.metric_type == MetricType.COUNTER
        assert counter.value == 1000

        # Test gauge metric
        gauge = Metric(
            name="memory.usage.percent",
            metric_type=MetricType.GAUGE,
            value=75.5,
        )
        assert gauge.metric_type == MetricType.GAUGE
        assert gauge.value == 75.5

        # Test histogram metric
        histogram = Metric(
            name="request.duration",
            metric_type=MetricType.HISTOGRAM,
            value=150,
            metadata={"bucket": "100-200ms"},
        )
        assert histogram.metric_type == MetricType.HISTOGRAM
        assert histogram.value == 150

    @pytest.mark.asyncio
    async def test_collect_counter_metric(self, metrics_collector: MetricsCollector, sample_metric: Metric):
        """Test collecting counter metrics."""
        # Collect metric
        metrics_collector.collect_metric(sample_metric)

        # Verify collection
        metrics = metrics_collector.get_metrics(name="database.connections.active")
        assert len(metrics) == 1
        assert metrics[0].value == 45

    @pytest.mark.asyncio
    async def test_collect_gauge_metric(self, metrics_collector: MetricsCollector):
        """Test collecting gauge metrics."""
        # Create gauge metric
        gauge_metric = Metric(
            name="memory.usage.percent",
            metric_type=MetricType.GAUGE,
            value=75.5,
        )

        # Collect metric
        metrics_collector.collect_metric(gauge_metric)

        # Verify collection
        metrics = metrics_collector.get_metrics(name="memory.usage.percent")
        assert len(metrics) == 1
        assert metrics[0].value == 75.5

    @pytest.mark.asyncio
    async def test_collect_histogram_metric(self, metrics_collector: MetricsCollector):
        """Test collecting histogram metrics."""
        # Create histogram metrics
        histogram_metrics = [
            Metric("request.duration", MetricType.HISTOGRAM, 50, metadata={"bucket": "0-100ms"}),
            Metric("request.duration", MetricType.HISTOGRAM, 150, metadata={"bucket": "100-200ms"}),
            Metric("request.duration", MetricType.HISTOGRAM, 250, metadata={"bucket": "200-300ms"}),
        ]

        # Collect metrics
        for metric in histogram_metrics:
            metrics_collector.collect_metric(metric)

        # Verify collection
        metrics = metrics_collector.get_metrics(name="request.duration")
        assert len(metrics) == 3
        values = [m.value for m in metrics]
        assert 50 in values
        assert 150 in values
        assert 250 in values

    @pytest.mark.asyncio
    async def test_metric_aggregation(self, metrics_collector: MetricsCollector, sample_metric: Metric):
        """Test metric aggregation."""
        # Collect multiple metrics of the same type
        for i in range(5):
            metric = sample_metric.model_copy()
            metric.value = metric.value + i * 10
            metrics_collector.collect_metric(metric)

        # Aggregate metrics
        aggregated = metrics_collector.aggregate_metrics("database.connections.active")

        # Verify aggregation
        assert aggregated.count == 5
        assert aggregated.sum == 45 + 55 + 65 + 75 + 85  # 325
        assert aggregated.avg == 65.0  # 325 / 5

    @pytest.mark.asyncio
    async def test_metric_filtering(self, metrics_collector: MetricsCollector):
        """Test filtering metrics by various criteria."""
        # Collect different metrics
        metrics = [
            Metric("db.connections", MetricType.COUNTER, 10, metadata={"tenant": "tenant1", "db": "primary"}),
            Metric("db.connections", MetricType.COUNTER, 20, metadata={"tenant": "tenant2", "db": "primary"}),
            Metric("cpu.usage", MetricType.GAUGE, 75.5, metadata={"tenant": "tenant1", "region": "us-west"}),
            Metric("memory.usage", MetricType.GAUGE, 60.2, metadata={"tenant": "tenant2", "region": "us-east"}),
        ]

        for metric in metrics:
            metrics_collector.collect_metric(metric)

        # Filter by name
        db_metrics = metrics_collector.get_metrics(name="db.connections")
        assert len(db_metrics) == 2

        # Filter by type
        counter_metrics = metrics_collector.get_metrics(metric_type=MetricType.COUNTER)
        assert len(counter_metrics) == 2

        # Filter by metadata
        tenant1_metrics = metrics_collector.get_metrics(metadata={"tenant": "tenant1"})
        assert len(tenant1_metrics) == 2

    @pytest.mark.asyncio
    async def test_metric_time_range_filtering(self, metrics_collector: MetricsCollector):
        """Test filtering metrics by time range."""
        # Collect metrics at different times
        now = datetime.now()
        metrics = [
            Metric("metric1", MetricType.COUNTER, 10, timestamp=now - timedelta(minutes=5)),
            Metric("metric1", MetricType.COUNTER, 20, timestamp=now - timedelta(minutes=4)),
            Metric("metric1", MetricType.COUNTER, 30, timestamp=now - timedelta(minutes=3)),
            Metric("metric1", MetricType.COUNTER, 40, timestamp=now - timedelta(minutes=2)),
            Metric("metric1", MetricType.COUNTER, 50, timestamp=now),
        ]

        for metric in metrics:
            metrics_collector.collect_metric(metric)

        # Filter by time range
        start_time = now - timedelta(minutes=3)
        end_time = now - timedelta(minutes=1)

        filtered_metrics = metrics_collector.get_metrics(
            name="metric1",
            start_time=start_time,
            end_time=end_time,
        )

        # Should have metrics from minutes 2 and 3
        assert len(filtered_metrics) == 2
        values = [m.value for m in filtered_metrics]
        assert 40 in values  # minute 2
        assert 30 in values  # minute 3

    @pytest.mark.asyncio
    async def test_metric_ttl_expiration(self, metrics_collector: MetricsCollector, sample_metric: Metric):
        """Test metric TTL expiration."""
        # Collect metric with TTL
        metric_with_ttl = sample_metric.model_copy()
        metric_with_ttl.ttl_seconds = 60  # 1 minute TTL
        metrics_collector.collect_metric(metric_with_ttl)

        # Verify metric is there initially
        metrics = metrics_collector.get_metrics(name="database.connections.active")
        assert len(metrics) == 1

        # Simulate time passing
        with patch('dhara.monitoring.metrics.datetime') as mock_dt:
            mock_dt.now.return_value = datetime.now() + timedelta(minutes=2)
            metrics_collector.cleanup_expired_metrics()

        # Verify metric was expired
        metrics = metrics_collector.get_metrics(name="database.connections.active")
        assert len(metrics) == 0

    @pytest.mark.asyncio
    async def test_metric_export_prometheus(self, metrics_collector: MetricsCollector):
        """Test exporting metrics in Prometheus format."""
        # Collect some metrics
        metrics = [
            Metric("requests_total", MetricType.COUNTER, 1000),
            Metric("response_time_seconds", MetricType.HISTOGRAM, 0.5),
            Metric("memory_usage_bytes", MetricType.GAUGE, 1024 * 1024 * 500),
        ]

        for metric in metrics:
            metrics_collector.collect_metric(metric)

        # Export to Prometheus format
        prometheus_text = metrics_collector.export_prometheus()

        # Verify format
        assert "requests_total" in prometheus_text
        assert "response_time_seconds" in prometheus_text
        assert "memory_usage_bytes" in prometheus_text
        assert "TYPE" in prometheus_text  # Prometheus type declarations
        assert HELP in prometheus_text  # Help text

    @pytest.mark.asyncio
    async def test_metric_export_json(self, metrics_collector: MetricsCollector):
        """Test exporting metrics in JSON format."""
        # Collect some metrics
        metrics = [
            Metric("requests_total", MetricType.COUNTER, 1000),
            Metric("memory_usage_bytes", MetricType.GAUGE, 1024 * 1024 * 500),
        ]

        for metric in metrics:
            metrics_collector.collect_metric(metric)

        # Export to JSON format
        json_data = metrics_collector.export_json()

        # Verify format
        assert isinstance(json_data, list)
        assert len(json_data) == 2

        # Verify structure
        for metric in json_data:
            assert "name" in metric
            assert "type" in metric
            assert "value" in metric
            assert "timestamp" in metric

    @pytest.mark.asyncio
    async def test_metric_export_influxdb(self, metrics_collector: MetricsCollector):
        """Test exporting metrics in InfluxDB line protocol format."""
        # Collect some metrics with metadata
        metric = Metric(
            name="cpu_usage",
            metric_type=MetricType.GAUGE,
            value=75.5,
            metadata={
                "host": "server1",
                "region": "us-west",
            },
        )
        metrics_collector.collect_metric(metric)

        # Export to InfluxDB format
        influx_lines = metrics_collector.export_influxdb()

        # Verify format
        assert len(influx_lines) == 1
        line = influx_lines[0]
        assert "cpu_usage" in line
        assert "75.5" in line
        assert "host=server1" in line
        assert "region=us-west" in line

    @pytest.mark.asyncio
    async def test_metric_storage_integration(self, metrics_collector: MetricsCollector):
        """Test integration with storage backend."""
        # Mock storage backend
        mock_storage = AsyncMock(spec=StorageBackend)

        # Configure storage
        metrics_collector.set_storage_backend(mock_storage)

        # Collect metrics
        metric = Metric("test.metric", MetricType.COUNTER, 100)
        metrics_collector.collect_metric(metric)

        # Persist metrics
        await metrics_collector.persist_metrics()

        # Verify storage was called
        mock_storage.put.assert_called()

    @pytest.mark.asyncio
    async def test_metric_batch_processing(self, metrics_collector: MetricsCollector):
        """Test processing metrics in batches."""
        # Collect many metrics
        metrics = []
        for i in range(100):
            metric = Metric(f"metric.{i}", MetricType.COUNTER, i)
            metrics.append(metric)
            metrics_collector.collect_metric(metric)

        # Process metrics in batches
        batch_results = await metrics_collector.process_metrics_batch(
            batch_size=10,
            process_func=lambda metrics: {"count": len(metrics)}
        )

        # Verify batch processing
        assert len(batch_results) == 10  # 100 metrics / 10 per batch
        assert all("count" in result for result in batch_results)
        assert all(result["count"] == 10 for result in batch_results)

    @pytest.mark.asyncio
    async def test_metric_rate_calculation(self, metrics_collector: MetricsCollector):
        """Test calculating metric rates."""
        # Collect time series data
        now = datetime.now()
        metrics = [
            Metric("requests", MetricType.COUNTER, 100, timestamp=now - timedelta(seconds=60)),
            Metric("requests", MetricType.COUNTER, 200, timestamp=now - timedelta(seconds=30)),
            Metric("requests", MetricType.COUNTER, 300, timestamp=now),
        ]

        for metric in metrics:
            metrics_collector.collect_metric(metric)

        # Calculate rates
        rates = metrics_collector.calculate_rates("requests", time_window_seconds=60)

        # Verify rates
        assert len(rates) == 2  # 2 intervals
        assert rates[0]["value"] == 100 / 30  # (200-100)/30s
        assert rates[1]["value"] == 100 / 30  # (300-200)/30s

    @pytest.mark.asyncio
    async def test_metric_percentiles(self, metrics_collector: MetricsCollector):
        """Test calculating metric percentiles."""
        # Collect histogram data
        metrics = [
            Metric("response_time", MetricType.HISTOGRAM, 100),
            Metric("response_time", MetricType.HISTOGRAM, 200),
            Metric("response_time", MetricType.HISTOGRAM, 300),
            Metric("response_time", MetricType.HISTOGRAM, 400),
            Metric("response_time", MetricType.HISTOGRAM, 500),
        ]

        for metric in metrics:
            metrics_collector.collect_metric(metric)

        # Calculate percentiles
        percentiles = metrics_collector.calculate_percentiles("response_time", [50, 90, 95, 99])

        # Verify percentiles
        assert len(percentiles) == 4
        assert percentiles[50] == 300  # Median
        assert percentiles[90] == 500  # 90th percentile

    @pytest.mark.asyncio
    async def test_metric_anomaly_detection(self, metrics_collector: MetricsCollector):
        """Test detecting metric anomalies."""
        # Collect normal metrics
        for i in range(10):
            metric = Metric("cpu_usage", MetricType.GAUGE, 50 + i)
            metrics_collector.collect_metric(metric)

        # Collect anomalous metric
        anomalous_metric = Metric("cpu_usage", MetricType.GAUGE, 200)  # Spike
        metrics_collector.collect_metric(anomalous_metric)

        # Detect anomalies
        anomalies = metrics_collector.detect_anomalies(
            "cpu_usage",
            z_threshold=3,  # 3 standard deviations
        )

        # Verify anomaly detection
        assert len(anomalies) == 1
        assert anomalies[0].value == 200
        assert anomalies[0].anomaly_score > 0

    @pytest.mark.asyncio
    async def test_metric_concurrent_collection(self, metrics_collector: MetricsCollector):
        """Test concurrent metric collection."""
        async def collect_metrics(task_id):
            for i in range(10):
                metric = Metric(f"metric.{task_id}", MetricType.COUNTER, i)
                metrics_collector.collect_metric(metric)

        # Collect metrics concurrently
        tasks = [collect_metrics(i) for i in range(5)]
        await asyncio.gather(*tasks)

        # Verify all metrics were collected
        total_metrics = 0
        for i in range(5):
            metrics = metrics_collector.get_metrics(name=f"metric.{i}")
            total_metrics += len(metrics)

        assert total_metrics == 50  # 5 tasks * 10 metrics each

    @pytest.mark.asyncio
    async def test_metric_cleanup(self, metrics_collector: MetricsCollector):
        """Test cleaning up old metrics."""
        # Collect metrics
        now = datetime.now()
        old_time = now - timedelta(days=2)
        metrics = [
            Metric("metric1", MetricType.COUNTER, 10, timestamp=now),
            Metric("metric2", MetricType.COUNTER, 20, timestamp=old_time),
        ]

        for metric in metrics:
            metrics_collector.collect_metric(metric)

        # Clean up old metrics
        deleted_count = metrics_collector.cleanup_old_metrics(days=1)

        # Verify cleanup
        assert deleted_count == 1
        metrics = metrics_collector.get_metrics()
        assert len(metrics) == 1
        assert metrics[0].name == "metric1"