import pytest
from unittest.mock import Mock, patch, AsyncMock, MagicMock
from prometheus_client import Gauge
from exporter.azslurm import Azslurm, AzslurmNotAvailException

class TestAzslurm:

    @pytest.fixture
    def azslurm(self):
        return Azslurm(binary_path="/root/bin/azslurm", interval=300, timeout=120)

    @patch('exporter.util.is_file_binary')
    def test_initialize_success(self, mock_is_binary, azslurm):
        mock_is_binary.return_value = True
        azslurm.initialize()
        mock_is_binary.assert_called_once_with("/root/bin/azslurm")

    @patch('exporter.util.is_file_binary')
    def test_initialize_failure(self, mock_is_binary, azslurm):
        mock_is_binary.return_value = False
        with pytest.raises(AzslurmNotAvailException):
            azslurm.initialize()

    def test_export_metrics(self, azslurm):
        azslurm.cached_output["azslurm_metrics"] = ["metric1", "metric2"]
        metrics = azslurm.export_metrics()
        assert metrics == ["metric1", "metric2"]

    def test_parse_partitions(self, azslurm):
        stdout = b"PartitionName=part1\nNodename=node[1-5]\nPartitionName=part2\nNodename=node[6-10]"
        result = azslurm._parse_partitions(stdout)
        assert result["part1"] == "node[1-5]"
        assert result["part2"] == "node[6-10]"

    def test_parse_partitions_empty(self, azslurm):
        stdout = b""
        result = azslurm._parse_partitions(stdout)
        assert result == {}

    def test_parse_limits(self, azslurm):
        stdout = b'[{"nodearray":"na1","vm_size":"Standard_D2s_v3","available_count":"10","family_available_count":"15","regional_available_count":"20"}]'
        result = list(azslurm._parse_limits(stdout))
        assert len(result) == 1
        assert result[0].nodearray == "na1"
        assert result[0].vm_size == "Standard_D2s_v3"
        assert result[0].available_count == "10"

    def test_parse_output(self, azslurm):
        partitions_stdout = b"PartitionName=part1\nNodename=node[1-5]"
        limits_stdout = b'[{"nodearray":"part1","vm_size":"Standard_D2s_v3","available_count":"10","family_available_count":"15","regional_available_count":"20"}]'

        result = azslurm.parse_output(partitions_stdout, limits_stdout)
        assert len(result) == 1
        assert isinstance(result[0], Gauge)
        assert result[0].describe()[0].name == "azslurm_partition_info"
        metric = result[0].collect()
        samples_by_key = {
                (s.labels['partition'],s.labels["vm_size"], s.labels["azure_count"], s.labels["nodelist"]): s.value
                for s in metric[0].samples
        }
        assert samples_by_key["part1","Standard_D2s_v3","15","node[1-5]"] == 10
        
    @patch.object(Azslurm, 'run_command', new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_azslurm_query_success(self, mock_run, azslurm):
        proc_mock = MagicMock()
        proc_mock.stdout = b"PartitionName=part1\nNodename=node[1-5]"
        mock_run.return_value = proc_mock

        mock_run.side_effect = [
            MagicMock(stdout=b"PartitionName=part1\nNodename=node[1-5]"),
            MagicMock(stdout=b'[{"nodearray":"part1","vm_size":"Standard_D2s_v3","available_count":"10","family_available_count":"15","regional_available_count":"20"}]')
        ]

        await azslurm.azslurm_query()
        assert len(azslurm.cached_output["azslurm_metrics"]) > 0
        assert azslurm.cached_output["azslurm_metrics"][0].describe()[0].name == "azslurm_partition_info"
        metric = azslurm.cached_output["azslurm_metrics"][0].collect()
        samples_by_key = {
                (s.labels['partition'],s.labels["vm_size"], s.labels["azure_count"], s.labels["nodelist"]): s.value
                for s in metric[0].samples
        }
        assert samples_by_key["part1","Standard_D2s_v3","15","node[1-5]"] == 10

    @patch.object(Azslurm, 'run_command', new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_azslurm_query_exception(self, mock_run, azslurm):
        mock_run.side_effect = Exception("Command failed")
        await azslurm.azslurm_query()
        assert azslurm.cached_output["azslurm_metrics"] == []