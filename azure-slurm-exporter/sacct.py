from exporter import BaseCollector
from collections import namedtuple
from prometheus_client import Counter, disable_created_metrics
from datetime import datetime, timedelta
import logging
import util as util
from typing import List
log = logging.getLogger(__name__)

class SacctNotAvailException(Exception):
    pass

class Sacct(BaseCollector):

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
                                    ["partition", "exit_code","reason","state"], registry=None)
        self.default_output_fmt = "jobid,jobname,nodelist,nnodes,partition,exitcode,derivedexitcode,state,user,start,submit,end,reason"
        self.sacct_output = namedtuple("sacct_output", self.default_output_fmt)
        self.terminal_states = "completed,failed,cancelled,timeout,node_fail,preempted,out_of_memory,deadline,boot_fail"
        self.starttime = (datetime.now() - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S")
        self.endtime = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        self.default_options = ["-P" ,"-n", "-o", self.default_output_fmt, "-s", self.terminal_states, "--allocations" ]

    def initialize(self) -> None:
        """
        Initialize the Sacct instance by validating the binary and disabling created metrics.

        Checks if the sacct binary exists and is executable. If the binary is not found
        or is not executable, logs an error and raises an exception.

        Raises:
            SacctNotAvailException: If the sacct binary is not available or not executable.
        """
        if not util.is_file_binary(self.binary_path):
            log.error(f"{self.binary_path} is not a file or not executable")
            raise SacctNotAvailException
        disable_created_metrics()

    def start(self) -> None:
        """
        Begin collecting metrics asynchronously.

        This method initializes the metric collection process and runs it at regular
        intervals as defined by the configured downstream interval. The collection
        runs asynchronously without blocking the event loop.
        """
        self.launch_task(func=self.sacct_query, interval=self.interval)

    def export_metrics(self) -> List[Counter]:
        """
        Return metrics in Prometheus-compatible format.

        Returns:
            list: A list of metric objects in Prometheus-compatible format,
                  ready for exposition to monitoring backends.
        """
        #TODO: DO we need to lock this?
        return [self.sacct_terminal_jobs]

    def parse_output(self, stdout) -> None:
        """
        Parse sacct command output and increment terminal job metrics.

        Processes the raw stdout from sacct command, splits it into lines and fields,
        and updates Prometheus metrics for completed SLURM jobs with their partition,
        exit code, reason, and state.

        Args:
            stdout (bytes): The raw output from sacct command execution.
        """
        seen={}
        lines = stdout.decode().strip().splitlines()
        log.debug(f"Number of jobs:{len(lines)}")
        lines_iter = (line.split("|") for line in lines)
        for row in map(self.sacct_output._make, lines_iter):
            reason = self.SLURM_EXIT_CODE_MAPPING.get(row.exitcode, "")
            self.sacct_terminal_jobs.labels(
                partition=row.partition,
                exit_code=row.exitcode,
                reason=reason,
                state=row.state).inc()

    async def sacct_query(self) -> None:
        """
        Query SLURM accounting data (sacct) for jobs within a specified time window.

        This method queries sacct filtering by a time window of size `interval`, which represents
        the frequency at which queries are executed. For example, if interval is 5 minutes, the
        query retrieves job data from the last 5 minutes.

        The time window progresses as follows:
        - The start time of the current query is set to the end time of the previous query
        - The end time is set to the current moment when the query is executed
        - After execution, starttime is updated to the current endtime for the next query iteration

        The method constructs and executes the sacct command with appropriate filters and handles
        any exceptions that occur during query execution. Query output is parsed upon successful completion.
        """
        args = []
        self.endtime = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        args.append(self.binary_path)
        args.extend(self.default_options)
        args.extend(["--starttime", self.starttime, "--endtime", self.endtime])
        log.debug(f"running sacct query between {self.starttime} and {self.endtime}")
        try:
            proc = await self.run_command(timeout=self.timeout,*args)
        except Exception as e:
            log.error(e)
            return
        self.starttime=self.endtime
        self.parse_output(proc.stdout)


