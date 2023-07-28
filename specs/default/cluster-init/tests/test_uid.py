#!/opt/cycle/jetpack/system/embedded/bin/python -m pytest
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
import subprocess
import jetpack.config


def test_slurm_uid():
    suid = jetpack.config.get('slurm.user.uid', "11100")
    suser = jetpack.config.get('slurm.user.name', "slurm")
    muid = jetpack.config.get('munge.user.uid', "11101")
    muser = jetpack.config.get('munge.user.name', "munge")

    # Check that slurm uid and username match what is in data store
    assert suser in subprocess.check_output(['grep', suid, '/etc/passwd']).decode()
    assert muser in subprocess.check_output(['grep', muid, '/etc/passwd']).decode()

