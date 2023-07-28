#!/bin/bash
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
OS_VERSION=$(cat /etc/os-release  | grep VERSION_ID | cut -d= -f2 | cut -d\" -f2 | cut -d. -f1)

yum -y install epel-release
yum -y install munge
if [ "$OS_VERSION" -gt "7" ]; then
    dnf -y --enablerepo=powertools install -y perl-Switch
else
    yum -y install python3
fi


if [ ${SLURM_ROLE} == "scheduler" ]; then
    yum  -y install $(ls slurm-pkgs/*${SLURM_VERSION}.el${OS_VERSION}*.rpm)
else
    yum  -y install $(ls slurm-pkgs/*${SLURM_VERSION}.el${OS_VERSION}*.rpm | grep -v slurmdbd)
fi

touch $INSALLED_FILE
