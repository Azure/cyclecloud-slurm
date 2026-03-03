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
        Initialize the Squeue instance and validate the binary executable.
        """
        if not util.is_file_binary(self.binary_path):
            log.error(f"{self.binary_path} is not a file or not executable")
            raise SqueueNotAvailException

    def start(self) -> None:
        """
        Begin collecting metrics asynchronously and runs it at regular
        intervals as defined by the configured downstream interval.
        """
        self.launch_task(func=self.squeue_query, interval=self.interval)

    def export_metrics(self) -> List[Gauge]:
        """
        Return metrics in Prometheus-compatible format from cache.
        """
        return self.cached_output["squeue_metrics"]

    def parse_output(self,stdout) -> List[Gauge]:
        """
        Parse the stdout from an squeue command and generates two Prometheus
        Gauge metrics:

        1. squeue_partition_jobs_state: Tracks the number of jobs in each state per partition
            - Labels: partition, state

        2. squeue_job_nodes_allocated: Tracks the number of nodes allocated to running jobs
            - Labels: job_id, job_name, partition, state
            - Only populated for jobs in "running" state
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
                                                  state=row.state,
                                                  nodelist=row.nodelist).set(float(row.nodes))
            key = (row.partition, row.state.lower())
            counts[key] = counts.get(key, 0) + 1

        for (partition, state), count in counts.items():
            squeue_partition_jobs_state.labels(partition=partition,
                                                   state=state).set(count)

        return [squeue_partition_jobs_state, squeue_job_nodes_allocated]

    async def squeue_query(self) -> None:
        """
        Execute an squeue query asynchronously and cache the parsed result in prometheus
        metrics format.
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
        self.cached_output["squeue_metrics"] = output
