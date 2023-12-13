#!/usr/bin/env bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
#
set -e
INSALLED_FILE=/etc/azslurm-bins.installed
if [ -e $INSALLED_FILE ]; then
    exit 0
fi

SLURM_ROLE=$1
SLURM_VERSION=$2

if [[ $SLURM_VERSION != "23.02.6-1" ]];then
    echo "Only slurm version 23.02.6 is supported"
    exit 1
fi

apt update
apt -y install munge
apt -y install python3 python3.8-venv python3-pip

PACKAGE_DIR=slurm-pkgs-debian10
dpkg -i --force-all $(ls $PACKAGE_DIR/*${SLURM_VERSION}*.deb | grep -v -e slurmdbd -e slurmctld)

if [[ ${SLURM_ROLE} == "scheduler" ]]; then
    dpkg -i --force-all $PACKAGE_DIR/slurm-slurmctld_${SLURM_VERSION}*.deb
    dpkg -i --force-all $PACKAGE_DIR/slurm-slurmdbd_${SLURM_VERSION}*.deb
fi

apt -y --fix-broken install
touch $INSALLED_FILE