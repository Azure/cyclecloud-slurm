from .exporter import BaseCollector
from prometheus_client import Gauge
import logging
import exporter.util as util
from typing import List
import json

log = logging.getLogger(__name__)

class SdiagNotAvailException(Exception):
    pass

class Sdiag(BaseCollector):
    """
    A collector that periodically queries SLURM sdiag command to gather essential scheduler health metrics
    for monitoring scheduler performance and identifying potential issues.
    Parses JSON output into Prometheus Gauge metrics.
    """

    def __init__(self, binary_path="/usr/bin/sdiag", interval=300, timeout=30):
        """
        Initialize the Sdiag collector.

        Args:
            binary_path: Path to the sdiag binary (default: /usr/bin/sdiag)
            interval: Collection interval in seconds (default: 300s to minimize scheduler overhead)
            timeout: Command execution timeout in seconds (default: 30)
        """
        self.binary_path = binary_path
        self.interval = interval
        self.timeout = timeout
        self.cached_output = {"sdiag_metrics": []}
        self.default_options = ["--json"]

    def initialize(self) -> None:
        """
        Validate that the sdiag binary is available and executable to be used for metrics collection.
        """
        if not util.is_file_binary(self.binary_path):
            log.error(f"{self.binary_path} is not a file or not executable")
            raise SdiagNotAvailException

    def start(self) -> None:
        """
        Start the periodic metrics collection loop for sdiag to query scheduler diagnostic data,
        parse the JSON output to create Prometheus formatted metrics, and cache the results at each interval.
        """
        self.launch_task(func=self.sdiag_query, interval=self.interval)

    def export_metrics(self) -> List[Gauge]:
        """
        Return the most recently collected sdiag metrics for Prometheus to scrape.
        """
        return self.cached_output["sdiag_metrics"]

    def parse_output(self, stdout) -> List[Gauge]:
        """
        Parse the JSON output from the sdiag command and create Prometheus Gauge metrics
        for scheduler health monitoring.
        """
        metrics = []

        try:
            data = json.loads(stdout.decode())
            statistics = data.get("statistics", {})

            # Server thread count
            if "server_thread_count" in statistics:
                server_threads = Gauge(
                    "sdiag_server_thread_count",
                    "Number of server threads currently active in slurmctld",
                    registry=None
                )
                server_threads.set(statistics["server_thread_count"])
                metrics.append(server_threads)

            # Agent queue size
            if "agent_queue_size" in statistics:
                agent_queue = Gauge(
                    "sdiag_agent_queue_size",
                    "Number of outgoing RPC requests queued for compute nodes",
                    registry=None
                )
                agent_queue.set(statistics["agent_queue_size"])
                metrics.append(agent_queue)

            # DBD agent queue
            if "dbd_agent_queue_size" in statistics:
                dbd_queue = Gauge(
                    "sdiag_dbd_agent_queue_size",
                    "Number of messages queued for Slurm database daemon",
                    registry=None
                )
                dbd_queue.set(statistics["dbd_agent_queue_size"])
                metrics.append(dbd_queue)

            # Main scheduling cycle time (with type labels: last, max, mean)
            if any(k in statistics for k in ["schedule_cycle_last", "schedule_cycle_max", "schedule_cycle_mean"]):
                cycle_time = Gauge(
                    "sdiag_main_cycle_time_us",
                    "Main scheduling cycle time in microseconds by type",
                    labelnames=["type"],
                    registry=None
                )
                if "schedule_cycle_last" in statistics:
                    cycle_time.labels(type="last").set(statistics["schedule_cycle_last"])
                if "schedule_cycle_max" in statistics:
                    cycle_time.labels(type="max").set(statistics["schedule_cycle_max"])
                if "schedule_cycle_mean" in statistics:
                    cycle_time.labels(type="mean").set(statistics["schedule_cycle_mean"])
                metrics.append(cycle_time)

            # Mean scheduling cycle depth
            if "schedule_cycle_mean_depth" in statistics:
                mean_depth = Gauge(
                    "sdiag_main_mean_depth_cycle",
                    "Mean number of jobs examined per scheduling cycle",
                    registry=None
                )
                mean_depth.set(statistics["schedule_cycle_mean_depth"])
                metrics.append(mean_depth)

        except json.JSONDecodeError as e:
            log.error(f"Failed to parse sdiag JSON output: {e}")
            return []
        except Exception as e:
            log.error(f"Error parsing sdiag output: {e}")
            return []

        return metrics

    async def sdiag_query(self) -> None:
        """
        Run the sdiag query with JSON output option, parse the output to create Prometheus
        metrics for scheduler diagnostics, and cache the results.
        """
        args = [self.binary_path]
        args.extend(self.default_options)

        try:
            proc = await self.run_command(*args, timeout=self.timeout)
            self.cached_output["sdiag_metrics"] = self.parse_output(proc.stdout)
        except Exception as e:
            log.error(f"Error executing sdiag command: {e}")
            return
