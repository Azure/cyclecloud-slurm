from .exporter import BaseCollector
from collections import namedtuple
from prometheus_client import Gauge
import logging
import exporter.util as util
from typing import List

log = logging.getLogger(__name__)

class SinfoNotAvailException(Exception):
    pass

class Sinfo(BaseCollector):
    """
    A collector that periodically queries SLURM sinfo command to collect node state information
    across partitions, normalizes state values by mapping state suffixes to their operational meanings, and
    parses the output into Prometheus Gauge metrics.
    """


    # Suffix meanings from sinfo man page
    STATE_SUFFIXES = {
        "*": "not_responding",
        "~": "powered_off",
        "#": "powering_up",
        "!": "pending_power_down",
        "%": "powering_down",
        "$": "maintenance_reservation",
        "@": "pending_reboot",
        "^": "reboot_issued",
        "-": "planned_backfill",
    }

    def __init__(self, binary_path="/usr/bin/sinfo", interval=30, timeout=15):
        self.binary_path = binary_path
        self.interval = interval
        self.timeout = timeout
        self.cached_output = {"sinfo_query":[]}
        self.default_output_fmt = f"%N|%D|%R|%E|%T"
        self.default_output_headers = "nodelist,nodes,partition,reason,state"
        self.sinfo_output = namedtuple("sinfo_output", self.default_output_headers)
        self.default_options = ["-h", "-o", self.default_output_fmt]

    def initialize(self) -> None:
        """
        Validate that the sinfo binary is available and executable to be used for metrics collection
        """
        if not util.is_file_binary(self.binary_path):
            log.error(f"{self.binary_path} is not a file or not executable")
            raise SinfoNotAvailException

    def start(self) -> None:
        """
        Start the periodic metrics collection loop for sinfo to query node state data
        parse the output to create Prometheus formatted node state Gauge metric, and cache the results at each interval.
        """
        self.launch_task(func=self.sinfo_query, interval=self.interval)

    def export_metrics(self) -> List[Gauge]:
        """
        Return the most recently collected sinfo metrics for Prometheus to scrape.
        """
        return self.cached_output["sinfo_query"]

    def normalize_state(self, state) -> str:
        """
        Normalize SLURM node state by mapping state suffixes to their base states. If
        node state has a suffix, then we set that node's state as the suffix state to indicate the
        actual operational status of the node
        """
        suffix = state[-1]
        if suffix in self.STATE_SUFFIXES:
            return self.STATE_SUFFIXES[suffix]
        else:
            return state

    def parse_output(self, stdout) -> List[Gauge]:
        """
        Parse the output from the sinfo command and create a Gauge metric that tracks each nodelist's
        state per partition as well as the reason they are in that state if any.
        """
        sinfo_partitions_nodes_state = Gauge(
                f"sinfo_partition_nodes_state",
                f"Number of nodes in a state per partition",
                labelnames=['node_list','partition','state', 'reason'], registry=None
            )

        lines = stdout.decode().strip().splitlines()
        lines_iter = (line.split("|") for line in lines)
        for row in map(self.sinfo_output._make, lines_iter):
            state = self.normalize_state(row.state)
            sinfo_partitions_nodes_state.labels(node_list=row.nodelist,
                                                partition=row.partition,
                                                state=state,
                                                reason=row.reason).set(float(row.nodes))
        return [sinfo_partitions_nodes_state]


    async def sinfo_query(self) -> None:
        """
        Run the sinfo query with default options, parse the output to create a Prometheus Gauge metric
        that represents each nodelist and their current state, and cache the result
        """
        args = [self.binary_path]
        args.extend(self.default_options)
        try:
            proc = await self.run_command(*args, timeout=self.timeout)
        except Exception as e:
            log.error(e)
            return
        self.cached_output["sinfo_query"] = self.parse_output(proc.stdout)

