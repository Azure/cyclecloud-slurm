from .exporter import BaseCollector
from collections import namedtuple
from prometheus_client import Gauge
import json
import logging
import exporter.util as util
import re
from typing import List
log = logging.getLogger(__name__)

class AzslurmNotAvailException(Exception):
    pass

class Azslurm(BaseCollector):
    """
    A collector that periodically queries the azslurm binary to retrieve partition and resource availability information,
    and parses the output into Prometheus-compatible gauge metrics.
    """

    def __init__(self, binary_path="/root/bin/azslurm", interval=300, timeout=120):
        self.binary_path = binary_path
        self.interval = interval
        self.timeout = timeout
        self.partition_output = namedtuple("partition_output", ["partition", "node_list"])
        self.limits_default_fmt = ["nodearray","vm_size","available_count","family_available_count","regional_available_count","ncpus","ngpus","memgb"]
        self.limits_output = namedtuple("limits_output",self.limits_default_fmt)
        self.cached_output = {"azslurm_metrics":[]}

    def initialize(self) -> None:
        """
        Validate that the azslurm binary is available and executable to be used for metrics collection.
        """
        if not util.is_file_binary(self.binary_path):
            log.error(f"{self.binary_path} is not a file or not executable")
            raise AzslurmNotAvailException

    def start(self) -> None:
        """
        Start the periodic metrics collection loop for azslurm to query partitions and limits data,
        parse the output to create Prometheus formatted cluster capacity metrics, and cache the results at each interval.
        """
        self.launch_task(func=self.azslurm_query, interval=self.interval)

    def export_metrics(self) -> List[Gauge]:
        """
        Return the most recently collected azslurm metrics for Prometheus to scrape.
        """
        return self.cached_output["azslurm_metrics"]

    def parse_output(self, partitions_stdout, limits_stdout) -> List[Gauge]:
        """
        Convert raw azslurm partitions and limits output into Prometheus metrics.
        Combines partition node lists with per-VM-size availability limits
        to produce a single gauge representing cluster capacity.
        """
        azslurm_partition_info = Gauge("azslurm_partition_info", "Partition specs for cluster and available nodecount for each partitions",
                                       labelnames=["partition", "nodelist", "vm_size", "azure_count", "ncpus", "ngpus", "memory_gib"],
                                       registry=None)

        nodelist_map = self._parse_partitions(partitions_stdout)
        for row in self._parse_limits(limits_stdout):
            nodelist = nodelist_map.get(row.nodearray, "")
            memory_gib = self._parse_memgb(row.memgb)
            azslurm_partition_info.labels(partition=row.nodearray,
                                        nodelist=nodelist,
                                        vm_size=row.vm_size,
                                        azure_count=min(int(row.family_available_count), int(row.regional_available_count)),
                                        ncpus=row.ncpus,
                                        ngpus=row.ngpus,
                                        memory_gib=memory_gib
                                        ).set(int(row.available_count))
        return [azslurm_partition_info]

    def _parse_partitions(self, stdout) -> dict:
        """
        Map each partition (nodearray) to its associated node list.
        """
        node_list_map = {}
        partition_name = None
        for line in stdout.decode().strip().splitlines():
            if line.startswith("#"):
                continue
            kv = dict(re.findall(r'(\w+)=(\S+)', line))
            if "PartitionName" in kv:
                partition_name = kv["PartitionName"]
            if "Nodename" in kv and partition_name:
                node_list_map[partition_name] = kv["Nodename"]
                partition_name = None
        return node_list_map

    def _parse_limits(self, stdout):
        """
        Extract per-nodearray VM availability limits from azslurm limits output.
        """
        for entry in json.loads(stdout.decode()):
            yield self.limits_output._make(entry[f] for f in self.limits_default_fmt)

    def _parse_memgb(self, memgb_str: str) -> str:
        """
        Parse the memgb field (e.g. 'memory::220.00g') and return the numeric GiB value as a string.
        """
        try:
            return memgb_str.split("::")[1].rstrip("g")
        except (IndexError, AttributeError):
            return "0"
    async def azslurm_query(self) -> None:
        """
        Query azslurm partitions and limits command and cache parsed output as a single prometheus gauge to represent
        per vm-size cluster capacity.
        """
        args_partitions = [self.binary_path]
        args_limits = [self.binary_path]
        args_partitions.extend(["partitions"])
        args_limits.extend(["limits"])

        try:
            proc_partitions = await self.run_command(timeout=self.timeout, *args_partitions)
            proc_limits = await self.run_command(timeout=self.timeout, *args_limits)
        except Exception as e:
            log.error(e)
            return

        self.cached_output["azslurm_metrics"] = self.parse_output(proc_partitions.stdout, proc_limits.stdout)


