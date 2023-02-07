import os
import json
import csv
from tabulate import tabulate
from datetime import datetime
import hpc.autoscale.hpclogging as log
from collections import namedtuple
from hpc.autoscale.cost.azurecost import azurecost
from .util import run_command

def get_sacct_fields():

    options = []
    cmd = "/usr/bin/sacct -e"
    out = run_command(cmd)
    for line in out.stdout.split('\n'):
        for opt in line.split():
            options.append(opt.lower())

    return options

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
    def __init__(self, start:str, end: str, cluster: str) -> None:

        self.start = start
        self. end = end
        self.cluster = cluster
        self.sacct = "/usr/bin/sacct"
        self.squeue = "/usr/bin/squeue"
        self.sacctmgr = "/usr/bin/sacctmgr"
        cache_root = "/tmp"
        self.stats = Statistics()
        self.cache = f"{cache_root}/slurm"
        try:
            os.makedirs(self.cache, 0o777, exist_ok=True)
        except OSError as e:
            log.error("Unable to create cache directory {self.cache}")
            log.error(e.strerror)
            raise
        self.DEFAULT_SLURM_FORMAT = "jobid,user,account,cluster,partition,ncpus,nnodes,submit,start,end,elapsedraw,state,admincomment"
        self.options = "--allusers --duplicates --parsable2 --allocations --noheader"
        #TODO fix this later
        self.slurm_avail_fmt = self.DEFAULT_SLURM_FORMAT
        self.slurm_fmt_t = namedtuple('slurm_fmt_t', self.DEFAULT_SLURM_FORMAT)
        self.c_fmt_t = namedtuple('c_fmt_t', ['cost'])

    def get_slurm_format(self):

        return ','.join(self.DEFAULT_SLURM_FORMAT)

    def _construct_command(self) -> str:

        args = f"{self.sacct} {self.options} " \
                f"-M {self.cluster} "\
                f"--start={self.start} " \
                f"--end={self.end} -o "\
                f"{self.DEFAULT_SLURM_FORMAT}"
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

        cmd = f"{self.squeue} --json"
        with open(_queue_rec_file, 'w') as fp:
            output = run_command(cmd, stdout=fp)
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
            output = run_command(cmd, stdout=fp)
            if output.returncode:
                log.error("Could not fetch slurm records")
        return _job_rec_file

    def parse_admincomment(self, comment: str):

        return json.loads(comment)

    def get_output_format(self, azcost: azurecost):

        az_fmt = azcost.get_azcost_job_format()
        #slurm_fmt =  self.get_slurm_format()

        return namedtuple('out_fmt_t', list(self.slurm_fmt_t._fields + az_fmt._fields + self.c_fmt_t._fields))

    def process_jobs(self, azcost: azurecost, jobsfp, out_fmt_t):

        _job_rec_file = self.fetch_job_records()
        running = self.process_queue()
        fp = open(_job_rec_file, newline='')
        reader = csv.reader(fp, delimiter='|')
        writer = csv.writer(jobsfp, delimiter=',')

        for row in map(self.slurm_fmt_t._make, reader):
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
            except json.JSONDecodeError as e:
                log.debug(f"Cannot parse admincomment job={row.jobid} cluster={row.cluster}")
                self.stats.admincomment_err += 1
                self.stats.unprocessed += 1
                continue
            charge_factor = float(row.ncpus) / float(cpupernode)

            az_fmt = azcost.get_azcost_job(sku_name, region, spot)
            charged_cost = ((az_fmt.rate/3600) * float(row.elapsedraw)) * charge_factor
            c_fmt = self.c_fmt_t(cost=charged_cost)
            if (region,sku_name) not in self.stats.cost_per_sku:
                self.stats.cost_per_sku[(region,sku_name)] = 0
            self.stats.cost_per_sku[(region,sku_name)] += charged_cost

            out_row = []
            for f in out_fmt_t._fields:
                if f in self.slurm_fmt_t._fields:
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

class CostDriver:
    def __init__(self, azcost: azurecost, config: dict):

        self.azcost = azcost
        self.cluster = config['cluster_name']

    def run(self, start: datetime, end: datetime, out: str):

        sacct_start = start.isoformat()
        sacct_end = end.isoformat()
        cost_slurm = CostSlurm(start=sacct_start, end=sacct_end, cluster=self.cluster)
        os.makedirs(out, exist_ok=True)

        jobs_csv = os.path.join(out, "jobs.csv")
        part_csv = os.path.join(out, "partition.csv")
        part_hourly = os.path.join(out, "partition_hourly.csv")

        fmt = self.azcost.get_azcost_job_format()
        out_fmt_t = cost_slurm.get_output_format(self.azcost)
        with open(jobs_csv, 'w') as fp:
            writer = csv.writer(fp, delimiter=',')
            writer.writerow(list(out_fmt_t._fields))
            cost_slurm.process_jobs(azcost=self.azcost, jobsfp=fp, out_fmt_t=out_fmt_t)

        fmt = self.azcost.get_azcost_nodearray_format()
        with open(part_csv, 'w') as fp:
            writer = csv.writer(fp, delimiter=',')
            writer.writerow(list(fmt._fields))
            count = self.azcost.get_azcost_nodearray(fp, start=sacct_start, end=sacct_end)
        cost_slurm.stats.display()