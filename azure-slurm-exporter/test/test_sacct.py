import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from exporter.sacct import Sacct, SacctNotAvailException
from exporter.exporter import CommandFailedException, CommandTimedOutException
from prometheus_client import Counter


class TestSacctInitialize:

    @pytest.fixture
    def sacct(self):
        """Create a Sacct collector instance for testing."""
        return Sacct()

    @patch("exporter.util.is_file_binary")
    def test_initialize_valid_binary(self, mock_is_binary, sacct):
        """Test successful initialization when binary exists."""
        mock_is_binary.return_value = True
        sacct.initialize()

    @patch("exporter.util.is_file_binary")
    def test_initialize_invalid_binary(self, mock_is_binary, sacct):
        """Test initialization fails when binary is not available."""
        mock_is_binary.return_value = False
        with pytest.raises(SacctNotAvailException):
            sacct.initialize()


class TestSacctParseOutput:

    @pytest.fixture
    def sacct(self):
        """Create a Sacct collector instance for testing."""
        return Sacct()

    def test_parse_output_single_completed_job(self, sacct):
        """Test parse_output handles a single completed job."""
        stdout = b"1001|myjob|node1|1|batch|0:0|0:0|COMPLETED|user1|2024-01-01T10:00:00|2024-01-01T09:00:00|2024-01-01T11:00:00|None\n"
        sacct.parse_output(stdout)
        samples_by_keys = {}
        metrics = sacct.export_metrics()
        assert len(metrics) == 1

        for metric in metrics:
            for family in metric.collect():
                for s in family.samples:
                    assert "partition" in s.labels
                    assert "exit_code" in s.labels
                    assert "reason" in s.labels
                    assert "state" in s.labels
                    samples_by_keys[(s.labels["partition"], s.labels["state"], s.labels["reason"], s.labels["exit_code"])] = s.value
        assert samples_by_keys.get(("batch","completed","","0:0")) == 1

    def test_parse_output_multiple_states(self, sacct):
        """Test parse_output handles jobs with multiple states."""
        stdout = (
            b"1001|job1|node1|1|batch|0:0|0:0|COMPLETED|user1|2024-01-01T10:00:00|2024-01-01T09:00:00|2024-01-01T11:00:00|None\n"
            b"1002|job2|node2|1|batch|137:0|0:0|FAILED|user2|2024-01-01T10:00:00|2024-01-01T09:00:00|2024-01-01T11:00:00|None\n"
        )
        sacct.parse_output(stdout)
        metrics = sacct.export_metrics()

        all_samples = []
        for metric in metrics:
            for family in metric.collect():
                all_samples.extend(family.samples)

        states = {s.labels["state"] for s in all_samples}
        assert "completed" in states
        assert "failed" in states

    def test_parse_output_empty_output(self, sacct):
        """Test parse_output handles empty output."""
        sacct.parse_output(b"")
        metrics = sacct.export_metrics()

        # Counter should have no samples when no jobs parsed
        for metric in metrics:
            for family in metric.collect():
                for sample in family.samples:
                    assert sample.value == 0.0

    def test_parse_output_mixed_partitions(self, sacct):
        """Test parse_output correctly counts jobs across partitions."""
        stdout = (
            b"1|job1|node1|1|gpu|0:0|0:0|COMPLETED|u1|2024-01-01T10:00:00|2024-01-01T09:00:00|2024-01-01T11:00:00|None\n"
            b"2|job2|node2|1|gpu|0:0|0:0|COMPLETED|u2|2024-01-01T10:00:00|2024-01-01T09:00:00|2024-01-01T11:00:00|None\n"
            b"3|job3|node3|1|cpu|1:0|0:0|FAILED|u3|2024-01-01T10:00:00|2024-01-01T09:00:00|2024-01-01T11:00:00|None\n"
        )
        sacct.parse_output(stdout)
        metrics = sacct.export_metrics()

        terminal_metric = None
        for metric in metrics:
            for family in metric.collect():
                if "terminal_jobs" in family.name:
                    terminal_metric = family

        if terminal_metric:
            samples_by_key = {
                (s.labels["partition"], s.labels["state"]): s.value
                for s in terminal_metric.samples
                if "_total" in s.name
            }
            assert samples_by_key.get(("gpu", "completed")) == 2.0
            assert samples_by_key.get(("cpu", "failed")) == 1.0


class TestSacctExportMetrics:

    @pytest.fixture
    def sacct(self):
        """Create a Sacct collector instance for testing."""
        return Sacct()

    def test_export_metrics_returns_counter(self, sacct):
        """Test export_metrics returns a Counter instance."""
        metrics = sacct.export_metrics()
        assert len(metrics) == 1
        assert isinstance(metrics[0], Counter)

    def test_export_metrics_same_reference(self, sacct):
        """Test export_metrics returns consistent references."""
        stdout = b"1001|job1|node1|1|batch|0:0|0:0|COMPLETED|user1|2024-01-01T10:00:00|2024-01-01T09:00:00|2024-01-01T11:00:00|None\n"
        sacct.parse_output(stdout)

        metrics1 = sacct.export_metrics()
        metrics2 = sacct.export_metrics()
        assert metrics1 == metrics2


