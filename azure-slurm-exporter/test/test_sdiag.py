import pytest
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from prometheus_client import Gauge
from exporter.sdiag import Sdiag, SdiagNotAvailException
from exporter.exporter import CommandFailedException, CommandTimedOutException
import json


class TestSdiagInitialize:

    @pytest.fixture
    def sdiag_collector(self):
        """Create a Sdiag collector instance for testing."""
        return Sdiag(binary_path="/usr/bin/sdiag", interval=300, timeout=30)

    @patch("exporter.util.is_file_binary")
    def test_initialize_success(self, mock_is_file_binary, sdiag_collector):
        """Test successful initialization"""
        mock_is_file_binary.return_value = True
        sdiag_collector.initialize()
        mock_is_file_binary.assert_called_once_with("/usr/bin/sdiag")

    @patch("exporter.util.is_file_binary")
    def test_initialize_failure(self, mock_is_file_binary, sdiag_collector):
        """Test initialization fails when binary is not available"""
        mock_is_file_binary.return_value = False
        with pytest.raises(SdiagNotAvailException):
            sdiag_collector.initialize()


class TestSdiagParseOutput:

    @pytest.fixture
    def sdiag_collector(self):
        """Create a Sdiag collector instance for testing."""
        return Sdiag(binary_path="/usr/bin/sdiag", interval=300, timeout=30)

    def _samples_by_name(self, metrics):
        """Collect prometheus samples from a list of Gauge metrics, keyed by metric name."""
        samples_by_name = {}
        for metric in metrics:
            for family in metric.collect():
                samples_by_name.setdefault(family.name, []).extend(family.samples)
        return samples_by_name

    def _scalar_value(self, samples_by_name, name):
        samples = samples_by_name[name]
        assert len(samples) == 1, f"Expected single sample for {name}, got {samples}"
        return samples[0].value

    def _labeled_values(self, samples_by_name, name, label):
        return {s.labels[label]: s.value for s in samples_by_name[name]}

    def test_parse_output_basic_metrics(self, sdiag_collector):
        """Test parse_output correctly parses basic scheduler metrics"""
        sdiag_json = {
            "statistics": {
                "server_thread_count": 120,
                "agent_queue_size": 42,
                "dbd_agent_queue_size": 8
            }
        }
        stdout = json.dumps(sdiag_json).encode()

        metrics = sdiag_collector.parse_output(stdout)

        assert len(metrics) == 3
        samples = self._samples_by_name(metrics)
        assert self._scalar_value(samples, "sdiag_server_thread_count") == 120
        assert self._scalar_value(samples, "sdiag_agent_queue_size") == 42
        assert self._scalar_value(samples, "sdiag_dbd_agent_queue_size") == 8

    def test_parse_output_scheduling_metrics(self, sdiag_collector):
        """Test parse_output correctly parses main scheduling cycle metrics"""
        sdiag_json = {
            "statistics": {
                "schedule_cycle_last": 125000,
                "schedule_cycle_max": 500000,
                "schedule_cycle_mean": 150000,
                "schedule_cycle_mean_depth": 42
            }
        }
        stdout = json.dumps(sdiag_json).encode()

        metrics = sdiag_collector.parse_output(stdout)

        assert len(metrics) == 2
        samples = self._samples_by_name(metrics)

        cycle_values = self._labeled_values(samples, "sdiag_main_cycle_time_us", "type")
        assert cycle_values == {"last": 125000, "max": 500000, "mean": 150000}
        assert self._scalar_value(samples, "sdiag_main_mean_depth_cycle") == 42

    def test_parse_output_scheduling_metrics_partial(self, sdiag_collector):
        """Only emit cycle-time label series that are present in the JSON."""
        sdiag_json = {
            "statistics": {
                "schedule_cycle_last": 1000,
                "schedule_cycle_mean": 2000,
            }
        }
        stdout = json.dumps(sdiag_json).encode()

        metrics = sdiag_collector.parse_output(stdout)

        samples = self._samples_by_name(metrics)
        cycle_values = self._labeled_values(samples, "sdiag_main_cycle_time_us", "type")
        assert cycle_values == {"last": 1000, "mean": 2000}
        assert "max" not in cycle_values

    def test_parse_output_comprehensive(self, sdiag_collector):
        """Test parse_output with comprehensive real-world sdiag output"""
        sdiag_json = {
            "statistics": {
                "server_thread_count": 204,
                "agent_queue_size": 1248,
                "dbd_agent_queue_size": 3421,
                "schedule_cycle_last": 387000,
                "schedule_cycle_max": 1124000,
                "schedule_cycle_mean": 342000,
                "schedule_cycle_mean_depth": 125
            }
        }
        stdout = json.dumps(sdiag_json).encode()

        metrics = sdiag_collector.parse_output(stdout)

        assert len(metrics) == 5
        samples = self._samples_by_name(metrics)

        assert self._scalar_value(samples, "sdiag_server_thread_count") == 204
        assert self._scalar_value(samples, "sdiag_agent_queue_size") == 1248
        assert self._scalar_value(samples, "sdiag_dbd_agent_queue_size") == 3421
        assert self._scalar_value(samples, "sdiag_main_mean_depth_cycle") == 125

        cycle_values = self._labeled_values(samples, "sdiag_main_cycle_time_us", "type")
        assert cycle_values == {"last": 387000, "max": 1124000, "mean": 342000}

    def test_parse_output_empty(self, sdiag_collector):
        """Test parse_output with empty statistics"""
        sdiag_json = {"statistics": {}}
        stdout = json.dumps(sdiag_json).encode()

        metrics = sdiag_collector.parse_output(stdout)

        assert metrics == []

    def test_parse_output_invalid_json(self, sdiag_collector):
        """Test parse_output handles invalid JSON gracefully"""
        stdout = b"invalid json{{"

        metrics = sdiag_collector.parse_output(stdout)

        assert metrics == []

    def test_parse_output_missing_statistics_key(self, sdiag_collector):
        """Test parse_output handles missing statistics key"""
        sdiag_json = {"other_key": "value"}
        stdout = json.dumps(sdiag_json).encode()

        metrics = sdiag_collector.parse_output(stdout)

        assert metrics == []


