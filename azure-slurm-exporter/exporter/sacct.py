from .exporter import BaseCollector
from collections import namedtuple
from prometheus_client import Counter, disable_created_metrics
from datetime import datetime, timedelta
import logging
import exporter.util as util
from typing import List
log = logging.getLogger(__name__)

class SacctNotAvailException(Exception):
    pass

class Sacct(BaseCollector):
    """
    A collector that periodically queries SLURM sacct command within a sliding time window to
    track job completions and their outcomes. It maps SLURM exit codes to human-readable
    descriptions and exports a Prometheus Counter metric labeled by partition, exit code, reason, state,
    and nodelist.
    """

    SLURM_EXIT_CODE_MAPPING = {
            "0:0": "",
            "1:0": "General failure",
            "2:0": "Misuse of shell built-in",
            "125:0": "Slurm Out of Memory Error",
            "126:0": "Command invoked cannot execute",
            "127:0": "Command not found",
            "128:0": "Invalid argument to exit",
            "129:0": "SIGHUP",
            "130:0": "SIGINT - Ctrl+C",
            "131:0": "SIGQUIT",
            "134:0": "SIGABRT",
            "137:0": "SIGKILL - Force killed",
            "139:0": "SIGSEGV - Segfault",
            "141:0": "SIGPIPE",
            "143:0": "SIGTERM - Terminated",
            "152:0": "SIGXCPU - CPU limit",
            "153:0": "SIGXFSZ - File size limit",
        }

    def __init__(self, binary_path="/usr/bin/sacct", interval=300, timeout=120):
        self.binary_path = binary_path
        self.interval = interval
        self.timeout = timeout
        self.sacct_terminal_jobs= Counter("sacct_terminal_jobs","Total Number of completed slurm jobs",
                                    ["partition", "exit_code","reason","state", "nodelist"], registry=None)
        self.default_output_fmt = "jobid,jobname,nodelist,nnodes,partition,exitcode,derivedexitcode,state,user,start,submit,end,reason"
        self.sacct_output = namedtuple("sacct_output", self.default_output_fmt)
        self.terminal_states = "completed,failed,cancelled,timeout,node_fail,preempted,out_of_memory,deadline,boot_fail"
        self.starttime = (datetime.now() - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S")
        self.endtime = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        self.default_options = ["-P" ,"-n", "-o", self.default_output_fmt, "-s", self.terminal_states, "--allocations" ]

    def initialize(self) -> None:
        """
        Validate that the sacct binary is available and executable to be used for metrics collection and
        disable Prometheus Counter created related metrics.
        """
        if not util.is_file_binary(self.binary_path):
            log.error(f"{self.binary_path} is not a file or not executable")
            raise SacctNotAvailException
        disable_created_metrics()

    def start(self) -> None:
        """
        Start the periodic metrics collection loop for sacct to query terminal job data (jobs that have either completed, failed, or cancelled for whatever reason),
        parse the output to create Prometheus formatted terminal job Counter metric, and cache the results at each interval.
        """
        self.launch_task(func=self.sacct_query, interval=self.interval)

    def export_metrics(self) -> List[Counter]:
        """
        Return the most recently collected sacct metrics for Prometheus to scrape.
        """
        return [self.sacct_terminal_jobs]

    def parse_output(self, stdout) -> None:
        """
        Parse sacct command output and increment terminal jobs metric for each job in the output to describe total number of finished jobs by partition,
        exit_code, reason, state, and nodelist.
        """
        lines = stdout.decode().strip().splitlines()
        log.debug(f"Number of jobs:{len(lines)}")
        lines_iter = (line.split("|") for line in lines)
        for row in map(self.sacct_output._make, lines_iter):
            reason = self.SLURM_EXIT_CODE_MAPPING.get(row.exitcode, "")
            self.sacct_terminal_jobs.labels(
                partition=row.partition,
                exit_code=row.exitcode,
                reason=reason,
                state=row.state.lower(),
                nodelist=row.nodelist).inc()

    async def sacct_query(self) -> None:
        """
        Run sacct query with default options and filtering by a time window of size `interval`, which represents
        the frequency at which queries are executed, to only get the total # of jobs that finished (whether completed successfully,
        failed, or cancelled) in that specific time window. Those outputted jobs are then parsed to increment the Prometheus terminal jobs
        Counter metric. Time window then progresses by setting starttime to the current endtime so that in the next query we only increment unique jobs
        that just finished in that updated window.

        """
        args = [self.binary_path]
        self.endtime = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        args.extend(self.default_options)
        args.extend(["--starttime", self.starttime, "--endtime", self.endtime])
        log.debug(f"running sacct query between {self.starttime} and {self.endtime}")
        try:
            proc = await self.run_command(timeout=self.timeout, *args)
        except Exception as e:
            log.error(e)
            return
        self.starttime=self.endtime
        self.parse_output(proc.stdout)


