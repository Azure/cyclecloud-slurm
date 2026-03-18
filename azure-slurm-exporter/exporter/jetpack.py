from .exporter import BaseCollector
from prometheus_client import Gauge
import logging
import exporter.util as util
from typing import List
log = logging.getLogger(__name__)

class JetpackNotAvailException(Exception):
    pass

class Jetpack(BaseCollector):
    """
    A collector that queries the Jetpack binary to retrieve cluster metadata
    and exports it as a Prometheus Gauge metrics.
    """


    def __init__(self, binary_path="/opt/cycle/jetpack/bin/jetpack", interval=86400, timeout=120):
        self.binary_path = binary_path
        self.interval = interval
        self.timeout = timeout
        self.cached_output = {"jetpack_metrics":[]}
        self.default_options = ["config", "azure.metadata.compute.location", "None"]

    def initialize(self) -> None:
        """
        Validate that the jetpack binary is available and executable to be used for metrics collection.
        """
        if not util.is_file_binary(self.binary_path):
            log.error(f"{self.binary_path} is not a file or not executable")
            raise JetpackNotAvailException

    def start(self) -> None:
        """
        Start the periodic metrics collection loop for jetpack to query cluster region data,
        parse the output to create Prometheus formatted cluster info metric, and cache the results at each interval.
        """
        self.launch_task(func=self.jetpack_query, interval=self.interval)

    def export_metrics(self) -> List[Gauge]:
        """
        Return the most recently collected jetpack metrics for Prometheus to scrape.
        """
        return self.cached_output["jetpack_metrics"]

    def parse_output(self, stdout) -> List[Gauge]:
        """
        Parse jetpack command stdout and return prometheus gauge for cluster info
        """
        jetpack_cluster_info = Gauge("jetpack_cluster_info", "Cluster Metadata",
                                       labelnames=["region"],
                                       registry=None)
        region = stdout.decode().strip()
        jetpack_cluster_info.labels(region=region).set(1)
        return [jetpack_cluster_info]

    async def jetpack_query(self) -> None:
        """
        Run jetpack query with default options to retrieve the cluster region and cache the parsed result as a prometheus
        metrics gauge representing cluster info
        """
        args = [self.binary_path]
        args.extend(self.default_options)

        try:
            proc = await self.run_command(*args, timeout=self.timeout)
            self.cached_output["jetpack_metrics"] = self.parse_output(proc.stdout)
        except Exception as e:
            log.error(e)
            return
