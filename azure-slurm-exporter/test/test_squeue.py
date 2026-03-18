import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from exporter.squeue import Squeue, SqueueNotAvailException
from exporter.exporter import CommandFailedException, CommandTimedOutException
from prometheus_client import Gauge


class TestSqueueInitialize:

    @pytest.fixture
    def squeue(self):
        """Create a Squeue collector instance for testing."""
        return Squeue()

    @patch("exporter.util.is_file_binary")
    def test_initialize_valid_binary(self, mock_is_binary, squeue):
        """Test successful initialization when binary exists."""
        mock_is_binary.return_value = True
        squeue.initialize()

    @patch("exporter.util.is_file_binary")
    def test_initialize_invalid_binary(self, mock_is_binary, squeue):
        """Test initialization fails when binary is not available."""
        mock_is_binary.return_value = False
        with pytest.raises(SqueueNotAvailException):
            squeue.initialize()


class TestSqueueParseOutput:

    @pytest.fixture
    def squeue(self):
        """Create a Squeue collector instance for testing."""
        return Squeue()

    def test_parse_output_running_job(self, squeue):
        """Test parse_output correctly parses a running job."""
        stdout = b"12345|job_name|2|node[1-2]|partition1|RUNNING|2024-01-01T00:00:00|2024-01-01T00:00:01|user1\n"
        squeue.cached_output["squeue_metrics"] = squeue.parse_output(stdout)
        samples_by_keys = {}
        metrics = squeue.export_metrics()

        # Validate partition job state metric
        for metric in metrics:
            for metric_family in metric.collect():
                if metric_family.name == "squeue_partition_jobs_state":
                    for s in metric_family.samples:
                        assert "partition" in s.labels
                        assert "state" in s.labels
                        samples_by_keys[(s.labels["partition"], s.labels["state"])] = s.value
                elif metric_family.name == "squeue_job_nodes_allocated":
                    for s in metric_family.samples:
                        assert "partition" in s.labels
                        assert "state" in s.labels
                        assert "nodelist" in s.labels
                        assert "job_id" in s.labels
                        assert "job_name" in s.labels
                        assert "start_time" in s.labels
                        samples_by_keys[(s.labels['nodelist'],s.labels["partition"], s.labels["state"], s.labels["job_id"], s.labels["job_name"], s.labels["start_time"])] = s.value
        assert samples_by_keys.get(("node[1-2]","partition1","running","12345", "job_name", "2024-01-01T00:00:01")) == 2
        assert samples_by_keys.get(("partition1","running")) == 1

    def test_parse_output_multiple_states(self, squeue):
        """Test parse_output handles jobs with multiple states."""
        stdout = (
            b"12345|job1|2|node[1-2]|part1|RUNNING|2024-01-01T00:00:00|2024-01-01T00:00:01|user1\n"
            b"12346|job2|1||part1|PENDING|2024-01-01T00:01:00|N/A|user2\n"
        )
        squeue.cached_output["squeue_metrics"] = squeue.parse_output(stdout)
        metrics = squeue.export_metrics()
        # Collect all samples and validate states
        all_samples = []
        for metric in metrics:
            for metric_family in metric.collect():
                all_samples.extend(metric_family.samples)

        states = {s.labels["state"] for s in all_samples}
        assert "running" in states
        assert "pending" in states

    def test_parse_output_empty_output(self, squeue):
        """Test parse_output handles empty output."""
        stdout = b""
        squeue.cached_output["squeue_metrics"] = squeue.parse_output(stdout)

        metrics = squeue.export_metrics()

        # All values should be 0 or no samples
        for metric in metrics:
            for metric_family in metric.collect():
                for sample in metric_family.samples:
                    assert sample.value == 0.0

    def test_parse_output_mixed_states(self, squeue):
        """Test parse_output correctly counts jobs across partitions and states."""
        stdout = (
            b"1|job1|2|node1|p1|RUNNING|2024-01-01T00:00:00|2024-01-01T00:00:01|u1\n"
            b"2|job2|1|node2|p1|RUNNING|2024-01-01T00:01:00|2024-01-01T00:01:01|u2\n"
            b"3|job3|3||p2|PENDING|2024-01-01T00:02:00|N/A|u3\n"
        )
        squeue.cached_output["squeue_metrics"] = squeue.parse_output(stdout)
        metrics = squeue.export_metrics()

        # Find the partition jobs state metric
        partition_metric = None
        job_nodes_metric = None
        for metric in metrics:
            for metric_family in metric.collect():
                if "partition_jobs_state" in metric_family.name:
                    partition_metric = metric_family
                elif "job_nodes_allocated" in metric_family.name:
                    job_nodes_metric = metric_family

        # Validate partition job counts
        if partition_metric:
            samples_by_key = {
                (s.labels["partition"], s.labels["state"]): s.value
                for s in partition_metric.samples
            }
            assert samples_by_key.get(("p1", "running")) == 2
            assert samples_by_key.get(("p2", "pending")) == 1

        # Validate node allocations for running jobs
        if job_nodes_metric:
            samples_by_job = {
                s.labels["job_id"]: s.value
                for s in job_nodes_metric.samples
            }
            assert samples_by_job.get("1") == 2
            assert samples_by_job.get("2") == 1


