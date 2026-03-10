import pytest
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from prometheus_client import Gauge
from exporter.sinfo import Sinfo, SinfoNotAvailException
import logging

class TestSinfo:

    @pytest.fixture
    def sinfo_collector(self):
        """Create a Sinfo collector instance for testing"""
        return Sinfo(binary_path="/usr/bin/sinfo", interval=30, timeout=15)

    @patch("exporter.util.is_file_binary")
    def test_initialize_success(self, mock_is_file_binary, sinfo_collector):
        """Test successful initialization"""
        mock_is_file_binary.return_value = True
        sinfo_collector.initialize()
        mock_is_file_binary.assert_called_once_with("/usr/bin/sinfo")

    @patch("exporter.util.is_file_binary")
    def test_initialize_failure(self, mock_is_file_binary, sinfo_collector):
        """Test initialization fails when binary is not available"""
        mock_is_file_binary.return_value = False
        with pytest.raises(SinfoNotAvailException):
            sinfo_collector.initialize()

    def test_normalize_state_with_suffix(self, sinfo_collector):
        """Test normalize_state removes suffix and returns mapped state"""
        assert sinfo_collector.normalize_state("idle*") == "not_responding"
        assert sinfo_collector.normalize_state("allocated~") == "powered_off"
        assert sinfo_collector.normalize_state("down#") == "powering_up"

    def test_normalize_state_without_suffix(self, sinfo_collector):
        """Test normalize_state returns original state when no suffix"""
        assert sinfo_collector.normalize_state("idle") == "idle"
        assert sinfo_collector.normalize_state("allocated") == "allocated"

    def test_parse_output(self, sinfo_collector):
        """Test parse_output correctly parses sinfo command output"""
        stdout = b"node[01-02]|2|partition1|None|idle\nnode03|1|partition2|down|down*"

        metrics = sinfo_collector.parse_output(stdout)

        assert len(metrics) == 1
        assert isinstance(metrics[0], Gauge)
        assert metrics[0]._name == "sinfo_partition_nodes_state"
        metric = metrics[0].collect()
        samples_by_key = {
                (s.labels['node_list'],s.labels["partition"], s.labels["state"], s.labels["reason"]): s.value
                for s in metric[0].samples
        }
        assert samples_by_key["node[01-02]","partition1","idle","None"] == 2
        assert samples_by_key["node03","partition2","not_responding","down"] == 1
    def test_parse_output_empty(self, sinfo_collector):
        """Test parse_output with empty output"""
        stdout = b""

        metrics = sinfo_collector.parse_output(stdout)

        assert len(metrics) == 1
        assert isinstance(metrics[0], Gauge)

    def test_parse_output_with_normalized_states(self, sinfo_collector):
        """Test parse_output normalizes state suffixes"""
        stdout = b"node01|1|partition1|reason|idle*\nnode02|1|partition1|None|allocated~"

        metrics = sinfo_collector.parse_output(stdout)

        assert len(metrics) == 1
        assert isinstance(metrics[0], Gauge)
        assert metrics[0]._name == "sinfo_partition_nodes_state"
        metric = metrics[0].collect()
        samples_by_key = {
                (s.labels['node_list'],s.labels["partition"], s.labels["state"], s.labels["reason"]): s.value
                for s in metric[0].samples
        }
        assert samples_by_key["node01","partition1","not_responding","reason"] == 1
        assert samples_by_key["node02","partition1","powered_off","None"] == 1

    def test_export_metrics(self, sinfo_collector):
        """Test export_metrics returns cached output"""
        mock_gauge = Mock(spec=Gauge)
        sinfo_collector.cached_output["sinfo_query"] = [mock_gauge]

        result = sinfo_collector.export_metrics()

        assert result == [mock_gauge]

    @pytest.mark.asyncio
    async def test_sinfo_query_success(self, sinfo_collector):
        """Test successful sinfo_query execution"""
        mock_proc = Mock()
        mock_proc.stdout = b"node01|1|partition1|None|idle"

        sinfo_collector.run_command = AsyncMock(return_value=mock_proc)

        await sinfo_collector.sinfo_query()

        sinfo_collector.run_command.assert_called_once()
        assert len(sinfo_collector.cached_output["sinfo_query"]) == 1
        metric = sinfo_collector.cached_output["sinfo_query"][0].collect()
        samples_by_key = {
                (s.labels['node_list'],s.labels["partition"], s.labels["state"], s.labels["reason"]): s.value
                for s in metric[0].samples
        }
        assert samples_by_key["node01","partition1","idle","None"] == 1

    @pytest.mark.asyncio
    async def test_sinfo_query_exception(self, sinfo_collector):
        """Test sinfo_query handles exceptions gracefully"""
        sinfo_collector.run_command = AsyncMock(side_effect=Exception("Command failed"))

        # Should not raise exception
        await sinfo_collector.sinfo_query()

        assert sinfo_collector.cached_output["sinfo_query"] == []
