import os
import re
import shutil
import sys
import json
import csv
from tabulate import tabulate
from datetime import datetime
import logging
import subprocess
from collections import namedtuple
from hpc.autoscale.cost.azurecost import azurecost
from .util import run

log = logging.getLogger('cost')


class Statistics:

    def __init__(self):

        self.jobs = 0
        self.running_jobs = 0
        self.processed = 0
        self.unprocessed = 0
        self.cost_per_sku = {}
        self.admincomment_err = 0

    def display(self):

        table = []
        table.append(['Total Jobs', self.jobs])
        table.append(['Total Processed Jobs', self.processed])
        table.append(['Total processed running jobs', self.running_jobs])
        table.append(['Unprocessed Jobs', self.unprocessed])
        table.append(['Jobs with admincomment errors', self.admincomment_err])
        print(tabulate(table, headers=['SUMMARY',''], tablefmt="simple"))

class CostSlurm:
    def __init__(self, start:str, end: str, cluster: str, cache_root: str, fmt: str=None) -> None:

        self.start = start
        self. end = end
        self.cluster = cluster
        self.sacct = shutil.which("sacct")
        if not self.sacct:
            raise RuntimeError("Could not find valid sacct binary")

        self.squeue = shutil.which("squeue")
        if not self.squeue:
            raise RuntimeError("Could not find valid squeue binary")

        self.sacctmgr = shutil.which("sacctmgr")
        if not self.sacctmgr:
            raise RuntimeError("Could not find valid sacctmgr binary")

        self.stats = Statistics()
        self.cache = f"{cache_root}/slurm"
        try:
            os.makedirs(self.cache, 0o777, exist_ok=True)
        except OSError as e:
            log.error("Unable to create cache directory {self.cache}")
            log.error(e.strerror)
            raise
        default_output_fmt = "jobid,user,account,cluster,partition,ncpus,nnodes,submit,start,end,elapsedraw,state"
        default_input_fmt = default_output_fmt + ",admincomment"
        self.options = ["--allusers", "--duplicates", "--parsable2", "--allocations", "--noheader"]
        avail_format = self.get_sacct_fields()
        if fmt:
            req_fmt = fmt.split(",")
            in_fmt = default_input_fmt.split(",")
            for f in req_fmt:
                if f not in avail_format:
                    raise ValueError(f"{f} is not a valid sacct format option")
                if f not in in_fmt:
                    in_fmt.append(f)
            self.output_format = ",".join(req_fmt)
            self.input_format = ",".join(in_fmt)
        else:
            self.output_format = default_output_fmt
            self.input_format = default_input_fmt

        self.in_fmt_t = namedtuple('in_fmt_t', self.input_format)
        self.slurm_fmt_t = namedtuple('slurm_fmt_t', self.output_format)
        self.c_fmt_t = namedtuple('c_fmt_t', ['cost'])

    def get_sacct_fields(self):

        options = []
        cmd = [self.sacct, "-e"]
        out = run(cmd)
        for line in out.stdout.splitlines():
            for opt in line.split():
                options.append(opt.lower())

        return options

    def _construct_command(self) -> list:

        args = [self.sacct]
        for opt in self.options:
            args.append(opt)
        args.append("-M")
        args.append(self.cluster)
        args.append(f"--start={self.start}")
        args.append(f"--end={self.end}")
        args.append("-o")
        args.append(self.input_format)
        return args

    def use_cache(self, filename) -> bool:
        return False

    def get_queue_rec_file(self) -> str:
        return os.path.join(self.cache, f"queue.out")

    def get_job_rec_file(self) -> str:
        return os.path.join(self.cache, f"sacct-{self.start}-{self.end}.out")

    def get_queue_records(self) -> str:

        _queue_rec_file = self.get_queue_rec_file()
        if self.use_cache(_queue_rec_file):
            return _queue_rec_file

        cmd = [self.squeue, "--json"]
        with open(_queue_rec_file, 'w') as fp:
            output = run(cmd, stdout=fp)
            if output.returncode:
                log.error("could not read slurm queue")
        return _queue_rec_file

    def process_queue(self) -> dict:
        running_jobs = {}
        queue_rec = self.get_queue_records()
        with open(queue_rec, 'r') as fp:
            data = json.load(fp)

        for job in data['jobs']:
            if job['job_state'] != 'RUNNING' and job['job_state'] != 'CONFIGURING':
                continue
            job_id = job['job_id']
            if job['admin_comment']:
                running_jobs[job_id] = job['admin_comment']
        return running_jobs

    def fetch_job_records(self) -> str:

        _job_rec_file = self.get_job_rec_file()
        if self.use_cache(_job_rec_file):
            return _job_rec_file
        cmd = self._construct_command()
        with open(_job_rec_file, 'w') as fp:
            output = run(cmd, stdout=fp)
            if output.returncode:
                log.error("Could not fetch slurm records")
        return _job_rec_file

    def parse_admincomment(self, comment: str):

        return json.loads(comment)

    def get_output_format(self, azcost: azurecost):

        az_fmt = azcost.get_job_format()
        return namedtuple('out_fmt_t', list(self.slurm_fmt_t._fields + az_fmt._fields + self.c_fmt_t._fields))

    def process_jobs(self, azcost: azurecost, jobsfp, out_fmt_t):

        _job_rec_file = self.fetch_job_records()
        running = self.process_queue()
        fp = open(_job_rec_file, newline='')
        reader = csv.reader(fp, delimiter='|')
        writer = csv.writer(jobsfp, delimiter=',')

        for row in map(self.in_fmt_t._make, reader):
            self.stats.jobs += 1
            if row.state == 'RUNNING' and int(row.jobid) in running:
                admincomment = running[int(row.jobid)]
                self.stats.running_jobs += 1
            else:
                admincomment = row.admincomment
            try:
                comment_d = self.parse_admincomment(admincomment)[0]
                sku_name = comment_d['vm_size']
                cpupernode = comment_d['pcpu_count']
                region = comment_d['location']
                spot = comment_d['spot']
            except (json.JSONDecodeError,IndexError) as e:
                log.debug(f"Cannot parse admincomment job={row.jobid} cluster={row.cluster} admincomment={admincomment}")
                self.stats.admincomment_err += 1
                self.stats.unprocessed += 1
                continue
            except KeyError as e:
                log.debug(f"Key: {e.args[0]} not found in admincomment, job={row.jobid}, cluster={row.cluster}")
                self.stats.admincomment_err +=1
                self.stats.unprocessed += 1
                continue
            charge_factor = float(row.ncpus) / float(cpupernode)

            az_fmt = azcost.get_job(sku_name, region, spot)
            charged_cost = ((az_fmt.rate/3600) * float(row.elapsedraw)) * charge_factor
            c_fmt = self.c_fmt_t(cost=charged_cost)
            if (region,sku_name) not in self.stats.cost_per_sku:
                self.stats.cost_per_sku[(region,sku_name)] = 0
            self.stats.cost_per_sku[(region,sku_name)] += charged_cost

            out_row = []
            for f in out_fmt_t._fields:
                if f in self.in_fmt_t._fields:
                    out_row.append(row._asdict()[f])
                elif f in az_fmt._fields:
                    out_row.append(az_fmt._asdict()[f])
                elif f in self.c_fmt_t._fields:
                    out_row.append(c_fmt._asdict()[f])
                else:
                    log.error(f"encountered an unexpected field {f}")

            writer.writerow(out_row)
            self.stats.processed += 1
        fp.close()