class TestSqueueExportMetrics:

    @pytest.fixture
    def squeue(self):
        """Create a Squeue collector instance for testing."""
        return Squeue()

    def test_export_metrics_empty(self, squeue):
        """Test export_metrics returns empty list when no cached data."""
        metrics = squeue.export_metrics()
        assert metrics == []

    def test_export_metrics_cached(self, squeue):
        """Test export_metrics returns consistent cached data."""
        stdout = (
            b"100|myjob|4|node[1-4]|batch|RUNNING|2024-01-01T00:00:00|2024-01-01T00:00:01|testuser\n"
            b"101|myjob2|1||batch|PENDING|2024-01-01T00:01:00|N/A|testuser\n"
        )
        squeue.cached_output["squeue_metrics"] = squeue.parse_output(stdout)

        # First call
        metrics1 = squeue.export_metrics()
        # Second call should return same cached data
        metrics2 = squeue.export_metrics()
        assert metrics1 == metrics2

    def test_export_metrics_validates_gauge_type(self, squeue):
        """Test export_metrics returns Gauge instances."""
        stdout = b"12345|job1|2|node[1-2]|part1|RUNNING|2024-01-01T00:00:00|2024-01-01T00:00:01|user1\n"
        squeue.cached_output["squeue_metrics"] = squeue.parse_output(stdout)

        metrics = squeue.export_metrics()
        for metric in metrics:
            assert isinstance(metric, Gauge)


class TestSqueueMetricValues:
    """Validate exact metric values using prometheus_client sample inspection."""

    @pytest.fixture
    def squeue(self):
        """Create a Squeue collector instance for testing."""
        return Squeue()

    def test_single_running_job_values(self, squeue):
        """Test metric values for a single running job."""
        stdout = b"500|training|8|gpu-node[1-8]|gpu|RUNNING|2024-06-15T10:00:00|2024-06-15T10:00:01|researcher\n"
        squeue.cached_output["squeue_metrics"] = squeue.parse_output(stdout)
        metrics = squeue.export_metrics()

        for metric in metrics:
            for family in metric.collect():
                for sample in family.samples:
                    assert isinstance(sample.value, (int, float))
                    assert sample.value >= 0

    def test_no_jobs_all_zeros(self, squeue):
        """Test all metric values are zero when no jobs exist."""
        squeue.cached_output["squeue_metrics"] = squeue.parse_output(b"")
        metrics = squeue.export_metrics()

        for metric in metrics:
            for family in metric.collect():
                for sample in family.samples:
                    assert sample.value == 0.0

    def test_large_job_count(self, squeue):
        """Test metric values for a large number of jobs."""
        lines = []
        for i in range(100):
            state = b"RUNNING" if i % 2 == 0 else b"PENDING"
            nodelist = b"node1" if state == b"RUNNING" else b""
            lines.append(b"%d|job%d|1|%s|batch|%s|2024-01-01T00:00:00|2024-01-01T00:00:01|user\n" % (i, i, nodelist, state))
        stdout = b"".join(lines)

        squeue.cached_output["squeue_metrics"] = squeue.parse_output(stdout)
        metrics = squeue.export_metrics()

        partition_metric = None
        for metric in metrics:
            for family in metric.collect():
                if "partition_jobs_state" in family.name:
                    partition_metric = family

        if partition_metric:
            samples_by_state = {
                s.labels["state"]: s.value for s in partition_metric.samples
            }
            assert samples_by_state.get("running") == 50.0
            assert samples_by_state.get("pending") == 50.0


