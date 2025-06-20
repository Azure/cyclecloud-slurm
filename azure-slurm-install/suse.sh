#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
#
set -e
set -x

SLURM_ROLE=$1
SLURM_VERSION=$(echo $2 | cut -d- -f1)


which munge 2>/dev/null
if [ $? != 0 ]; then
    zypper install -y munge || exit 1
fi

which python3 2>/dev/null
if [ $? != 0 ]; then
    zypper install -y python3 || exit 1
fi

set -e 

if [ ${SLURM_ROLE} == "scheduler" ]; then
    zypper install -y slurm-${SLURM_VERSION} \
                      slurm-slurmdbd-${SLURM_VERSION} \
                      slurm-lua-${SLURM_VERSION} \
                      slurm-sql-${SLURM_VERSION}
else
    zypper install -y slurm-${SLURM_VERSION}
fi

for fil in slurm.conf cgroup.conf slurmdbd.conf; do
    if [ -e /etc/slurm/$fil ]; then
        if [ ! -L /etc/slurm/$fil ]; then
            mv /etc/slurm/$fil /etc/slurm/$fil.suse_example
        fi
    fi
done