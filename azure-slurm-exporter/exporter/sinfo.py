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
        Initialize the Sinfo object by validating the binary path.
        """
        if not util.is_file_binary(self.binary_path):
            log.error(f"{self.binary_path} is not a file or not executable")
            raise SinfoNotAvailException

    def start(self) -> None:
        """
        Begin collecting metrics asynchronously and runs it at regular
        intervals as defined by the configured downstream interval.
        """
        self.launch_task(func=self.sinfo_query, interval=self.interval)

    def export_metrics(self) -> List[Gauge]:
        """
        Return metrics in Prometheus-compatible format from cache.
        """
        return self.cached_output["sinfo_query"]

    def normalize_state(self, state) -> str:
        """
        Normalize SLURM node state by mapping state suffixes to their base states. If
        node state has a suffix, then we set that node's state to the suffix state.
        """
        suffix = state[-1]
        if suffix in self.STATE_SUFFIXES:
            return self.STATE_SUFFIXES[suffix]
        else:
            return state

    def parse_output(self, stdout) -> List[Gauge]:
        """
        Parse the output from the sinfo command and create a Gauge metric that track each nodelist's
        state per partition.
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
        Execute sinfo command asynchronously and cache the parsed output in prometheus metric format.
        """
        args = [self.binary_path]
        args.extend(self.default_options)
        try:
            proc = await self.run_command(timeout=self.timeout,*args)
        except Exception as e:
            log.error(e)
            return
        output = self.parse_output(proc.stdout)
        #TODO: DO we need to lock this?
        self.cached_output["sinfo_query"] = output

