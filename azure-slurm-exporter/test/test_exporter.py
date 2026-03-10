import pytest
import asyncio
import sys
from unittest.mock import Mock, MagicMock, patch, AsyncMock, call
from exporter.exporter import main, CompositeCollector, NoCollectorsFoundException, HTTPServerFailedException
from prometheus_client import Gauge, Counter

class TestCompositeCollectorExportMetrics:
    """Tests for CompositeCollector.export_metrics()"""

    def test_export_metrics_single_collector(self):
        """Test export_metrics yields metrics from a single collector"""
        gauge = Gauge("test_metric", "A test metric", registry=None)
        mock_collector = MagicMock()
        mock_collector.export_metrics.return_value = [gauge]

        composite = CompositeCollector()
        composite.collectors = [mock_collector]

        result = list(composite.export_metrics())
        assert result == [gauge]
        mock_collector.export_metrics.assert_called_once()

    def test_export_metrics_multiple_collectors(self):
        """Test export_metrics yields metrics from all collectors"""
        gauge1 = Gauge("test_metric_1", "First test metric", registry=None)
        gauge2 = Gauge("test_metric_2", "Second test metric", registry=None)
        counter1 = Counter("test_counter_1", "A test counter", registry=None)

        collector_a = MagicMock()
        collector_a.export_metrics.return_value = [gauge1, gauge2]

        collector_b = MagicMock()
        collector_b.export_metrics.return_value = [counter1]

        composite = CompositeCollector()
        composite.collectors = [collector_a, collector_b]

        result = list(composite.export_metrics())
        assert result == [gauge1, gauge2, counter1]

    def test_export_metrics_no_collectors(self):
        """Test export_metrics yields nothing when no collectors are registered"""
        composite = CompositeCollector()
        composite.collectors = []

        result = list(composite.export_metrics())
        assert result == []

    def test_export_metrics_collector_returns_empty(self):
        """Test export_metrics handles collectors that return no metrics"""
        mock_collector = MagicMock()
        mock_collector.export_metrics.return_value = []

        composite = CompositeCollector()
        composite.collectors = [mock_collector]

        result = list(composite.export_metrics())
        assert result == []


class TestCompositeCollectorCollect:
    """Tests for CompositeCollector.collect()"""

    def test_collect_yields_prometheus_metrics(self):
        """Test collect() yields Metric objects from underlying Prometheus metric types"""
        gauge = Gauge("collect_test_gauge", "A test gauge", ["label"], registry=None)
        gauge.labels(label="value1").set(42)

        mock_collector = MagicMock()
        mock_collector.export_metrics.return_value = [gauge]

        composite = CompositeCollector()
        composite.collectors = [mock_collector]

        result = list(composite.collect())
        assert len(result) > 0
        # Each yielded item should be a Prometheus Metric object
        from prometheus_client.metrics_core import Metric
        for metric in result:
            assert isinstance(metric, Metric)

    def test_collect_multiple_metric_types(self):
        """Test collect() works with mixed Gauge and Counter metrics"""
        gauge = Gauge("collect_gauge", "A gauge", registry=None)
        gauge.set(10)
        counter = Counter("collect_counter", "A counter", registry=None)
        counter.inc(5)

        collector_a = MagicMock()
        collector_a.export_metrics.return_value = [gauge]

        collector_b = MagicMock()
        collector_b.export_metrics.return_value = [counter]

        composite = CompositeCollector()
        composite.collectors = [collector_a, collector_b]

        result = list(composite.collect())
        metric_names = [m.name for m in result]
        assert "collect_gauge" in metric_names
        assert "collect_counter" in metric_names

    def test_collect_no_collectors(self):
        """Test collect() yields nothing when no collectors exist"""
        composite = CompositeCollector()
        composite.collectors = []

        result = list(composite.collect())
        assert result == []

    def test_collect_is_iterator(self):
        """Test collect() returns an iterator, not a list"""
        composite = CompositeCollector()
        composite.collectors = []

        result = composite.collect()
        assert hasattr(result, '__iter__')
        assert hasattr(result, '__next__')
        