class TestSqueueQuery:

    @pytest.fixture
    def squeue(self):
        """Create a Squeue collector instance for testing."""
        return Squeue()

    @pytest.mark.asyncio
    @patch.object(Squeue, "run_command", new_callable=AsyncMock)
    async def test_squeue_query_success(self, mock_run, squeue):
        """Test successful squeue query parses and caches metrics."""
        mock_proc = MagicMock()
        mock_proc.stdout = b"12345|job1|2|node[1-2]|batch|RUNNING|2024-01-01T00:00:00|2024-01-01T00:00:01|user1\n"
        mock_run.return_value = mock_proc
        samples_by_key = {}
        await squeue.squeue_query()
        assert len(squeue.cached_output["squeue_metrics"]) == 2
        metric1 = squeue.cached_output["squeue_metrics"][0]
        family = metric1.collect()
        for s in family[0].samples:
            samples_by_key[(s.labels["partition"], s.labels["state"])] = s.value
        metric2 = squeue.cached_output["squeue_metrics"][1]
        family = metric2.collect()
        for s in family[0].samples:
            samples_by_key[(s.labels['nodelist'],s.labels["partition"], s.labels["state"], s.labels["job_id"], s.labels["job_name"], s.labels["start_time"])] = s.value
        assert samples_by_key.get(("batch","running")) == 1
        assert samples_by_key.get(("node[1-2]","batch","running","12345","job1","2024-01-01T00:00:01")) == 2

    @pytest.mark.asyncio
    @patch.object(Squeue, "run_command", new_callable=AsyncMock)
    async def test_squeue_query_caches_result(self, mock_run, squeue):
        """Test squeue query caches parse_output result."""
        mock_proc = MagicMock()
        mock_proc.stdout = b"12345|job1|2|node[1-2]|batch|RUNNING|2024-01-01T00:00:00|2024-01-01T00:00:01|user1\n"
        mock_run.return_value = mock_proc
        mock_gauges = [MagicMock(spec=Gauge), MagicMock(spec=Gauge)]

        with patch.object(squeue, "parse_output", return_value=mock_gauges):
            await squeue.squeue_query()
            assert squeue.cached_output["squeue_metrics"] == mock_gauges

    @pytest.mark.asyncio
    @patch.object(Squeue, "run_command", new_callable=AsyncMock)
    async def test_squeue_query_exception(self, mock_run, squeue):
        """Test squeue query does not parse output on command failure."""
        mock_run.side_effect = CommandFailedException("squeue", 1, "error")
        with patch.object(squeue, "parse_output") as mock_parse:
            await squeue.squeue_query()
            mock_parse.assert_not_called()

    @pytest.mark.asyncio
    @patch.object(Squeue, "run_command", new_callable=AsyncMock)
    async def test_squeue_query_timeout(self, mock_run, squeue):
        """Test squeue query does not parse output on timeout."""
        mock_run.side_effect = CommandTimedOutException("squeue", 30)
        with patch.object(squeue, "parse_output") as mock_parse:
            await squeue.squeue_query()
            mock_parse.assert_not_called()

    @pytest.mark.asyncio
    @patch.object(Squeue, "run_command", new_callable=AsyncMock)
    async def test_squeue_query_nonzero_exit_preserves_cache(self, mock_run, squeue):
        """Test squeue query preserves empty cache on non-zero exit."""
        mock_run.side_effect = CommandFailedException("squeue", 1, "slurm error")
        await squeue.squeue_query()
        assert squeue.cached_output["squeue_metrics"] == []
