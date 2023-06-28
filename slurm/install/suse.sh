#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
#

INSALLED_FILE=/etc/azslurm-bins.installed
if [ -e $INSALLED_FILE ]; then
    exit 0
fi

SLURM_ROLE=$1
SLURM_VERSION=$(echo $2 | cut -d. -f1-2 | sed 's/\./_/g')


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
    zypper install -y slurm_${SLURM_VERSION} \
                      slurm_${SLURM_VERSION}-slurmdbd \
                      slurm_${SLURM_VERSION}-lua \
                      slurm_${SLURM_VERSION}-sql
else
    zypper install -y slurm_${SLURM_VERSION} \
fi

for fil in slurm.conf cgroup.conf slurmdbd.conf; do
    if [ -e /etc/slurm/$fil ]; then
        if [ ! -L /etc/slurm/$fil ]; then
            mv /etc/slurm/$fil /etc/slurm/$fil.suse_example
        fi
    fi
done

touch $INSALLED_FILE
