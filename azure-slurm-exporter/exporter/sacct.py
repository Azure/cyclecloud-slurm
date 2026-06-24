from .exporter import BaseCollector
from collections import namedtuple
from prometheus_client import Counter, disable_created_metrics, Gauge
from datetime import datetime
import logging
import exporter.util as util
from typing import List, Union
log = logging.getLogger(__name__)

class SacctNotAvailException(Exception):
    pass

class Sacct(BaseCollector):
    """
    A collector that periodically queries SLURM sacct command within a sliding time window to
    track job completions and their outcomes. It maps SLURM exit codes to human-readable
    descriptions and exports a Prometheus Counter metric labeled by partition, exit code, reason, and state.
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

    def __init__(self, binary_path="/usr/bin/sacct", interval=300, timeout=120, starttime=None):
        self.binary_path = binary_path
        self.interval = interval
        self.timeout = timeout
        self.sacct_terminal_jobs= Counter("sacct_terminal_jobs","Total Number of completed slurm jobs",
                                    ["partition", "exit_code","reason","state"], registry=None)
        self.default_output_fmt = "jobid,jobname,nodelist,nnodes,partition,exitcode,derivedexitcode,state,user,start,submit,end,reason"
        self.sacct_output = namedtuple("sacct_output", self.default_output_fmt)
        self.terminal_states = "completed,failed,cancelled,timeout,node_fail,preempted,out_of_memory,deadline,boot_fail"
        self.failed_states = "failed,node_fail,out_of_memory,boot_fail"
        self.cardinality_bound = 20
        self.starttime = starttime if starttime is not None else datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        self.endtime = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        self.default_options = ["-P" ,"-n", "-o", self.default_output_fmt, "-s", self.terminal_states, "--allocations" ]
        self.cached_output={"sacct_metrics":[]}

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

    def export_metrics(self) -> List[Union[Counter,Gauge]]:
        """
        Return the most recently collected sacct metrics for Prometheus to scrape.
        """
        return self.cached_output["sacct_metrics"]

    def _node_count(self, row) -> int:
        """Number of nodes allocated to a job, used to rank failed jobs. Defaults to 0 when unparseable."""
        try:
            return int(row.nnodes)
        except (ValueError, TypeError):
            return 0

    def parse_output(self, stdout) -> List[Union[Counter,Gauge]]:
        """
        Parse sacct output into a terminal jobs counter covering every finished job and a per-job
        gauge for failed jobs.

        TODO: ###### MUST REMOVE ASAP ######.
        This is a hack to mathematically bound the failed jobs exported. Any job can finish in a
        non-COMPLETED state, so the "failed" set is otherwise unbounded. To bound it:
        1) The failed jobs gauge is restricted to genuine failure states (self.failed_states). When more
           failed jobs than the bound are present, the jobs allocated the most nodes are kept, since larger
           failures consume the most resources and are the most useful to drill into.
        2) The failed jobs exported per interval is capped at self.cardinality_bound. Upper bounds below
           assume cardinality_bound = 20 and interval = 5 minutes.

           Each job is one unique series keyed by 3 cardinality-exploding labels: jobid, jobname, nodelist.
           The rest (partition, exit_code, reason, state) are low-cardinality. starttime/endtime are the
           collector's query-window bounds (one value per interval, shared by all jobs).
           NOTE: the original intent of the developer seems to be to emit the job's own start/end timestamps but instead they are emitting
            Query window's starttime and endtime. 
            Doing the correct thing would actually add 2 more exploding labels. We intentionally are choosing to KEEP THIS BUG.

           Series index: <= 20 new series every 5 minutes. A series stays "active" only while ingested in
               the last ~12 hours, bounding active series from this gauge to 20 * (12h / 5min) = 2,880 per
               12-hour window.
           Inverted label index: <= 3 exploding labels * 20 jobs + 2 unique timestamps (query window timestamps) = 62 new index entries every 5 minutes,
               i.e. 62 * 144 = 8928 within the 12-hour active window.

        Both series and their label-index entries are retained in the metrics backend for up to 18 months
        with no way to purge. This bounds the 12-hour active-series window, but long-term storage still grows
        unbounded, capped only by the rolling 18-month retention. Source: https://learn.microsoft.com/en-us/azure/azure-monitor/fundamentals/service-limits#prometheus-metrics
        ## TODO: This entire section NEEDS TO BE GONE BY NEXT RELEASE.
        """
        sacct_failed_jobs = Gauge("sacct_failed_jobs",
                                    f"Per-job indicator (value is always 1) for up to {self.cardinality_bound} failed jobs (ranked by node count) in the query interval",
                                    ["jobid","jobname","nodelist","partition", "exit_code","reason","state", "starttime","endtime"], registry=None)

        failed_states = set(self.failed_states.split(","))
        failed_rows = []
        lines = stdout.decode().strip().splitlines()
        log.debug(f"Number of jobs:{len(lines)}")
        lines_iter = (line.split("|") for line in lines)
        for row in map(self.sacct_output._make, lines_iter):
            reason = self.SLURM_EXIT_CODE_MAPPING.get(row.exitcode, "")
            self.sacct_terminal_jobs.labels(
                partition=row.partition,
                exit_code=row.exitcode,
                reason=reason,
                state=row.state.lower()).inc()

            if row.state.lower() in failed_states:
                failed_rows.append(row)

        top_failed_rows = sorted(failed_rows, key=self._node_count, reverse=True)[:self.cardinality_bound]
        log.debug(f"Number of failed jobs: {len(failed_rows)}, exporting top {len(top_failed_rows)} by node count")
        for row in top_failed_rows:
            reason = self.SLURM_EXIT_CODE_MAPPING.get(row.exitcode, "")
            sacct_failed_jobs.labels(
                jobid=row.jobid,
                jobname=row.jobname,
                nodelist=row.nodelist,
                partition=row.partition,
                exit_code=row.exitcode,
                reason=reason,
                state=row.state.lower(),
                starttime=self.starttime,
                endtime=self.endtime).set(1)

        return [self.sacct_terminal_jobs, sacct_failed_jobs]

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
            proc = await self.run_command(*args, timeout=self.timeout)
            self.cached_output["sacct_metrics"] = self.parse_output(proc.stdout)
        except Exception as e:
            log.error(e)
            return
        else:
            #if command raises an exception, starttime does not get updated and next interval still includes initial starttime
            self.starttime=self.endtime