def _escape(s: str) -> str:
    return re.sub("[^a-zA-Z0-9-]", "-", s).lower()


class CostDriver:
    def __init__(self, azcost: azurecost, config: dict):

        self.config = config
        self.azcost = azcost
        self.cluster = config.get('cluster_name')
        if not self.cluster:
            raise ValueError("cluster_name not present in config")
        self.cluster = _escape(self.cluster)

    def run(self, start: datetime, end: datetime, out: str, fmt: str):

        log.debug(f"start: {start}")
        log.debug(f"end: {end}")
        sacct_start = start.isoformat()
        sacct_end = end.isoformat()

        cost_config = self.config.get('cost', {})
        if not cost_config or not cost_config.get('cache_root'):
            log.debug("Using /tmp as cost cache dir")
            cache_root = "/tmp"
        else:
            cache_root = cost_config.get('cache_root')

        cost_slurm = CostSlurm(start=sacct_start, end=sacct_end, cluster=self.cluster,
                               cache_root=cache_root,fmt=fmt)
        try:
            os.makedirs(out, exist_ok=True)
        except OSError as e:
            log.error(f"Cannot create output directory {out}")
            raise
        jobs_csv = os.path.join(out, "jobs.csv")
        part_csv = os.path.join(out, "partition.csv")
        part_hourly = os.path.join(out, "partition_hourly.csv")

        fmt = self.azcost.get_job_format()
        out_fmt_t = cost_slurm.get_output_format(self.azcost)
        with open(jobs_csv, 'w') as fp:
            writer = csv.writer(fp, delimiter=',')
            writer.writerow(list(out_fmt_t._fields))
            cost_slurm.process_jobs(azcost=self.azcost, jobsfp=fp, out_fmt_t=out_fmt_t)

        fmt = self.azcost.get_nodearray_format()
        with open(part_csv, 'w') as fp:
            writer = csv.writer(fp, delimiter=',')
            writer.writerow(list(fmt._fields))
            self.azcost.get_nodearray(fp, start=sacct_start, end=sacct_end)

        fmt = self.azcost.get_nodearray_hourly_format()
        with open(part_hourly, 'w') as fp:
            writer = csv.writer(fp, delimiter=',')
            writer.writerow(list(fmt._fields))
            self.azcost.get_nodearray_hourly(fp, start=sacct_start, end=sacct_end)

        cost_slurm.stats.display()