class TestSacctExitCodeMapping:

    @pytest.fixture
    def sacct(self):
        """Create a Sacct collector instance for testing."""
        return Sacct()

    def test_known_exit_codes(self, sacct):
        """Test known exit codes are mapped correctly."""
        assert sacct.SLURM_EXIT_CODE_MAPPING["0:0"] == ""
        assert sacct.SLURM_EXIT_CODE_MAPPING["137:0"] == "SIGKILL - Force killed"
        assert sacct.SLURM_EXIT_CODE_MAPPING["143:0"] == "SIGTERM - Terminated"
        assert sacct.SLURM_EXIT_CODE_MAPPING["139:0"] == "SIGSEGV - Segfault"
        assert sacct.SLURM_EXIT_CODE_MAPPING["130:0"] == "SIGINT - Ctrl+C"

    def test_exit_code_mapped_to_reason_label(self, sacct):
        """Test exit code is mapped to the reason label in metrics."""
        stdout = b"1001|job1|node1|1|batch|137:0|0:0|FAILED|user1|2024-01-01T10:00:00|2024-01-01T09:00:00|2024-01-01T11:00:00|None\n"
        sacct.parse_output(stdout)
        metrics = sacct.export_metrics()

        for metric in metrics:
            for family in metric.collect():
                for sample in family.samples:
                    if sample.labels.get("exit_code") == "137:0":
                        assert sample.labels["reason"] == "SIGKILL - Force killed"

    def test_unknown_exit_code_defaults_to_empty(self, sacct):
        """Test unknown exit code defaults to empty reason."""
        stdout = b"1001|job1|node1|1|batch|99:0|0:0|FAILED|user1|2024-01-01T10:00:00|2024-01-01T09:00:00|2024-01-01T11:00:00|None\n"
        sacct.parse_output(stdout)
        metrics = sacct.export_metrics()

        for metric in metrics:
            for family in metric.collect():
                for sample in family.samples:
                    if sample.labels.get("exit_code") == "99:0":
                        assert sample.labels["reason"] == ""


class TestSacctMetricValues:
    """Validate exact metric values using prometheus_client sample inspection."""

    @pytest.fixture
    def sacct(self):
        """Create a Sacct collector instance for testing."""
        return Sacct()

    def test_counter_increments(self, sacct):
        """Test counter increments for multiple completed jobs."""
        stdout = (
            b"1|job1|node1|1|batch|0:0|0:0|COMPLETED|u1|2024-01-01T10:00:00|2024-01-01T09:00:00|2024-01-01T11:00:00|None\n"
            b"2|job2|node1|1|batch|0:0|0:0|COMPLETED|u2|2024-01-01T10:00:00|2024-01-01T09:00:00|2024-01-01T11:00:00|None\n"
            b"3|job3|node1|1|batch|0:0|0:0|COMPLETED|u3|2024-01-01T10:00:00|2024-01-01T09:00:00|2024-01-01T11:00:00|None\n"
        )
        sacct.parse_output(stdout)
        metrics = sacct.export_metrics()

        for metric in metrics:
            for family in metric.collect():
                for sample in family.samples:
                    if "_total" in sample.name and sample.labels.get("partition") == "batch":
                        assert sample.value == 3.0

    def test_counter_accumulates_across_calls(self, sacct):
        """Test counter accumulates across multiple parse_output calls."""
        batch1 = b"1|job1|node1|1|batch|0:0|0:0|COMPLETED|u1|2024-01-01T10:00:00|2024-01-01T09:00:00|2024-01-01T11:00:00|None\n"
        batch2 = b"2|job2|node1|1|batch|0:0|0:0|COMPLETED|u2|2024-01-01T10:00:00|2024-01-01T09:00:00|2024-01-01T11:00:00|None\n"

        sacct.parse_output(batch1)
        sacct.parse_output(batch2)
        metrics = sacct.export_metrics()

        for metric in metrics:
            for family in metric.collect():
                for sample in family.samples:
                    if "_total" in sample.name and sample.labels.get("partition") == "batch":
                        assert sample.value == 2.0

    def test_all_values_non_negative(self, sacct):
        """Test all metric values are non-negative."""
        stdout = b"1|job1|node1|1|batch|0:0|0:0|COMPLETED|u1|2024-01-01T10:00:00|2024-01-01T09:00:00|2024-01-01T11:00:00|None\n"
        sacct.parse_output(stdout)
        metrics = sacct.export_metrics()

        for metric in metrics:
            for family in metric.collect():
                for sample in family.samples:
                    assert isinstance(sample.value, (int, float))
                    assert sample.value == 1

    def test_large_job_batch(self, sacct):
        """Test metric values for a large batch of jobs."""
        lines = []
        for i in range(100):
            state = b"COMPLETED" if i % 2 == 0 else b"FAILED"
            exit_code = b"0:0" if state == b"COMPLETED" else b"1:0"
            lines.append(
                b"%d|job%d|node1|1|batch|%s|0:0|%s|user|2024-01-01T10:00:00|2024-01-01T09:00:00|2024-01-01T11:00:00|None\n"
                % (i, i, exit_code, state)
            )
        stdout = b"".join(lines)
        sacct.parse_output(stdout)
        metrics = sacct.export_metrics()

        terminal_metric = None
        for metric in metrics:
            for family in metric.collect():
                if "terminal_jobs" in family.name:
                    terminal_metric = family

        if terminal_metric:
            samples_by_state = {
                s.labels["state"]: s.value
                for s in terminal_metric.samples
                if "_total" in s.name
            }
            assert samples_by_state.get("completed") == 50.0
            assert samples_by_state.get("failed") == 50.0


