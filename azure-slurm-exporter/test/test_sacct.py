import pytest
from unittest.mock import patch, AsyncMock
from exporter.sacct import Sacct, SacctNotAvailException
from prometheus_client import Counter


class TestSacctInitialize:
    @patch("exporter.util.is_file_binary")
    def test_initialize_valid_binary(self, mock_is_binary):
        mock_is_binary.return_value = True
        sacct = Sacct()
        sacct.initialize()

    @patch("exporter.util.is_file_binary")
    def test_initialize_invalid_binary(self, mock_is_binary):
        mock_is_binary.return_value = False
        sacct = Sacct()
        with pytest.raises(SacctNotAvailException):
            sacct.initialize()


class TestSacctParseOutput:
    def test_parse_output_single_completed_job(self):
        sacct = Sacct()
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
                    assert "nodelist" in s.labels
                    samples_by_keys[(s.labels['nodelist'],s.labels["partition"], s.labels["state"], s.labels["reason"], s.labels["exit_code"])] = s.value
        assert samples_by_keys.get(("node1", "batch","COMPLETED","","0:0")) == 1
        
    def test_parse_output_multiple_states(self):
        sacct = Sacct()
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
        assert "COMPLETED" in states
        assert "FAILED" in states

    def test_parse_output_empty_output(self):
        sacct = Sacct()
        sacct.parse_output(b"")
        metrics = sacct.export_metrics()

        # Counter should have no samples when no jobs parsed
        for metric in metrics:
            for family in metric.collect():
                for sample in family.samples:
                    assert sample.value == 0.0

    def test_parse_output_mixed_partitions(self):
        sacct = Sacct()
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
                (s.labels['nodelist'],s.labels["partition"], s.labels["state"]): s.value
                for s in terminal_metric.samples
                if "_total" in s.name
            }
            assert samples_by_key.get(("node1","gpu", "COMPLETED")) == 1.0
            assert samples_by_key.get(("node2","gpu", "COMPLETED")) == 1.0
            assert samples_by_key.get(("node3","cpu", "FAILED")) == 1.0


class TestSacctExportMetrics:
    def test_export_metrics_returns_counter(self):
        sacct = Sacct()
        metrics = sacct.export_metrics()
        assert len(metrics) == 1
        assert isinstance(metrics[0], Counter)

    def test_export_metrics_same_reference(self):
        sacct = Sacct()
        stdout = b"1001|job1|node1|1|batch|0:0|0:0|COMPLETED|user1|2024-01-01T10:00:00|2024-01-01T09:00:00|2024-01-01T11:00:00|None\n"
        sacct.parse_output(stdout)

        metrics1 = sacct.export_metrics()
        metrics2 = sacct.export_metrics()
        assert metrics1 == metrics2


class TestSacctExitCodeMapping:
    def test_known_exit_codes(self):
        sacct = Sacct()
        assert sacct.SLURM_EXIT_CODE_MAPPING["0:0"] == ""
        assert sacct.SLURM_EXIT_CODE_MAPPING["137:0"] == "SIGKILL - Force killed"
        assert sacct.SLURM_EXIT_CODE_MAPPING["143:0"] == "SIGTERM - Terminated"
        assert sacct.SLURM_EXIT_CODE_MAPPING["139:0"] == "SIGSEGV - Segfault"
        assert sacct.SLURM_EXIT_CODE_MAPPING["130:0"] == "SIGINT - Ctrl+C"

    def test_exit_code_mapped_to_reason_label(self):
        sacct = Sacct()
        stdout = b"1001|job1|node1|1|batch|137:0|0:0|FAILED|user1|2024-01-01T10:00:00|2024-01-01T09:00:00|2024-01-01T11:00:00|None\n"
        sacct.parse_output(stdout)
        metrics = sacct.export_metrics()

        for metric in metrics:
            for family in metric.collect():
                for sample in family.samples:
                    if sample.labels.get("exit_code") == "137:0":
                        assert sample.labels["reason"] == "SIGKILL - Force killed"

    def test_unknown_exit_code_defaults_to_empty(self):
        sacct = Sacct()
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

    def test_counter_increments(self):
        sacct = Sacct()
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

    def test_counter_accumulates_across_calls(self):
        sacct = Sacct()
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

    def test_all_values_non_negative(self):
        sacct = Sacct()
        stdout = b"1|job1|node1|1|batch|0:0|0:0|COMPLETED|u1|2024-01-01T10:00:00|2024-01-01T09:00:00|2024-01-01T11:00:00|None\n"
        sacct.parse_output(stdout)
        metrics = sacct.export_metrics()

        for metric in metrics:
            for family in metric.collect():
                for sample in family.samples:
                    assert isinstance(sample.value, (int, float))
                    assert sample.value == 1

    def test_large_job_batch(self):
        sacct = Sacct()
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
            assert samples_by_state.get("COMPLETED") == 50.0
            assert samples_by_state.get("FAILED") == 50.0


class TestSacctQuery:
    @pytest.mark.asyncio
    async def test_sacct_query_success(self):
        sacct = Sacct()
        mock_proc = AsyncMock()
        mock_proc.stdout = b"1|job1|node1|1|batch|0:0|0:0|COMPLETED|u1|2024-01-01T10:00:00|2024-01-01T09:00:00|2024-01-01T11:00:00|None\n"

        with patch.object(sacct, "run_command", return_value=mock_proc):
            await sacct.sacct_query()
            assert sacct.starttime == sacct.endtime
        metric = sacct.sacct_terminal_jobs.collect()
        samples_by_key = {
        (s.labels['nodelist'],s.labels["partition"], s.labels["state"], s.labels["reason"], s.labels["exit_code"]): s.value
        for s in metric[0].samples
        }
        print(samples_by_key)
        assert samples_by_key.get(("node1","batch","COMPLETED","","0:0")) == 1

    @pytest.mark.asyncio
    async def test_sacct_query_exception(self):
        sacct = Sacct()
        with patch.object(sacct, "run_command", side_effect=Exception("Command failed")):
            with patch.object(sacct, "parse_output") as mock_parse:
                await sacct.sacct_query()
                mock_parse.assert_not_called()

