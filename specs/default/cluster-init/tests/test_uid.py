#!/opt/cycle/jetpack/system/embedded/bin/python -m pytest
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
import subprocess
import jetpack.config


def test_slurm_uid():
    suid = str(jetpack.config.get('slurm.user.uid')).strip()
    suser = jetpack.config.get('slurm.user.name').strip()
    muid = str(jetpack.config.get('munge.user.uid')).strip()
    muser = jetpack.config.get('munge.user.name').strip()

    # Check that slurm uid and username match what is in data store
    assert suser in subprocess.check_output(['grep', suid, '/etc/passwd'])

    # Check that munge uid and username match what is in data store
    assert muser in subprocess.check_output(['grep', muid, '/etc/passwd'])