@pytest.mark.asyncio
async def test_main_success():
    """Test main function successfully initializes and starts HTTP server"""
    mock_runner = AsyncMock()
    mock_collector = MagicMock(spec=CompositeCollector)
    mock_collector.start_http_server = AsyncMock(return_value=mock_runner)
    mock_collector.initialize_collectors = Mock()

    with patch('exporter.exporter.argparse.ArgumentParser') as mock_parser_class, \
         patch('exporter.exporter.logging.config.fileConfig'), \
         patch('exporter.exporter.CompositeCollector', return_value=mock_collector), \
         patch('exporter.exporter.asyncio.get_running_loop') as mock_loop, \
         patch('sys.argv', ['exporter.py', '--port', '9101', '--host', '127.0.0.1']):

        mock_loop_instance = MagicMock()
        mock_loop_instance.add_signal_handler = Mock()
        mock_loop.return_value = mock_loop_instance

        mock_parser = MagicMock()
        mock_parser_class.return_value = mock_parser
        mock_args = MagicMock()
        mock_args.port = 9101
        mock_args.host = '127.0.0.1'
        mock_parser.parse_args.return_value = mock_args

        stop_event = asyncio.Event()
        stop_event.set()
        with patch('exporter.exporter.asyncio.Event', return_value=stop_event):
            await main()

        mock_collector.initialize_collectors.assert_called_once()
        mock_collector.start_http_server.assert_called_once_with(host='127.0.0.1', port=9101)
        mock_runner.cleanup.assert_awaited_once()


@pytest.mark.asyncio
async def test_main_no_collectors_found():
    """Test main exits when no collectors are initialized"""
    mock_collector = MagicMock(spec=CompositeCollector)
    mock_collector.initialize_collectors = Mock(side_effect=NoCollectorsFoundException())

    stop_event = asyncio.Event()
    stop_event.set()
    with patch('exporter.exporter.argparse.ArgumentParser'), \
         patch('exporter.exporter.logging.config.fileConfig'), \
         patch('exporter.exporter.CompositeCollector', return_value=mock_collector), \
         patch('exporter.exporter.asyncio.get_running_loop'), \
         patch('exporter.exporter.asyncio.Event', return_value=stop_event), \
         patch('sys.argv', ['exporter.py']), \
         patch('sys.exit') as mock_exit:

        await main()
        mock_exit.assert_called_once_with(1)


@pytest.mark.asyncio
async def test_main_http_server_failed():
    """Test main exits when HTTP server fails to start"""
    mock_collector = MagicMock(spec=CompositeCollector)
    mock_collector.initialize_collectors = Mock()
    mock_collector.start_http_server = AsyncMock(side_effect=HTTPServerFailedException())

    stop_event = asyncio.Event()
    stop_event.set()
    with patch('exporter.exporter.argparse.ArgumentParser'), \
         patch('exporter.exporter.logging.config.fileConfig'), \
         patch('exporter.exporter.CompositeCollector', return_value=mock_collector), \
         patch('exporter.exporter.asyncio.get_running_loop'), \
         patch('exporter.exporter.asyncio.Event', return_value=stop_event), \
         patch('sys.argv', ['exporter.py']), \
         patch('sys.exit') as mock_exit:

        await main()
        mock_exit.assert_called_once_with(1)


@pytest.mark.asyncio
async def test_main_custom_port_and_host():
    """Test main uses custom port and host from arguments"""
    mock_runner = AsyncMock()
    mock_collector = MagicMock(spec=CompositeCollector)
    mock_collector.start_http_server = AsyncMock(return_value=mock_runner)
    mock_collector.initialize_collectors = Mock()

    with patch('exporter.exporter.argparse.ArgumentParser') as mock_parser_class, \
         patch('exporter.exporter.logging.config.fileConfig'), \
         patch('exporter.exporter.CompositeCollector', return_value=mock_collector), \
         patch('exporter.exporter.asyncio.get_running_loop') as mock_loop, \
         patch('sys.argv', ['exporter.py', '--port', '8080', '--host', '0.0.0.0']):

        mock_loop_instance = MagicMock()
        mock_loop_instance.add_signal_handler = Mock()
        mock_loop.return_value = mock_loop_instance

        mock_parser = MagicMock()
        mock_parser_class.return_value = mock_parser
        mock_args = MagicMock()
        mock_args.port = 8080
        mock_args.host = '0.0.0.0'
        mock_parser.parse_args.return_value = mock_args

        stop_event = asyncio.Event()
        stop_event.set()
        with patch('exporter.exporter.asyncio.Event', return_value=stop_event):
            await main()

        mock_collector.start_http_server.assert_called_once_with(host='0.0.0.0', port=8080)

