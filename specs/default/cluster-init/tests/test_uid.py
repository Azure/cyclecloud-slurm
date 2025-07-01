#!/opt/cycle/jetpack/system/embedded/bin/python -m pytest
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
import subprocess
import jetpack.config


def test_slurm_uid():
    suid = jetpack.config.get('slurm.user.uid')
    suser = jetpack.config.get('slurm.user.name', 'slurm')
    muid = jetpack.config.get('munge.user.uid')
    muser = jetpack.config.get('munge.user.name', 'munge')
    # Check that slurm uid and username match what is in data store
    assert subprocess.check_output(["id", "-u", suser]).decode().strip() == str(suid)

    assert subprocess.check_output(["id", "-u", muser]).decode().strip() == str(muid)
