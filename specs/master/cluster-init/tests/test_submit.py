#!/opt/cycle/jetpack/system/embedded/bin/python -m pytest
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
#

import os
import subprocess
import tempfile
import time
import uuid


def test_hello_world():
    script_path = os.path.expanduser("~/hello_world.sh")
    job_name = str(uuid.uuid4())
    with open(script_path, 'w') as fw:
        fw.write(
"""#!/bin/bash
#
#SBATCH --job-name={job_name}
#SBATCH --output=test_hello_world.{job_name}.txt
#
#SBATCH --ntasks=1
srun hostname""".format(job_name=job_name))
    
    subprocess.check_call(["sbatch", script_path])

    deadline = time.time() + 20 * 60
    while time.time() < deadline:
        time.sleep(1)
        stdout = subprocess.check_output(['squeue', '--format', "%j", "-h"])
        if job_name not in stdout:
            return
    raise AssertionError("Timed out waiting for job %s to finish" % job_name)


def test_single_switch():
    script_path = os.path.expanduser("~/hello_world.sh")
    job_name = str(uuid.uuid4())
    with open(script_path, 'w') as fw:
        fw.write(
"""#!/bin/bash
#
#SBATCH --job-name={job_name}
#SBATCH --output=test_hello_world.{job_name}.txt
#
#SBATCH --switches 1
srun hostname""".format(job_name=job_name))
    
    subprocess.check_call(["sbatch", script_path])

    deadline = time.time() + 20 * 60
    while time.time() < deadline:
        time.sleep(1)
        stdout = subprocess.check_output(['squeue', '--format', "%j", "-h"])
        if job_name not in stdout:
            return
    raise AssertionError("Timed out waiting for job %s to finish" % job_name)