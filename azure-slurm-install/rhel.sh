#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
#
set -e
INSTALLED_FILE=/etc/azslurm-bins.installed
if [ -e $INSTALLED_FILE ]; then
    exit 0
fi

SLURM_ROLE=$1
SLURM_VERSION=$2
OS_VERSION=$(cat /etc/os-release  | grep VERSION_ID | cut -d= -f2 | cut -d\" -f2 | cut -d. -f1)
OS_ID=$(cat /etc/os-release  | grep ^ID= | cut -d= -f2 | cut -d\" -f2 | cut -d. -f1)

if [ "$OS_VERSION" -lt "8" ]; then
    echo "RHEL versions < 8 no longer supported"
    exit 1
fi

if [ "${OS_ID,,}" == "rhel" ]; then
        dnf -y install -y perl-Switch
        dnf -y install https://dl.fedoraproject.org/pub/epel/epel-release-latest-8.noarch.rpm
    else
        yum -y install epel-release
        dnf -y --enablerepo=powertools install -y perl-Switch
fi
yum -y install munge jq
slurm_packages="slurm slurm-libpmi slurm-devel slurm-pam_slurm slurm-perlapi slurm-torque slurm-openlava slurm-example-configs slurm-contribs"
sched_packages="slurm-slurmctld slurm-slurmdbd slurm-slurmrestd"
execute_packages="slurm-slurmd"

INSIDERS=$(/opt/cycle/jetpack/bin/jetpack config slurm.insiders False)

if [[ "$OS_VERSION" == "9" ]]; then
    if [[ "$INSIDERS" == "True" ]]; then
        cp slurmel9insiders.repo /etc/yum.repos.d/slurm.repo
    else
        cp slurmel9.repo /etc/yum.repos.d/slurm.repo
    fi
elif [[ "$OS_VERSION" == "8" ]]; then
    if [[ "$INSIDERS" == "True" ]]; then
        cp slurmel8insiders.repo /etc/yum.repos.d/slurm.repo
    else
        cp slurmel8.repo /etc/yum.repos.d/slurm.repo
    fi
else
    echo "Unsupported OS version: $OS_VERSION"
    exit 1
fi

## This package is pre-installed in all hpc images used by cyclecloud, but if customer wants to
## build an image from generic marketplace images then this package sets up the right gpg keys for PMC.
if [ ! -e /etc/yum.repos.d/microsoft-prod.repo ];then
    curl -sSL -O https://packages.microsoft.com/config/rhel/$OS_VERSION/packages-microsoft-prod.rpm
    rpm -i packages-microsoft-prod.rpm
    rm packages-microsoft-prod.rpm
fi
for pkg in $slurm_packages; do
    yum -y install "${pkg}-${SLURM_VERSION}*" --disableexcludes slurm
done
if [ ${SLURM_ROLE} == "scheduler" ]; then
    for pkg in $sched_packages; do
        yum -y install "${pkg}-${SLURM_VERSION}*" --disableexcludes slurm
    done
fi

if [ ${SLURM_ROLE} == "execute" ]; then
    for pkg in $execute_packages; do
        yum -y install "${pkg}-${SLURM_VERSION}*" --disableexcludes slurm
    done
fi
touch $INSTALLED_FILE

exit

