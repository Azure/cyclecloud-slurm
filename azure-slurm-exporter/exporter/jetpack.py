from exporter import BaseCollector
from collections import namedtuple
from prometheus_client import Gauge
import logging
import util as util
from typing import List
log = logging.getLogger(__name__)

class JetpackNotAvailException(Exception):
    pass

class Jetpack(BaseCollector):

    def __init__(self, binary_path="/opt/cycle/jetpack/bin/jetpack", interval=86400, timeout=120):
        self.binary_path = binary_path
        self.interval = interval
        self.timeout = timeout
        self.cached_output = {"jetpack_metrics":[]}
        self.default_options = ["config", "azure.metadata.compute.location", "None"]

    def initialize(self) -> None:
        """
        Initialize the Jetpack instance by validating the binary
        """
        if not util.is_file_binary(self.binary_path):
            log.error(f"{self.binary_path} is not a file or not executable")
            raise JetpackNotAvailException

    def start(self) -> None:
        """
        Begin collecting metrics asynchronously and runs it at regular
        intervals as defined by the configured downstream interval.
        """
        self.launch_task(func=self.jetpack_query, interval=self.interval)

    def export_metrics(self) -> List[Gauge]:
        """
        Return metrics in Prometheus-compatible format from cache.
        """
        #TODO: DO we need to lock this?
        return self.cached_output["jetpack_metrics"]

    def parse_output(self, stdout) -> None:
        """
        Parse jetpack command stdout and return prometheus gauge for cluster specs
        """
        jetpack_cluster_info = Gauge("jetpack_cluster_info", "Cluster Metadata",
                                       labelnames=["region"],
                                       registry=None)
        region = stdout.decode().strip()
        jetpack_cluster_info.labels(region=region).set(1)
        return [jetpack_cluster_info]

    async def jetpack_query(self) -> None:
        """
        Run jetpack query with default options and save parsed result in prometheus
        metrics format to cache
        """
        args = [self.binary_path]
        args.extend(self.default_options)

        try:
            proc = await self.run_command(timeout=self.timeout,*args)
        except Exception as e:
            log.error(e)
            return

        self.cached_output["jetpack_metrics"] = self.parse_output(proc.stdout)