class TestSdiagExportMetrics:

    @pytest.fixture
    def sdiag_collector(self):
        """Create a Sdiag collector instance for testing."""
        return Sdiag(binary_path="/usr/bin/sdiag", interval=300, timeout=30)

    def test_export_metrics(self, sdiag_collector):
        """Test export_metrics returns cached output"""
        mock_gauge = Mock(spec=Gauge)
        sdiag_collector.cached_output["sdiag_metrics"] = [mock_gauge]

        result = sdiag_collector.export_metrics()

        assert result == [mock_gauge]

    def test_export_metrics_empty(self, sdiag_collector):
        """Test export_metrics returns empty list when no metrics cached"""
        result = sdiag_collector.export_metrics()

        assert result == []


class TestSdiagQuery:

    @pytest.fixture
    def sdiag_collector(self):
        """Create a Sdiag collector instance for testing."""
        return Sdiag(binary_path="/usr/bin/sdiag", interval=300, timeout=30)

    @pytest.mark.asyncio
    @patch.object(Sdiag, "run_command", new_callable=AsyncMock)
    async def test_sdiag_query_success(self, mock_run, sdiag_collector):
        """Test successful sdiag_query execution"""
        sdiag_json = {
            "statistics": {
                "server_thread_count": 150,
                "agent_queue_size": 25
            }
        }
        mock_proc = MagicMock()
        mock_proc.stdout = json.dumps(sdiag_json).encode()
        mock_run.return_value = mock_proc

        await sdiag_collector.sdiag_query()

        mock_run.assert_called_once()
        assert len(sdiag_collector.cached_output["sdiag_metrics"]) == 2

    @pytest.mark.asyncio
    @patch.object(Sdiag, "run_command", new_callable=AsyncMock)
    async def test_sdiag_query_exception_preserves_cache(self, mock_run, sdiag_collector):
        """On command failure, previously cached metrics must be preserved."""
        sentinel = [Mock(spec=Gauge)]
        sdiag_collector.cached_output["sdiag_metrics"] = sentinel
        mock_run.side_effect = CommandFailedException("sdiag", 1, "error")

        # Should not raise exception
        await sdiag_collector.sdiag_query()

        assert sdiag_collector.cached_output["sdiag_metrics"] is sentinel

    @pytest.mark.asyncio
    @patch.object(Sdiag, "run_command", new_callable=AsyncMock)
    async def test_sdiag_query_timeout_preserves_cache(self, mock_run, sdiag_collector):
        """On timeout, previously cached metrics must be preserved."""
        sentinel = [Mock(spec=Gauge)]
        sdiag_collector.cached_output["sdiag_metrics"] = sentinel
        mock_run.side_effect = CommandTimedOutException("sdiag", 30)

        # Should not raise exception
        await sdiag_collector.sdiag_query()

        assert sdiag_collector.cached_output["sdiag_metrics"] is sentinel

    @pytest.mark.asyncio
    @patch.object(Sdiag, "run_command", new_callable=AsyncMock)
    async def test_sdiag_query_calls_with_json_flag(self, mock_run, sdiag_collector):
        """Test sdiag_query calls command with --json flag"""
        mock_proc = MagicMock()
        mock_proc.stdout = b'{"statistics": {}}'
        mock_run.return_value = mock_proc

        await sdiag_collector.sdiag_query()

        # Verify called with correct arguments
        call_args = mock_run.call_args[0]
        assert "/usr/bin/sdiag" in call_args
        assert "--json" in call_args
