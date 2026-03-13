from .exporter import BaseCollector
from collections import namedtuple
from prometheus_client import Gauge
from dataclasses import dataclass, field
import logging
import exporter.util as util
from typing import List
# @dataclass
# class SqueueMetrics:
#     squeue_partition_jobs_state: GaugeMetricFamily = GaugeMetricFamily(
#                 f"squeue_partition_jobs_state",
#                 f"Number of jobs in a state per partition",
#                 labels=['partition','state'],
#             )

#     squeue_job_nodes_allocated: GaugeMetricFamily = GaugeMetricFamily(
#             "squeue_job_nodes_allocated",
#             "Number of nodes allocated to a running job",
#             labels=["job_id", "job_name", "partition", "state"],
#         )

#     def add(self, label: list, value):



log = logging.getLogger(__name__)

class SqueueNotAvailException(Exception):
    pass

class Squeue(BaseCollector):
    """
    A collector that periodically queries SLURM squeue command to gather job state information and node allocation
    data from the job queue and parses the output into Prometheus Gauge metrics.
    """
    def __init__(self, binary_path="/usr/bin/squeue", interval=60, timeout=30):
        self.binary_path = binary_path
        self.interval = interval
        self.timeout = timeout
        self.cached_output = {"squeue_metrics":[]}
        self.default_output_fmt = f"%i|%j|%D|%N|%P|%T|%V|%u"
        self.default_output_headers = "jobid,name,nodes,nodelist,partition,state,submit_time,user"
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
        Parse the stdout from an squeue command and generates two Prometheus
        Gauge metrics that track the number of jobs currently in the queue in each state per partition
        and track the number of nodes allocated to running jobs in the queue
        """
        squeue_partition_jobs_state = Gauge(
                f"squeue_partition_jobs_state",
                f"Number of jobs in a state per partition",
                labelnames=['partition','state'], registry=None
            )

        squeue_job_nodes_allocated = Gauge(
            "squeue_job_nodes_allocated",
            "Number of nodes allocated to a running job",
            labelnames=["job_id", "job_name", "partition", "state", "nodelist"], registry=None
        )
        # number of jobs per state,partition key
        counts = {}
        lines = stdout.decode().strip().splitlines()
        lines_iter = (line.split("|") for line in lines)

        for row in map(self.squeue_output._make, lines_iter):
            if row.state.lower() == "running":
                squeue_job_nodes_allocated.labels(job_id=row.jobid,
                                                  job_name=row.name,
                                                  partition=row.partition,
                                                  state=row.state.lower(),
                                                  nodelist=row.nodelist).set(int(row.nodes))
            key = (row.partition, row.state.lower())
            counts[key] = counts.get(key, 0) + 1

        for (partition, state), count in counts.items():
            squeue_partition_jobs_state.labels(partition=partition,
                                                   state=state).set(count)

        return [squeue_partition_jobs_state, squeue_job_nodes_allocated]

    async def squeue_query(self) -> None:
        """
        Run the squeue query with default options, parse the output to create two Prometheus Gauge metrics
        that represent the current state of each job in the queue as well as the total nodes allocated to
        any running job in the queue, and caches the results
        """
        args = [self.binary_path]
        args.extend(self.default_options)
        try:
            proc = await self.run_command(timeout=self.timeout, *args)
        except Exception as e:
            log.error(e)
            return
        self.cached_output["squeue_metrics"] = self.parse_output(proc.stdout)
