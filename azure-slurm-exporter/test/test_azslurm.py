import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from prometheus_client import Gauge
from exporter.azslurm import Azslurm, AzslurmNotAvailException
from exporter.exporter import CommandFailedException, CommandTimedOutException


class TestAzslurmInitialize:

    @pytest.fixture
    def azslurm(self):
        """Create an Azslurm collector instance for testing."""
        return Azslurm(binary_path="/root/bin/azslurm", interval=300, timeout=120)

    @patch("exporter.util.is_file_binary")
    def test_initialize_success(self, mock_is_binary, azslurm):
        """Test successful initialization when binary exists."""
        mock_is_binary.return_value = True
        azslurm.initialize()
        mock_is_binary.assert_called_once_with("/root/bin/azslurm")

    @patch("exporter.util.is_file_binary")
    def test_initialize_failure(self, mock_is_binary, azslurm):
        """Test initialization fails when binary is not available."""
        mock_is_binary.return_value = False
        with pytest.raises(AzslurmNotAvailException):
            azslurm.initialize()


class TestAzslurmExportMetrics:

    @pytest.fixture
    def azslurm(self):
        """Create an Azslurm collector instance for testing."""
        return Azslurm(binary_path="/root/bin/azslurm", interval=300, timeout=120)

    def test_export_metrics(self, azslurm):
        """Test export_metrics returns cached metrics."""
        azslurm.cached_output["azslurm_metrics"] = ["metric1", "metric2"]
        metrics = azslurm.export_metrics()
        assert metrics == ["metric1", "metric2"]


class TestAzslurmParseOutput:

    @pytest.fixture
    def azslurm(self):
        """Create an Azslurm collector instance for testing."""
        return Azslurm(binary_path="/root/bin/azslurm", interval=300, timeout=120)

    def test_parse_partitions(self, azslurm):
        """Test _parse_partitions correctly parses partition output."""
        stdout = b"PartitionName=part1\nNodename=node[1-5]\nPartitionName=part2\nNodename=node[6-10]"
        result = azslurm._parse_partitions(stdout)
        assert result["part1"] == "node[1-5]"
        assert result["part2"] == "node[6-10]"

    def test_parse_partitions_empty(self, azslurm):
        """Test _parse_partitions handles empty output."""
        stdout = b""
        result = azslurm._parse_partitions(stdout)
        assert result == {}

    def test_parse_limits(self, azslurm):
        """Test _parse_limits correctly parses JSON limits output."""
        stdout = b'[{"nodearray":"na1","vm_size":"Standard_D2s_v3","available_count":"10","family_available_count":"15","regional_available_count":"20","ncpus":2,"ngpus":0,"memgb":"memory::4.00g"}]'
        result = list(azslurm._parse_limits(stdout))
        assert len(result) == 1
        assert result[0].nodearray == "na1"
        assert result[0].vm_size == "Standard_D2s_v3"
        assert result[0].available_count == "10"

    def test_parse_output(self, azslurm):
        """Test parse_output correctly combines partition and limits data."""
        partitions_stdout = b"PartitionName=part1\nNodename=node[1-5]"
        limits_stdout = b'[{"nodearray":"part1","vm_size":"Standard_D2s_v3","available_count":"10","family_available_count":"15","regional_available_count":"20","ncpus":2,"ngpus":0,"memgb":"memory::4.00g"}]'

        result = azslurm.parse_output(partitions_stdout, limits_stdout)
        assert len(result) == 1
        assert isinstance(result[0], Gauge)
        assert result[0].describe()[0].name == "azslurm_partition_info"
        metric = result[0].collect()
        samples_by_key = {
                (s.labels['partition'],s.labels["vm_size"], s.labels["azure_count"], s.labels["nodelist"], s.labels["ncpus"], s.labels["ngpus"], s.labels["memory_gib"]): s.value
                for s in metric[0].samples
        }
        assert samples_by_key["part1","Standard_D2s_v3","15","node[1-5]","2","0","4.00"] == 10


class TestAzslurmQuery:

    @pytest.fixture
    def azslurm(self):
        """Create an Azslurm collector instance for testing."""
        return Azslurm(binary_path="/root/bin/azslurm", interval=300, timeout=120)

    @pytest.mark.asyncio
    @patch.object(Azslurm, "run_command", new_callable=AsyncMock)
    async def test_azslurm_query_success(self, mock_run, azslurm):
        """Test successful azslurm query returns partition info metrics."""
        proc_mock = MagicMock()
        proc_mock.stdout = b"PartitionName=part1\nNodename=node[1-5]"
        mock_run.return_value = proc_mock

        mock_run.side_effect = [
            MagicMock(stdout=b"PartitionName=part1\nNodename=node[1-5]"),
            MagicMock(stdout=b'[{"nodearray":"part1","vm_size":"Standard_D2s_v3","available_count":"10","family_available_count":"15","regional_available_count":"20","ncpus":2,"ngpus":0,"memgb":"memory::4.00g"}]')
        ]

        await azslurm.azslurm_query()
        assert len(azslurm.cached_output["azslurm_metrics"]) > 0
        assert azslurm.cached_output["azslurm_metrics"][0].describe()[0].name == "azslurm_partition_info"
        metric = azslurm.cached_output["azslurm_metrics"][0].collect()
        samples_by_key = {
                (s.labels['partition'],s.labels["vm_size"], s.labels["azure_count"], s.labels["nodelist"], s.labels["ncpus"], s.labels["ngpus"], s.labels["memory_gib"]): s.value
                for s in metric[0].samples
        }
        assert samples_by_key["part1","Standard_D2s_v3","15","node[1-5]","2","0","4.00"] == 10

    @pytest.mark.asyncio
    @patch.object(Azslurm, "run_command", new_callable=AsyncMock)
    async def test_azslurm_query_exception(self, mock_run, azslurm):
        """Test azslurm query preserves cache on command failure."""
        azslurm.cached_output["azslurm_metrics"] = ["Some original Metric"]
        mock_run.side_effect = CommandFailedException("azslurm", 1, "error")
        await azslurm.azslurm_query()
        assert azslurm.cached_output["azslurm_metrics"] == ["Some original Metric"]

    @pytest.mark.asyncio
    @patch.object(Azslurm, "run_command", new_callable=AsyncMock)
    async def test_azslurm_query_timeout(self, mock_run, azslurm):
        """Test azslurm query preserves cache on timeout."""
        azslurm.cached_output["azslurm_metrics"] = ["Some original Metric"]
        mock_run.side_effect = CommandTimedOutException("azslurm", 120)
        await azslurm.azslurm_query()
        assert azslurm.cached_output["azslurm_metrics"] == ["Some original Metric"]

    @pytest.mark.asyncio
    @patch.object(Azslurm, "run_command", new_callable=AsyncMock)
    async def test_azslurm_query_limits_failure(self, mock_run, azslurm):
        """Test that if partitions succeeds but limits fails, cache doesn't change"""
        azslurm.cached_output["azslurm_metrics"] = ["Some original Metric"]
        mock_run.side_effect = [
            MagicMock(stdout=b"PartitionName=part1\nNodename=node[1-5]"),
            CommandFailedException("azslurm limits", 1, "error"),
        ]
        await azslurm.azslurm_query()
        assert azslurm.cached_output["azslurm_metrics"] == ["Some original Metric"]