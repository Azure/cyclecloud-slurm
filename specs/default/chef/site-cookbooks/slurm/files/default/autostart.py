#!/usr/bin/env python

#from sge import get_sge_jobs, get_sge_job_details
import jetpack.config
import subprocess

def _get_jobs():
    jobs = get_slurm_jobs()

    # Process all the jobs
    autoscale_jobs = []
    for job in jobs.splitlines():

        job_id, job_cores, job_state = job.split('|')
        slot_type = 'execute'

        job = {
            'name': job_id,
            'nodearray': slot_type,
            'request_cpus': int(job_cores),
        }

        autoscale_jobs.append(job)

    return autoscale_jobs

def get_slurm_jobs():
    # Returns jobs in JOBID|CPUS|STATE format
    args = ['/bin/squeue', '-h', '-t', 'RUNNING,PENDING', '--format=%i|%C|%T']
    result = subprocess.check_output(args)
    return result

if __name__ == "__main__":
    import jetpack.autoscale
    jetpack.autoscale.scale_by_jobs(_get_jobs())
