from .exporter import BaseCollector
from collections import namedtuple
from prometheus_client import Gauge
import logging
import exporter.util as util
from typing import List

log = logging.getLogger(__name__)

class SqueueNotAvailException(Exception):
    pass

class Squeue(BaseCollector):
    """
    A collector that periodically queries SLURM squeue command to gather job state
    information from the job queue and parses the output into a Prometheus Gauge metric.
    """
    def __init__(self, binary_path="/usr/bin/squeue", interval=60, timeout=30):
        self.binary_path = binary_path
        self.interval = interval
        self.timeout = timeout
        self.cached_output = {"squeue_metrics":[]}
        self.default_output_fmt = f"%i|%j|%D|%N|%P|%T|%V|%S|%u"
        self.default_output_headers = "jobid,name,nodes,nodelist,partition,state,submit_time,start_time,user"
        self.squeue_output = namedtuple("squeue_output", self.default_output_headers)
        self.default_options = ["-h", "-o", self.default_output_fmt]

    def initialize(self) -> None:
        """
        Validate that the squeue binary is available and executable to be used for metrics collection
        """
        if not util.is_file_binary(self.binary_path):
            log.error(f"{self.binary_path} is not a file or not executable")
            raise SqueueNotAvailException

    def start(self) -> None:
        """
        Start the periodic metrics collection loop for squeue to query the current queue's job state data,
        parse the output to create Prometheus formatted job state Gauge metric, and cache the results at each interval.
        """
        self.launch_task(func=self.squeue_query, interval=self.interval)

    def export_metrics(self) -> List[Gauge]:
        """
        Return the most recently collected squeue metrics for Prometheus to scrape.
        """
        return self.cached_output["squeue_metrics"]

    def parse_output(self,stdout) -> List[Gauge]:
        """
        Parse the stdout from an squeue command and generate a Prometheus
        Gauge metric that tracks the number of jobs currently in each state per partition.
        """
        squeue_partition_jobs_state = Gauge(
                f"squeue_partition_jobs_state",
                f"Number of jobs in a state per partition",
                labelnames=['partition','state'], registry=None
            )
        # number of jobs per state,partition key
        counts = {}
        lines = stdout.decode().strip().splitlines()
        lines_iter = (line.split("|") for line in lines)

        for row in map(self.squeue_output._make, lines_iter):
            key = (row.partition, row.state.lower())
            counts[key] = counts.get(key, 0) + 1

        for (partition, state), count in counts.items():
            squeue_partition_jobs_state.labels(partition=partition,
                                                   state=state).set(count)

        return [squeue_partition_jobs_state]

    async def squeue_query(self) -> None:
        """
        Run the squeue query with default options, parse the output to create the
        Prometheus Gauge metric that represents job counts by partition and state,
        and cache the results.
        """
        args = [self.binary_path]
        args.extend(self.default_options)
        try:
            proc = await self.run_command(*args, timeout=self.timeout)
            self.cached_output["squeue_metrics"] = self.parse_output(proc.stdout)
        except Exception as e:
            log.error(e)
            return

