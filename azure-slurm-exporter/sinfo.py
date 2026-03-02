from exporter import BaseCollector
from collections import namedtuple
from prometheus_client import Gauge
import logging
import util as util
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

        Checks if the binary file at self.binary_path exists and is executable.

        Raises:
            SinfoNotAvailException: If the binary path is not a valid file or not executable.
        """
        if not util.is_file_binary(self.binary_path):
            log.error(f"{self.binary_path} is not a file or not executable")
            raise SinfoNotAvailException

    def start(self) -> None:
        """
        Begin collecting metrics asynchronously.

        This method initializes the metric collection process and runs it at regular
        intervals as defined by the configured downstream interval. The collection
        runs asynchronously without blocking the event loop.
        """
        self.launch_task(func=self.sinfo_query, interval=self.interval)

    def export_metrics(self) -> List[Gauge]:
        """
        Return metrics in Prometheus-compatible format.

        Returns:
            list: A list of metric objects in Prometheus-compatible format,
                  ready for exposition to monitoring backends.
        """
        return self.cached_output["sinfo_query"]

    def normalize_state(self, state) -> str:
        """
        Normalize SLURM node state by mapping state suffixes to their base states.

        This method extracts the last character of the input state string and checks if it
        matches a known suffix in STATE_SUFFIXES. If a matching suffix is found, it returns
        the mapped state value; otherwise, it returns the original state string unchanged.

        Args:
            state (str): The SLURM node state string that may contain a suffix character.

        Returns:
            str: The normalized state. If the last character is a known suffix, returns the
                 mapped state value from STATE_SUFFIXES. Otherwise, returns the original
                 state string.

        """
        suffix = state[-1]
        if suffix in self.STATE_SUFFIXES:
            return self.STATE_SUFFIXES[suffix]
        else:
            return state

    def parse_output(self, stdout) -> List[Gauge]:
        """
        Parse the output from the sinfo command and create a Gauge metric.

        This method processes the stdout from an sinfo command execution, parses each line
        into structured data, normalizes the node state, and creates a Prometheus Gauge metric
        that tracks the number of nodes in each state per partition.

        Args:
            stdout (bytes): The raw output from the sinfo command as bytes.

        Returns:
            list: A list containing a single Gauge metric object with labels for node_list,
                  partition, state, and reason, where the metric value represents the number
                  of nodes in that particular state.
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
        Execute sinfo command asynchronously and cache the results.

        This method runs the sinfo command with configured default options and a specified timeout.
        The command output is parsed and stored in the cached_output dictionary for later retrieval.
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

