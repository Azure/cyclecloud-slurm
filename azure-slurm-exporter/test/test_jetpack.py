import pytest
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from exporter.jetpack import Jetpack, JetpackNotAvailException
from exporter.exporter import CommandFailedException, CommandTimedOutException
from prometheus_client import Gauge


class TestJetpackInitialize:

    @pytest.fixture
    def jetpack(self):
        """Create a Jetpack collector instance for testing."""
        return Jetpack()

    @patch("exporter.util.is_file_binary")
    def test_initialize_success(self, mock_is_binary, jetpack):
        """Test successful initialization when binary exists."""
        mock_is_binary.return_value = True
        jetpack.initialize()
        mock_is_binary.assert_called_once_with("/opt/cycle/jetpack/bin/jetpack")

    @patch("exporter.util.is_file_binary")
    def test_initialize_failure(self, mock_is_binary, jetpack):
        """Test initialization fails when binary is not available."""
        mock_is_binary.return_value = False
        with pytest.raises(JetpackNotAvailException):
            jetpack.initialize()


class TestJetpackExportMetrics:

    @pytest.fixture
    def jetpack(self):
        """Create a Jetpack collector instance for testing."""
        return Jetpack()

    def test_export_metrics(self, jetpack):
        """Test export_metrics returns cached metrics."""
        test_gauge = Mock(spec=Gauge)
        jetpack.cached_output["jetpack_metrics"] = [test_gauge]
        metrics = jetpack.export_metrics()
        assert metrics == [test_gauge]


class TestJetpackParseOutput:

    @pytest.fixture
    def jetpack(self):
        """Create a Jetpack collector instance for testing."""
        return Jetpack()

    def test_parse_output(self, jetpack):
        """Test parse_output correctly parses jetpack command output."""
        stdout = b"eastus"
        result = jetpack.parse_output(stdout)
        assert len(result) == 1
        assert isinstance(result[0], Gauge)
        assert result[0]._name == "jetpack_cluster_info"
        metric = result[0].collect()
        assert metric[0].samples[0].labels["region"] == "eastus"


class TestJetpackQuery:

    @pytest.fixture
    def jetpack(self):
        """Create a Jetpack collector instance for testing."""
        return Jetpack()

    @pytest.mark.asyncio
    @patch.object(Jetpack, "run_command", new_callable=AsyncMock)
    async def test_jetpack_query_success(self, mock_run_cmd, jetpack):
        """Test successful jetpack query returns region metric."""
        mock_proc = MagicMock()
        mock_proc.stdout = b"westus2"
        mock_run_cmd.return_value = mock_proc

        await jetpack.jetpack_query()

        assert len(jetpack.cached_output["jetpack_metrics"]) == 1
        mock_run_cmd.assert_called_once_with(
            "/opt/cycle/jetpack/bin/jetpack",
            "config",
            "azure.metadata.compute.location",
            "None",
            timeout=120
        )
        metric = jetpack.cached_output["jetpack_metrics"][0].collect()
        assert metric[0].samples[0].labels["region"] == "westus2"

    @pytest.mark.asyncio
    @patch.object(Jetpack, "run_command", new_callable=AsyncMock)
    async def test_jetpack_query_exception(self, mock_run_cmd, jetpack):
        """Test jetpack query preserves cache on command failure."""
        jetpack.cached_output["jetpack_metrics"] = ["Some original metric"]
        mock_run_cmd.side_effect = CommandFailedException("jetpack", 1, "error")

        await jetpack.jetpack_query()

        assert jetpack.cached_output["jetpack_metrics"] == ["Some original metric"]

    @pytest.mark.asyncio
    @patch.object(Jetpack, "run_command", new_callable=AsyncMock)
    async def test_jetpack_query_timeout(self, mock_run_cmd, jetpack):
        """Test jetpack query preserves cache on timeout."""
        jetpack.cached_output["jetpack_metrics"] = ["Some original metric"]
        mock_run_cmd.side_effect = CommandTimedOutException("jetpack", 120)

        await jetpack.jetpack_query()

        assert jetpack.cached_output["jetpack_metrics"] == ["Some original metric"]