class TestSacctQuery:

    @staticmethod
    async def _sacct_with_one_successful_query() -> Sacct:
        """Create a Sacct instance with one successful query already executed,
        so the counter has a known baseline value of 1 for (node1, batch, completed, '', 0:0)."""
        sacct = Sacct()
        mock_proc = MagicMock()
        mock_proc.stdout = b"1|job1|node1|1|batch|0:0|0:0|COMPLETED|u1|2024-01-01T10:00:00|2024-01-01T09:00:00|2024-01-01T11:00:00|None\n"
        with patch.object(Sacct, "run_command", new_callable=AsyncMock, return_value=mock_proc):
            await sacct.sacct_query()
        return sacct

    @pytest.mark.asyncio
    async def test_sacct_query_success(self):
        """Test successful sacct query populates counter and updates starttime."""
        sacct = await self._sacct_with_one_successful_query()
        assert sacct.starttime == sacct.endtime
        metric = sacct.sacct_terminal_jobs.collect()
        samples_by_key = {
        (s.labels["partition"], s.labels["state"], s.labels["reason"], s.labels["exit_code"]): s.value
        for s in metric[0].samples
        }
        assert samples_by_key.get(("batch","completed","","0:0")) == 1

    @pytest.mark.asyncio
    async def test_sacct_query_exception(self):
        """Test sacct query preserves starttime and counter on command failure."""
        sacct = await self._sacct_with_one_successful_query()
        starttime_after_success = sacct.starttime
        with patch.object(Sacct, "run_command", new_callable=AsyncMock, side_effect=CommandFailedException("sacct", 1, "error")):
            with patch.object(sacct, "parse_output") as mock_parse:
                await sacct.sacct_query()
                mock_parse.assert_not_called()
        # starttime should NOT advance on failure
        assert sacct.starttime == starttime_after_success
        # counter should still be 1 from the initial successful query
        metric = sacct.sacct_terminal_jobs.collect()
        samples_by_key = {
        (s.labels["partition"], s.labels["state"], s.labels["reason"], s.labels["exit_code"]): s.value
        for s in metric[0].samples
        }
        assert samples_by_key.get(("batch","completed","","0:0")) == 1

    @pytest.mark.asyncio
    async def test_sacct_query_timeout(self):
        """Test sacct query preserves starttime and counter on timeout."""
        sacct = await self._sacct_with_one_successful_query()
        starttime_after_success = sacct.starttime
        with patch.object(Sacct, "run_command", new_callable=AsyncMock, side_effect=CommandTimedOutException("sacct", 120)):
            with patch.object(sacct, "parse_output") as mock_parse:
                await sacct.sacct_query()
                mock_parse.assert_not_called()
        assert sacct.starttime == starttime_after_success
        # counter should still be 1
        metric = sacct.sacct_terminal_jobs.collect()
        samples_by_key = {
        (s.labels["partition"], s.labels["state"], s.labels["reason"], s.labels["exit_code"]): s.value
        for s in metric[0].samples
        }
        assert samples_by_key.get(("batch","completed","","0:0")) == 1

    @pytest.mark.asyncio
    async def test_sacct_query_nonzero_exit_preserves_starttime(self):
        """Test sacct query preserves starttime on non-zero exit."""
        sacct = await self._sacct_with_one_successful_query()
        starttime_after_success = sacct.starttime
        with patch.object(Sacct, "run_command", new_callable=AsyncMock, side_effect=CommandFailedException("sacct", 1, "slurm error")):
            await sacct.sacct_query()
        assert sacct.starttime == starttime_after_success
        # counter should still be 1
        metric = sacct.sacct_terminal_jobs.collect()
        samples_by_key = {
        (s.labels["partition"], s.labels["state"], s.labels["reason"], s.labels["exit_code"]): s.value
        for s in metric[0].samples
        }
        assert samples_by_key.get(("batch","completed","","0:0")) == 1

